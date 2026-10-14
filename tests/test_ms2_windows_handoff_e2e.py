"""Synthetic only. No Watcher/MS2/Excel, brokerage or real market records."""
import json
import os
import subprocess
import tempfile
import time
import unittest
from multiprocessing import shared_memory
from pathlib import Path
from unittest.mock import patch

from scripts import ms2_nonblocking_handoff as handoff
from scripts.ms2_ps_python_bridge import start_bridge, publish_into, OFF_GENERATION, _store
from scripts.ms2_offline_observation_writer import exclusive_writer_lock
from scripts.ms2_watcher_sidecar_contract import audit_sidecar_bytes
from tests.test_ms2_ps_python_bridge import _board, RELATIVE, ROOT


class WindowsHandoffE2ETests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            session.stop(0.1)
        self.tmp.cleanup()

    def start(self, **kw):
        session = start_bridge(self.root, RELATIVE, enabled=True, **kw)
        self.sessions.append(session)
        self.assertEqual(session.status, "STARTED", session.reason)
        return session

    def wait(self, predicate):
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("bounded worker deadline exceeded")

    def test_ps51_mapping_worker_durable_reread(self):
        session = self.start()
        if os.name == "nt":
            result = subprocess.run([
                "powershell.exe", "-NoProfile", "-File",
                str(ROOT / "tests/ms2_handoff_e2e_producer.ps1"),
                "-MapName", session.map_name,
            ], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            aggregate = json.loads(result.stdout.strip())
            self.assertEqual(aggregate["status"], "ACCEPTED")
            self.assertEqual(aggregate["ps_major"], 5)
            print("PS51_E2E_SUBMIT_MS=" + str(aggregate["elapsed_ms"]))
        else:
            self.assertEqual(session.submit_capture(_board(data_freshness="STALE"))["status"], "ACCEPTED")
        self.wait(lambda: session.metrics()["durable"] == 1)
        raw = (self.root / RELATIVE).read_bytes()
        row = json.loads(raw)
        self.assertFalse(row["snapshot_atomic"])
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertIsNone(row["event_time"])
        self.assertIsNone(row["available_at"])
        self.assertIsNone(row["levels"][0]["bid_qty"])
        self.assertEqual(row["levels"][0]["ask_qty"], 0)
        audit = audit_sidecar_bytes(raw)
        self.assertEqual(audit["close_state"], "NOT_CLOSED")
        self.assertEqual(audit["eligible_observed_n"], 0)
        session.stop()
        again = self.start()
        self.assertEqual(again.submit_capture(_board(data_freshness="STALE"))["status"], "ACCEPTED")
        self.wait(lambda: handoff._load(again._shm.buf, handoff._OFF_DUPLICATES) == 1)
        self.assertEqual((self.root / RELATIVE).read_bytes(), raw)

    def test_both_entrypoints_share_owner_lock(self):
        first = self.start()
        second = handoff.start_handoff(self.root, RELATIVE, enabled=True)
        self.sessions.append(second)
        self.assertEqual(second.status, "ALREADY_RUNNING")
        self.assertTrue(first._process.is_alive())

    def test_spawn_failure_releases_lock_and_owned_mapping(self):
        with patch.object(handoff, "get_context") as context:
            context.return_value.Process.return_value.start.side_effect = OSError("synthetic start failure")
            failed = handoff.start_handoff(self.root, RELATIVE, enabled=True)
        self.assertEqual(failed.status, "START_FAILED")
        self.assertEqual(failed.reason, "WORKER_START_FAILED")
        self.assertIsNone(failed._shm)
        self.assertIsNone(failed._lock_fd)
        self.start()

    def test_mapping_collision_never_unlinks_other_owner(self):
        name = "c" + __import__("uuid").uuid4().hex[:11]
        other = shared_memory.SharedMemory(create=True, name=name, size=handoff.SHM_SIZE)
        try:
            other.buf[0:4] = b"KEEP"
            failed = handoff.start_handoff(self.root, RELATIVE, enabled=True, map_name=name)
            self.assertEqual(failed.status, "START_FAILED")
            attached = shared_memory.SharedMemory(name=name)
            try:
                self.assertEqual(bytes(attached.buf[:4]), b"KEEP")
            finally:
                attached.close()
        finally:
            other.close()
            if os.name != "nt":
                other.unlink()
        self.start()

    def test_worker_lease_refuses_restart_after_owner_lock_lost(self):
        session = self.start(fault=handoff.FAULT_HOLD)
        # Model OS releasing owner's file lock after an abrupt owner exit.
        handoff._drop_lifecycle_lock(session._lock_fd)
        session._lock_fd = None
        refused = handoff.start_handoff(self.root, RELATIVE, enabled=True)
        self.sessions.append(refused)
        self.assertEqual(refused.status, "ALREADY_RUNNING")
        self.assertTrue(session._process.is_alive())
        session._process.kill()
        session._process.join(2)
        session.stop()
        self.start()

    def test_corrupt_header_generation_and_indices_fail_closed(self):
        for fault in ("header", "generation", "indices"):
            with self.subTest(fault=fault):
                session = self.start(fault=handoff.FAULT_HOLD)
                if fault == "header":
                    session._shm.buf[176] = 0
                elif fault == "generation":
                    _store(session._shm.buf, OFF_GENERATION, session._generation + 1)
                else:
                    handoff._store(session._shm.buf, handoff._OFF_READ, 1)
                self.wait(lambda: session.metrics()["fail_closed"] == 1)
                self.assertEqual(session.metrics()["durable"], 0)
                self.assertFalse((self.root / RELATIVE).exists())
                session.stop()

    def test_corrupt_record_and_stale_generation(self):
        session = self.start()
        self.assertEqual(publish_into(session._shm.buf, b"x" * 2048, session._generation)["status"], "ACCEPTED")
        self.wait(lambda: session.metrics()["fail_closed"] == 1)
        self.assertFalse((self.root / RELATIVE).exists())
        blob = handoff.pack_capture(_board())["record"]
        self.assertEqual(publish_into(session._shm.buf, blob, session._generation + 1)["reason"], "GENERATION_MISMATCH")
        self.assertEqual(session.metrics()["durable"], 0)

    def test_real_writer_lock_never_blocks_producer(self):
        session = self.start()
        with exclusive_writer_lock(self.root / "data/private/ms2_sidecar"):
            result = session.submit_capture(_board())
            self.assertEqual(result["status"], "ACCEPTED")
            self.assertFalse(result["blocking_syscall"])
            self.wait(lambda: session.metrics()["failures"] == 1)
        self.assertEqual(session.metrics()["durable"], 0)
        self.assertFalse((self.root / RELATIVE).exists())

    @unittest.skipUnless(os.name == "nt", "Windows last-handle semantics")
    def test_windows_mapping_survives_until_last_foreign_handle_closes(self):
        session = self.start()
        name = session.map_name
        foreign = shared_memory.SharedMemory(name=name)
        session.stop()
        still_open = shared_memory.SharedMemory(name=name)
        still_open.close()
        foreign.close()
        with self.assertRaises(FileNotFoundError):
            shared_memory.SharedMemory(name=name)

    def test_invalid_private_path_is_refused_before_spawn(self):
        with patch.object(handoff, "get_context") as context:
            session = handoff.start_handoff(self.root, "public.jsonl", enabled=True)
        self.assertEqual(session.status, "START_FAILED")
        context.assert_not_called()
        self.assertFalse((self.root / "data").exists())


if __name__ == "__main__":
    unittest.main()
