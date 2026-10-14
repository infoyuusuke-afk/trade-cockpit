import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import fcntl

from scripts.ms2_nonblocking_handoff import (
    DROP_POLICY,
    EXISTING_BOARD_COM_READS,
    FAULT_BLOCK_IO,
    FAULT_BLOCK_UNCHECKED,
    FAULT_CRASH,
    FAULT_DISK_FULL,
    FAULT_FILE_LOCK,
    FAULT_HOLD,
    FAULT_PERMISSION,
    FAULT_STALL,
    QUEUE_CAPACITY,
    RESTART_POLICY,
    SUBMIT_DEADLINE_NS,
    _worker_entry,
    _worker_loop,
    acceptance_verdict,
    handoff_contract,
    pack_capture,
    start_handoff,
    watcher_surface,
    windows_acceptance_checklist,
)
from scripts.ms2_offline_observation_writer import record_captured_observation
from scripts.ms2_watcher_sidecar_contract import audit_sidecar_bytes

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "data/private/ms2_sidecar/board.jsonl"
WATCHER_SHA = "4babc10249c2ebd603b28dfc20542224ce4b7b646fe16111ff398f76d2f60c1b"
HISTORY_SHA = "6da1968f71d9e54011d3180d934a683ba9829833d1d4e743fbd42b4172f2d554"
CONTRACT_SHA = "ffc45ca155d297506ce2f9f8758531e5a721df8f4dfef26c0dc0793b0c4ed80b"


def _level(number, read_at=None, *, bid=100, ask=101, bid_qty=None, ask_qty=None):
    payload = {"Level": number, "BidPrice": bid, "AskPrice": ask, "BidQty": bid_qty, "AskQty": ask_qty}
    if read_at is not None:
        payload["read_at"] = read_at
    return payload


def _board(**overrides):
    payload = {
        "symbol": "285A.T",
        "market": "TSE",
        "poll_seq": 3,
        "source": "offline-harness",
        "levels": [
            _level(1, "2026-10-14T01:00:00.010+09:00"),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ],
        "watcher_observed_at": "2026-10-14T01:00:00.000+09:00",
    }
    payload.update(overrides)
    return payload


class NonblockingHandoffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            try:
                session.stop(0.05)
            except Exception:
                pass
        self._tmp.cleanup()

    def _start(self, **kwargs):
        kwargs.setdefault("enabled", True)
        kwargs.setdefault("relative", RELATIVE)
        session = start_handoff(self.root, **kwargs)
        self.sessions.append(session)
        return session

    def _wait(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def _rows(self):
        path = self.root / RELATIVE
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_01_writer_normal_and_copy_is_isolated(self):
        disabled = self._start(enabled=False)
        self.assertEqual(disabled.status, "DISABLED")
        self.assertEqual(disabled.submit(_board())["status"], "DISABLED")
        self.assertFalse((self.root / "data").exists())
        session = self._start()
        self.assertEqual(session.status, "STARTED")
        capture = _board(levels=[
            _level(1, "2026-10-14T01:00:00.010+09:00", bid=100, ask=101, bid_qty=None, ask_qty=0),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ])
        accepted = session.submit(capture)
        self.assertEqual(accepted["status"], "ACCEPTED")
        capture["levels"][0]["BidPrice"] = 999
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertEqual(row["levels"][0]["bid"], 100)
        self.assertIsNone(row["levels"][0]["bid_qty"])
        self.assertEqual(row["levels"][0]["ask_qty"], 0)
        self.assertFalse(row["snapshot_atomic"])
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertFalse(row["order_proven"])
        self.assertIsNone(row["exchange_sequence"])
        self.assertIsNone(row["event_time"])
        self.assertIsNone(row["available_at"])
        self.assertEqual(row["available_at_basis"], "NOT_DEMONSTRATED")
        self.assertNotIn("+09:00", row["event_time"] or "")
        audited = audit_sidecar_bytes((self.root / RELATIVE).read_bytes())
        self.assertEqual(audited["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(audited["close_state"], "NOT_CLOSED")
        self.assertEqual(audited["eligible_observed_n"], 0)
        self.assertEqual(audited["synthetic_n"], 0)
        self.assertNotEqual(row["source"], "synthetic-fixture")
        self.assertEqual(session.metrics()["com_reads_added"], 0)
        self.assertLessEqual(accepted["elapsed_ns"], SUBMIT_DEADLINE_NS)

    def test_02_disk_stall_does_not_block_submit(self):
        def blocking_write(fd, payload):
            time.sleep(0.2)
            os.write(fd, payload)

        started = time.monotonic()
        record_captured_observation(
            self.root, RELATIVE, _board(poll_seq=1), enabled=True, hooks={"write": blocking_write},
        )
        self.assertGreater(time.monotonic() - started, 0.15)
        stalled_root = self.root / "stall"
        stalled_root.mkdir()
        session = start_handoff(stalled_root, RELATIVE, enabled=True, fault=FAULT_BLOCK_IO)
        self.sessions.append(session)
        self.assertEqual(session.status, "STARTED")
        self.assertEqual(session.submit(_board(poll_seq=2))["status"], "ACCEPTED")
        time.sleep(0.05)
        samples = []
        for seq in range(20, 40):
            item = session.submit(_board(poll_seq=seq))
            samples.append(item["elapsed_ns"])
            self.assertIn(item["status"], {"ACCEPTED", "DROPPED"})
        self.assertLessEqual(max(samples), SUBMIT_DEADLINE_NS)
        self.assertGreater(session.metrics()["dropped_newest"], 0)
        self.assertEqual(session.metrics()["durable"], 0)
        self.assertTrue(session.metrics()["worker_alive"])

    def test_03_disk_full_is_counted_and_not_retried(self):
        session = self._start()
        session.set_fault(FAULT_DISK_FULL)
        self.assertEqual(session.submit(_board())["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["failures"] == 1))
        self.assertEqual(session.metrics()["last_reason"], "DISK_FULL")
        time.sleep(0.1)
        self.assertEqual(session.metrics()["failures"], 1)
        self.assertFalse((self.root / RELATIVE).exists())

    def test_04_permission_denied_is_isolated(self):
        session = self._start()
        session.set_fault(FAULT_PERMISSION)
        item = session.submit(_board())
        self.assertEqual(item["status"], "ACCEPTED")
        self.assertLessEqual(item["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertTrue(self._wait(lambda: session.metrics()["failures"] == 1))
        self.assertEqual(session.metrics()["last_reason"], "WRITE_FAILED")
        self.assertFalse((self.root / RELATIVE).exists())

    def test_05_file_lock_does_not_wait(self):
        session = self._start()
        session.set_fault(FAULT_FILE_LOCK)
        item = session.submit(_board())
        self.assertEqual(item["status"], "ACCEPTED")
        self.assertLessEqual(item["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertTrue(self._wait(lambda: session.metrics()["failures"] == 1))
        self.assertEqual(session.metrics()["last_reason"], "WRITE_LOCKED")
        self.assertEqual(session.metrics()["lock_timeouts"], 0)

    def test_06_worker_crash_is_detected_without_blocking(self):
        session = self._start()
        session.set_fault(FAULT_CRASH)
        self.assertTrue(self._wait(lambda: not session._process.is_alive()))
        time.sleep(0.2)
        item = session.submit(_board())
        self.assertEqual(item["status"], "WORKER_DEAD")
        self.assertLessEqual(item["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertGreater(session.metrics()["dead_drops"], 0)
        self.assertEqual(session.metrics()["durable"], 0)

    def test_07_stopped_worker_rejects_new_work(self):
        session = self._start()
        session.set_fault(FAULT_STALL)
        time.sleep(0.2)
        stalled = session.submit(_board())
        self.assertEqual(stalled["status"], "ACCEPTED")
        self.assertLessEqual(stalled["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertGreater(session.metrics()["stall_seen"], 0)
        session.stop()
        stopped = session.submit(_board(poll_seq=4))
        self.assertEqual(stopped["status"], "WORKER_STOPPED")
        self.assertLessEqual(stopped["elapsed_ns"], SUBMIT_DEADLINE_NS)

    def test_08_queue_full_drops_newest(self):
        session = self._start(fault=FAULT_HOLD)
        self.assertEqual(session.metrics()["queue_capacity"], QUEUE_CAPACITY)
        self.assertEqual(DROP_POLICY, "DROP_NEWEST")
        accepted = 0
        dropped = 0
        samples = []
        for seq in range(1, QUEUE_CAPACITY + 5):
            item = session.submit(_board(poll_seq=seq))
            samples.append(item["elapsed_ns"])
            accepted += item["status"] == "ACCEPTED"
            dropped += item["status"] == "DROPPED"
        self.assertEqual(accepted, QUEUE_CAPACITY)
        self.assertEqual(dropped, 4)
        self.assertEqual(session.metrics()["dropped_newest"], 4)
        self.assertEqual(session.metrics()["durable"], 0)
        self.assertLessEqual(max(samples), SUBMIT_DEADLINE_NS)

    def test_09_slow_serialization_is_not_on_the_producer_path(self):
        session = self._start(fault=FAULT_HOLD)
        huge = _board(source="x" * (8 * 1024 * 1024))
        refused = session.submit(huge)
        self.assertEqual(refused["reason"], "SOURCE_ABSENT")
        self.assertLessEqual(refused["elapsed_ns"], SUBMIT_DEADLINE_NS)

        class SlowNumber:
            def __float__(self):
                time.sleep(1)
                return 1.0

        hostile = _board(poll_seq=5, levels=[_level(1, ask_qty=SlowNumber())])
        blocked = session.submit(hostile)
        self.assertEqual(blocked["status"], "REFUSED")
        self.assertLessEqual(blocked["elapsed_ns"], SUBMIT_DEADLINE_NS)
        original = json.dumps

        def boom(*args, **kwargs):
            raise AssertionError("producer called json.dumps")

        json.dumps = boom
        calls = {"flock": 0}
        real_flock = fcntl.flock

        def counting_flock(fd, op):
            calls["flock"] += 1
            return real_flock(fd, op)

        fcntl.flock = counting_flock
        try:
            item = session.submit(_board(poll_seq=6))
        finally:
            json.dumps = original
            fcntl.flock = real_flock
        self.assertEqual(item["status"], "ACCEPTED")
        self.assertEqual(calls["flock"], 0)
        self.assertFalse(item["blocking_syscall"])
        self.assertLessEqual(item["elapsed_ns"], SUBMIT_DEADLINE_NS)

    def test_10_duplicate_start_is_refused(self):
        first = self._start()
        second = self._start()
        self.assertEqual(second.status, "ALREADY_RUNNING")
        self.assertEqual(second.reason, "DUPLICATE_START")
        self.assertIsNone(second._process)
        self.assertTrue(first._process.is_alive())
        self.assertEqual(first.submit(_board())["status"], "ACCEPTED")

    def test_11_stop_is_bounded_and_restart_discards_unpublished(self):
        session = self._start(fault=FAULT_BLOCK_UNCHECKED)
        stopped = session.stop()
        self.assertLess(stopped["elapsed_s"], 0.6)
        self.assertTrue(stopped["killed"])
        self.assertFalse(session._process.is_alive())
        private = self.root / "data" / "private" / "ms2_sidecar"
        spill = private / "runtime" / "unpublished"
        spill.mkdir(parents=True, exist_ok=True)
        (spill / "old.bin").write_bytes(b"STALE-QUEUE")
        (private / ".board.jsonl.9.tmp").write_bytes(b"PARTIAL")
        restarted = self._start()
        self.assertEqual(restarted.status, "STARTED")
        self.assertGreaterEqual(restarted.metrics()["stale_discarded"], 2)
        self.assertEqual(restarted.metrics()["restart_policy"], RESTART_POLICY)
        self.assertFalse((self.root / RELATIVE).exists())
        quarantined = list((private / "quarantine").rglob("*"))
        blob = b"".join(path.read_bytes() for path in quarantined if path.is_file())
        self.assertIn(b"STALE-QUEUE", blob)
        self.assertIn(b"PARTIAL", blob)

    def test_12_stale_queue_is_not_replayed_on_first_start(self):
        private = self.root / "data" / "private" / "ms2_sidecar"
        unpublished = private / "runtime" / "unpublished"
        unpublished.mkdir(parents=True)
        (unpublished / "left.bin").write_bytes(b"ORPHAN-QUEUE")
        session = self._start()
        self.assertGreaterEqual(session.metrics()["stale_discarded"], 1)
        self.assertEqual(session.submit(_board())["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        text = (self.root / RELATIVE).read_bytes()
        self.assertNotIn(b"ORPHAN-QUEUE", text)

    def test_13_invalid_quantity_is_not_filled_with_zero(self):
        session = self._start(fault=FAULT_HOLD)
        missing = pack_capture(_board())
        self.assertTrue(missing["ok"])
        invalid = session.submit(_board(levels=[_level(1, ask_qty=-1)]))
        self.assertEqual(invalid["reason"], "QTY_INVALID")
        text = session.submit(_board(poll_seq=4, levels=[_level(1, ask_qty="OVER")]))
        self.assertEqual(text["status"], "REFUSED")
        self.assertLessEqual(invalid["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertGreater(session.metrics()["invalid_quantity"], 0)
        self.assertFalse((self.root / RELATIVE).exists())
        session.set_fault(0)
        explicit = session.submit(_board(
            poll_seq=8,
            levels=[_level(1, "2026-10-14T01:00:00.010+09:00", bid_qty=None, ask_qty=0)],
        ))
        self.assertEqual(explicit["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertIsNone(row["top"]["bid_qty"])
        self.assertEqual(row["top"]["ask_qty"], 0)
        stored = (self.root / RELATIVE).read_text(encoding="utf-8").replace(" ", "")
        self.assertIn('"bid_qty":null', stored)
        self.assertNotIn('"bid_qty":0', stored)

    def test_14_missing_and_contradictory_clocks_are_not_guessed(self):
        session = self._start()
        naive = session.submit(_board(watcher_observed_at="2026-10-14 01:00:00"))
        self.assertEqual(naive["reason"], "TIMEZONE_NOT_GUESSED")
        named = session.submit(_board(poll_seq=4, timezone="Asia/Tokyo"))
        self.assertEqual(named["reason"], "TIMEZONE_NOT_GUESSED")
        supplied = session.submit(_board(
            poll_seq=5,
            available_at="2026-10-14T01:00:02.000+09:00",
            available_at_basis="DURABLE_CONSUMER_READ",
        ))
        self.assertEqual(supplied["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertIsNone(row["available_at"])
        self.assertIsNone(row["event_time"])
        self.assertNotIn("JST", (self.root / RELATIVE).read_text(encoding="utf-8"))
        conflict = session.submit(_board(
            poll_seq=6,
            event_time="2026-10-14T01:00:01.000+09:00",
            event_time_basis="EXCHANGE_SUPPLIED",
            watcher_observed_at="2026-10-14T01:00:01.000+09:00",
        ))
        self.assertEqual(conflict["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["fail_closed"] == 1))
        self.assertEqual(len(self._rows()), 1)
        audited = audit_sidecar_bytes((self.root / RELATIVE).read_bytes())
        self.assertEqual(audited["close_state"], "NOT_CLOSED")

    def test_15_suspected_gap_stays_unclosed(self):
        session = self._start()
        gap = {
            "window_size": 300,
            "overlap_with_prev": 0,
            "prev_poll_nonempty": True,
            "new_appended": 20,
        }
        self.assertEqual(session.submit(_board(gap=gap, data_freshness="STALE"))["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertTrue(row["suspected_gap"])
        self.assertEqual(row["data_freshness"], "STALE")
        self.assertEqual(row["gap_diag"]["poll_seq"], 3)
        self.assertNotEqual(row["poll_seq"], row["exchange_sequence"])
        audited = audit_sidecar_bytes((self.root / RELATIVE).read_bytes())
        self.assertIn("GAP_SUSPECTED", audited["reasons"])
        self.assertIn("FRESHNESS_STALE", audited["reasons"])
        self.assertEqual(audited["close_state"], "NOT_CLOSED")
        contradicted = session.submit(_board(poll_seq=9, gap={**gap, "suspected_gap": False}))
        self.assertEqual(contradicted["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["fail_closed"] == 1))
        self.assertEqual(len(self._rows()), 1)

    def test_16_duplicate_event_is_not_appended_twice(self):
        session = self._start()
        self.assertEqual(session.submit(_board())["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        original = (self.root / RELATIVE).read_bytes()
        self.assertEqual(session.submit(_board())["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["duplicates"] == 1))
        self.assertEqual((self.root / RELATIVE).read_bytes(), original)
        self.assertEqual(session.metrics()["last_reason"], "DUPLICATE")

    def test_17_corrupt_jsonl_fails_closed(self):
        session = self._start()
        path = self.root / RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"{not-json\n")
        os.chmod(path, 0o600)
        before = path.read_bytes()
        self.assertEqual(session.submit(_board())["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["fail_closed"] == 1))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(session.metrics()["last_reason"], "DATA_CORRUPT")
        audited = audit_sidecar_bytes(path.read_bytes())
        self.assertEqual(audited["close_state"], "NOT_CLOSED")
        self.assertIn("DATA_CORRUPT", audited["reasons"])

    def test_18_same_input_is_deterministic(self):
        first = pack_capture(_board())
        second = pack_capture(_board())
        self.assertEqual(first["record"], second["record"])
        left = self._start()
        self.assertEqual(left.submit(_board(poll_seq=2))["status"], "ACCEPTED")
        self.assertEqual(left.submit(_board(poll_seq=3))["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: left.metrics()["durable"] == 2))
        left_bytes = (self.root / RELATIVE).read_bytes()
        left.stop()
        other = self.root / "other"
        other.mkdir()
        right = start_handoff(other, RELATIVE, enabled=True)
        self.sessions.append(right)
        self.assertEqual(right.submit(_board(poll_seq=2))["status"], "ACCEPTED")
        self.assertEqual(right.submit(_board(poll_seq=3))["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: right.metrics()["durable"] == 2))
        self.assertEqual((other / RELATIVE).read_bytes(), left_bytes)

    def test_19_no_added_com_and_watcher_bytes_stay(self):
        surface = watcher_surface(ROOT)
        self.assertEqual(surface["sha256"], WATCHER_SHA)
        self.assertEqual(surface["existing_board_com_reads_per_poll"], EXISTING_BOARD_COM_READS)
        self.assertEqual(surface["extra_com_reads"], 0)
        text = (ROOT / "ms2_live/Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8")
        self.assertEqual(text.count("$board = @(Read-BoardDepth"), 1)
        banned = {"Value2", "GetActiveObject", "win32com", "Excel", "Dispatch"}
        self.assertFalse(banned & set(_worker_loop.__code__.co_names))
        self.assertFalse(banned & set(_worker_entry.__code__.co_names))
        session = self._start()
        pid = session.metrics()["worker_pid"]
        command = Path(f"/proc/{pid}/cmdline").read_bytes().lower()
        self.assertNotIn(b"excel", command)
        self.assertNotIn(b"kioxia_rss_live_watcher", command)
        self.assertEqual(session.metrics()["com_reads_added"], 0)
        self.assertEqual(hashlib.sha256((ROOT / "paper_trade_history.json").read_bytes()).hexdigest(), HISTORY_SHA)
        self.assertEqual(hashlib.sha256((ROOT / "scripts/ms2_watcher_sidecar_contract.py").read_bytes()).hexdigest(), CONTRACT_SHA)

    def test_20_price_voice_and_sign_are_not_on_the_writer_path(self):
        session = self._start(fault=FAULT_BLOCK_IO)
        self.assertEqual(session.submit(_board())["status"], "ACCEPTED")
        time.sleep(0.05)
        order = []

        def price():
            order.append("price")

        def sign():
            order.append("sign")

        def voice():
            order.append("voice")

        started = time.monotonic_ns()
        price()
        sign()
        voice()
        item = session.submit(_board(poll_seq=11))
        elapsed = time.monotonic_ns() - started
        self.assertEqual(order, ["price", "sign", "voice"])
        self.assertLessEqual(item["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertLess(elapsed, SUBMIT_DEADLINE_NS)
        self.assertEqual(session.metrics()["durable"], 0)
        contract = handoff_contract()
        self.assertFalse(contract["watcher_modified"])
        self.assertFalse(contract["hard_realtime_guaranteed"])
        self.assertEqual(contract["live_watcher_connection"], "P0_BLOCKED")
        self.assertFalse(contract["real_submit_allowed"])
        verdict = acceptance_verdict(session.metrics())
        self.assertEqual(verdict["hard_realtime_guarantee"], "P0_BLOCKED")
        self.assertEqual(verdict["windows_acceptance"], "NOT_VERIFIED")
        self.assertEqual(verdict["eligible_observed_n"], 0)
        checklist = windows_acceptance_checklist()
        self.assertEqual([item["id"] for item in checklist], ["W1", "W2", "W3", "W4"])
        self.assertTrue(all(item["status"] == "NOT_VERIFIED" for item in checklist))
