import hashlib
import os
import sys
import tempfile
import time
import unittest
from multiprocessing import get_context
from pathlib import Path

from scripts.ms2_bridge_record import pack_capture as record_pack
from scripts.ms2_nonblocking_handoff import (
    FAULT_BLOCK_IO,
    FAULT_BLOCK_UNCHECKED,
    FAULT_DISK_FULL,
    FAULT_FILE_LOCK,
    FAULT_HOLD,
    FAULT_STALL,
    QUEUE_CAPACITY,
    RECORD_SIZE,
    SHM_SIZE,
    SLOT_BASE,
    _OFF_DROPPED,
    _OFF_FLAGS,
    _OFF_GENERATION,
    _OFF_KILL_DROPS,
    _OFF_WRITE,
    pack_capture,
)
from scripts.ms2_ps_python_bridge import (
    OFF_DROPPED,
    OFF_FLAGS,
    OFF_GENERATION,
    OFF_KILL_DROPS,
    OFF_HEARTBEAT,
    OFF_WRITE,
    PRODUCER_RELATIVE,
    START_METHOD,
    SUBMIT_DEADLINE_NS,
    WATCHER_SHA256,
    _attached_publish_main,
    bridge_contract,
    probe_interpreter,
    producer_audit,
    start_bridge,
    watcher_unchanged,
)
from scripts.ms2_watcher_sidecar_contract import audit_sidecar_bytes

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "data/private/ms2_sidecar/board.jsonl"
HISTORY_SHA = "6da1968f71d9e54011d3180d934a683ba9829833d1d4e743fbd42b4172f2d554"
CONTRACT_SHA = "ffc45ca155d297506ce2f9f8758531e5a721df8f4dfef26c0dc0793b0c4ed80b"
WRITER_SHA = "14bea3d3a805dd62d99f91b76677110cecb7427aedb04ea92f1435595f90f722"
SPAWN_MARKER = "import-time"


def _spawn_child(conn):
    conn.send(SPAWN_MARKER)
    conn.close()


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
            _level(1, "2026-10-14T01:00:00.010+09:00", bid_qty=None, ask_qty=0),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ],
        "watcher_observed_at": "2026-10-14T01:00:00.000+09:00",
    }
    payload.update(overrides)
    return payload


class PsPythonBridgeTests(unittest.TestCase):
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
        session = start_bridge(self.root, **kwargs)
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
        import json
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_00_layout_matches_existing_handoff(self):
        self.assertIs(pack_capture, record_pack)
        self.assertEqual(OFF_WRITE, _OFF_WRITE)
        self.assertEqual(OFF_DROPPED, _OFF_DROPPED)
        self.assertEqual(OFF_FLAGS, _OFF_FLAGS)
        self.assertEqual(OFF_GENERATION, _OFF_GENERATION)
        self.assertEqual(OFF_KILL_DROPS, _OFF_KILL_DROPS)
        self.assertEqual(QUEUE_CAPACITY, 8)
        self.assertEqual(RECORD_SIZE, 2048)
        self.assertEqual(SHM_SIZE, SLOT_BASE + 8 * 2048)

    def test_01_normal_message_crosses_a_spawned_process(self):
        disabled = self._start(enabled=False)
        self.assertEqual(disabled.status, "DISABLED")
        self.assertEqual(disabled.submit_capture(_board())["status"], "DISABLED")
        self.assertFalse((self.root / "data").exists())
        session = self._start()
        self.assertEqual(session.status, "STARTED")
        self.assertEqual(session._process._start_method if hasattr(session._process, "_start_method") else START_METHOD, START_METHOD)
        packed = pack_capture(_board())
        self.assertTrue(packed["ok"])
        parent, child = get_context(START_METHOD).Pipe(duplex=False)
        proc = get_context(START_METHOD).Process(
            target=_attached_publish_main,
            args=(session.map_name, packed["record"], child),
        )
        proc.start()
        child.close()
        status = parent.recv()
        proc.join(5)
        self.assertEqual(status, "ACCEPTED")
        self.assertEqual(proc.exitcode, 0)
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertEqual(row["levels"][0]["bid"], 100)
        self.assertIsNone(row["levels"][0]["bid_qty"])
        self.assertEqual(row["levels"][0]["ask_qty"], 0)
        self.assertFalse(row["snapshot_atomic"])
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertEqual(row["poll_seq"], 3)
        self.assertIsNone(row["exchange_sequence"])
        self.assertFalse(row["order_proven"])
        real_open = os.open
        real_dumps = __import__("json").dumps

        def boom_open(*args, **kwargs):
            raise AssertionError("publish opened a file")

        def boom_dumps(*args, **kwargs):
            raise AssertionError("publish serialized json")

        os.open = boom_open
        __import__("json").dumps = boom_dumps
        try:
            again = session.publish_bytes(pack_capture(_board(poll_seq=4))["record"])
        finally:
            os.open = real_open
            __import__("json").dumps = real_dumps
        self.assertEqual(again["status"], "ACCEPTED")
        self.assertFalse(again["blocking_syscall"])
        self.assertEqual(again["com_reads_added"], 0)
        self.assertLessEqual(again["elapsed_ns"], SUBMIT_DEADLINE_NS)

    def test_02_python_absent_is_one_attempt(self):
        result = probe_interpreter("/no/such/ms2-bridge-python")
        self.assertEqual(result["status"], "PYTHON_ABSENT")
        self.assertEqual(result["attempts"], 1)
        self.assertFalse(result["retry"])
        self.assertFalse(result["autostart"])

    def test_03_python_start_failure_does_not_retry(self):
        failed = probe_interpreter(sys.executable, args=("-c", "import sys; raise SystemExit(9)"))
        self.assertEqual(failed["status"], "PYTHON_START_FAILED")
        self.assertEqual(failed["attempts"], 1)
        self.assertFalse(failed["retry"])
        hung = probe_interpreter(sys.executable, timeout_s=0.2, args=("-c", "import time; time.sleep(30)"))
        self.assertEqual(hung["status"], "PYTHON_UNRESPONSIVE")
        self.assertEqual(hung["attempts"], 1)
        self.assertFalse(hung["retry"])
        self.assertLess(hung["elapsed_s"], 1.0)

    def test_04_spawn_does_not_inherit_parent_mutation(self):
        global SPAWN_MARKER
        SPAWN_MARKER = "mutated-in-parent"
        source = (ROOT / "scripts" / "ms2_ps_python_bridge.py").read_text(encoding="utf-8")
        self.assertNotIn("fork", source)
        self.assertIn('START_METHOD = "spawn"', source)
        parent, child = get_context("spawn").Pipe(duplex=False)
        proc = get_context("spawn").Process(target=_spawn_child, args=(child,))
        proc.start()
        child.close()
        self.assertEqual(parent.recv(), "import-time")
        proc.join(5)
        self.assertEqual(proc.exitcode, 0)
        contract = bridge_contract()
        self.assertEqual(contract["start_method"], "spawn")
        self.assertFalse(contract["poll_path_calls_python"])
        self.assertFalse(contract["poll_path_uses_pipe"])

    def test_05_dead_worker_does_not_block_publish(self):
        session = self._start()
        record = pack_capture(_board())["record"]

        def slow_alive():
            time.sleep(0.2)
            return True

        original_alive = session._process.is_alive
        session._process.is_alive = slow_alive
        timed = session.publish_bytes(record)
        self.assertLessEqual(timed["elapsed_ns"], SUBMIT_DEADLINE_NS)
        session._process.is_alive = original_alive
        session._process.kill()
        self.assertTrue(self._wait(lambda: not session._process.is_alive(), timeout=2))
        after = session.publish_bytes(pack_capture(_board(poll_seq=4))["record"])
        self.assertLessEqual(after["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertIn(after["status"], {"ACCEPTED", "DROPPED", "KILL_SWITCH", "REFUSED"})
        observed = session.observe_owner()
        self.assertEqual(observed["status"], "WORKER_DEAD")
        self.assertFalse(observed["retry"])
        killed = session.publish_bytes(pack_capture(_board(poll_seq=5))["record"])
        self.assertEqual(killed["status"], "KILL_SWITCH")
        self.assertLessEqual(killed["elapsed_ns"], SUBMIT_DEADLINE_NS)

    def test_06_unresponsive_worker_stop_is_bounded(self):
        session = self._start(fault=FAULT_BLOCK_UNCHECKED)
        record = pack_capture(_board())["record"]
        accepted = session.publish_bytes(record)
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertLessEqual(accepted["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertEqual(session.metrics()["durable"], 0)
        stopped = session.stop()
        self.assertTrue(stopped["killed"])
        self.assertLess(stopped["elapsed_s"], 0.8)
        self.assertFalse(stopped["retry"])
        self.assertFalse(session._process.is_alive())

    def test_07_stop_unlinks_shared_memory(self):
        session = self._start()
        name = session.map_name
        self.assertTrue(session._process.is_alive())
        session.stop()
        self.assertFalse(session._process.is_alive())
        from multiprocessing import shared_memory
        with self.assertRaises(FileNotFoundError):
            shared_memory.SharedMemory(name=name)

    def test_08_duplicate_start_returns_without_waiting(self):
        first = self._start()
        started = time.monotonic_ns()
        second = self._start()
        elapsed = time.monotonic_ns() - started
        self.assertEqual(second.status, "ALREADY_RUNNING")
        self.assertEqual(second.reason, "DUPLICATE_START")
        self.assertIsNone(second._process)
        self.assertLessEqual(elapsed, SUBMIT_DEADLINE_NS * 4)
        self.assertTrue(first._process.is_alive())

    def test_09_full_queue_drops_newest_deterministically(self):
        session = self._start(fault=FAULT_HOLD)
        statuses = []
        for poll in range(1, 11):
            statuses.append(session.publish_bytes(pack_capture(_board(poll_seq=poll))["record"])["status"])
        self.assertEqual(statuses, ["ACCEPTED"] * 8 + ["DROPPED", "DROPPED"])
        self.assertEqual(session.metrics()["dropped_newest"], 2)
        self.assertEqual(session.metrics()["durable"], 0)
        again = [session.publish_bytes(pack_capture(_board(poll_seq=poll))["record"])["status"] for poll in range(1, 11)]
        self.assertEqual(again, ["DROPPED"] * 10)

    def test_10_oversized_text_is_refused_before_encode(self):
        huge = "x" * 2_000_000
        started = time.monotonic_ns()
        packed = pack_capture(_board(symbol=huge))
        self.assertFalse(packed["ok"])
        self.assertEqual(packed["reason"], "SYMBOL_ABSENT")
        self.assertLessEqual(time.monotonic_ns() - started, SUBMIT_DEADLINE_NS)
        started = time.monotonic_ns()
        hostile = pack_capture(_board(levels=[_level(1, ask_qty=huge)]))
        self.assertFalse(hostile["ok"])
        self.assertLessEqual(time.monotonic_ns() - started, SUBMIT_DEADLINE_NS)
        deep = [{"Level": index} for index in range(1, 12)]
        deep[-1]["AskQty"] = huge
        started = time.monotonic_ns()
        limited = pack_capture(_board(levels=deep))
        self.assertEqual(limited["reason"], "DEPTH_LIMIT")
        self.assertLessEqual(time.monotonic_ns() - started, SUBMIT_DEADLINE_NS)

    def test_11_file_lock_does_not_block_publish(self):
        session = self._start()
        session.set_fault(FAULT_FILE_LOCK)
        record = pack_capture(_board())["record"]
        accepted = session.publish_bytes(record)
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertLessEqual(accepted["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertTrue(self._wait(lambda: session.metrics()["failures"] >= 1))
        self.assertEqual(session.metrics()["com_reads_added"], 0)
        self.assertEqual(session.metrics()["durable"], 0)

    def test_12_disk_full_does_not_block_publish(self):
        session = self._start()
        session.set_fault(FAULT_DISK_FULL)
        accepted = session.publish_bytes(pack_capture(_board())["record"])
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertLessEqual(accepted["elapsed_ns"], SUBMIT_DEADLINE_NS)
        blocked = session.publish_bytes(pack_capture(_board(poll_seq=4))["record"])
        self.assertLessEqual(blocked["elapsed_ns"], SUBMIT_DEADLINE_NS)
        self.assertTrue(self._wait(lambda: session.metrics()["failures"] >= 1))
        session.set_fault(FAULT_BLOCK_IO)
        stalled = session.publish_bytes(pack_capture(_board(poll_seq=5))["record"])
        self.assertEqual(stalled["status"], "ACCEPTED")
        self.assertLessEqual(stalled["elapsed_ns"], SUBMIT_DEADLINE_NS)

    def test_13_kill_switch_and_restart_discard_unpublished(self):
        session = self._start(fault=FAULT_BLOCK_UNCHECKED)
        session.trip_kill_switch()
        dropped = session.publish_bytes(pack_capture(_board())["record"])
        self.assertEqual(dropped["status"], "KILL_SWITCH")
        self.assertLessEqual(dropped["elapsed_ns"], SUBMIT_DEADLINE_NS)
        stopped = session.stop()
        self.assertLess(stopped["elapsed_s"], 0.8)
        private = self.root / "data" / "private" / "ms2_sidecar"
        spill = private / "runtime" / "unpublished"
        spill.mkdir(parents=True, exist_ok=True)
        (spill / "old.bin").write_bytes(b"STALE-QUEUE")
        (private / ".board.jsonl.9.tmp").write_bytes(b"PARTIAL")
        session._process.join(2)
        self.assertFalse(session._process.is_alive())
        restarted = self._start()
        self.assertEqual(restarted.status, "STARTED")
        self.assertGreaterEqual(restarted.metrics()["stale_discarded"], 2)
        self.assertFalse((self.root / RELATIVE).exists())
        blob = b"".join(path.read_bytes() for path in (private / "quarantine").rglob("*") if path.is_file())
        self.assertIn(b"STALE-QUEUE", blob)
        self.assertIn(b"PARTIAL", blob)
        self.assertNotIn(b"STALE-QUEUE", (self.root / RELATIVE).read_bytes() if (self.root / RELATIVE).exists() else b"")

    def test_14_sleep_resume_is_not_verified(self):
        contract = bridge_contract()
        self.assertEqual(contract["windows_sleep_resume"], "NOT_VERIFIED")
        self.assertEqual(contract["windows_owner_pc"], "NOT_VERIFIED")
        self.assertEqual(contract["powershell_memory_mapped_file"], "NOT_VERIFIED")
        session = self._start(fault=FAULT_STALL)
        from scripts.ms2_ps_python_bridge import _store
        _store(session._shm.buf, OFF_HEARTBEAT, 1)
        observed = session.observe_owner()
        self.assertEqual(observed["status"], "WORKER_STALLED")
        self.assertFalse((self.root / RELATIVE).exists())
        self.assertNotEqual(observed["status"], "CLOSED")

    def test_15_missing_clock_stays_absent(self):
        session = self._start()
        accepted = session.submit_capture(_board(
            available_at="2026-10-14T01:00:02.000+09:00",
            available_at_basis="DURABLE_CONSUMER_READ",
        ))
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertIsNone(row["event_time"])
        self.assertIsNone(row["available_at"])
        self.assertNotIn("JST", (self.root / RELATIVE).read_text(encoding="utf-8"))
        naive = session.submit_capture(_board(poll_seq=4, watcher_observed_at="2026-10-14T01:00:00"))
        self.assertEqual(naive["status"], "REFUSED")
        self.assertEqual(naive["reason"], "TIMEZONE_NOT_GUESSED")

    def test_16_stale_gap_and_time_conflict_stay_unclosed(self):
        session = self._start()
        gap = {
            "window_size": 300,
            "overlap_with_prev": 0,
            "prev_poll_nonempty": True,
            "new_appended": 20,
            "suspected_gap": True,
        }
        self.assertEqual(session.submit_capture(_board(gap=gap, data_freshness="STALE"))["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertEqual(row["data_freshness"], "STALE")
        self.assertTrue(row["suspected_gap"])
        self.assertEqual(row["sequence_basis"], "POLL")
        self.assertFalse(row["order_proven"])
        audited = audit_sidecar_bytes((self.root / RELATIVE).read_bytes())
        self.assertIn("FRESHNESS_STALE", audited["reasons"])
        self.assertIn("GAP_SUSPECTED", audited["reasons"])
        self.assertEqual(audited["close_state"], "NOT_CLOSED")
        self.assertNotEqual(audited["contract_status"], "CLOSED")
        conflict = session.submit_capture(_board(
            poll_seq=8,
            event_time="2026-10-14T01:00:01.000+09:00",
            event_time_basis="EXCHANGE_SUPPLIED",
            watcher_observed_at="2026-10-14T01:00:01.000+09:00",
        ))
        self.assertEqual(conflict["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["fail_closed"] == 1))
        self.assertEqual(len(self._rows()), 1)
        audited = audit_sidecar_bytes((self.root / RELATIVE).read_bytes())
        self.assertEqual(audited["close_state"], "NOT_CLOSED")

    def test_17_invalid_book_is_refused_and_missing_qty_stays_null(self):
        session = self._start()
        invalid = session.submit_capture(_board(levels=[_level(1, ask_qty="OVER")]))
        self.assertEqual(invalid["status"], "REFUSED")
        self.assertFalse((self.root / RELATIVE).exists())
        negative = session.submit_capture(_board(levels=[_level(1, ask_qty=-1)]))
        self.assertEqual(negative["reason"], "QTY_INVALID")
        accepted = session.submit_capture(_board())
        self.assertEqual(accepted["status"], "ACCEPTED")
        self.assertTrue(self._wait(lambda: session.metrics()["durable"] == 1))
        row = self._rows()[0]
        self.assertIsNone(row["levels"][0]["bid_qty"])
        self.assertIsNone(row["levels"][1]["ask_qty"])
        self.assertEqual(row["levels"][0]["ask_qty"], 0)

    def test_18_same_input_packs_the_same_bytes(self):
        first = pack_capture(_board())
        second = pack_capture(_board())
        self.assertEqual(first["record"], second["record"])
        self.assertEqual(len(first["record"]), 2048)
        changed = pack_capture(_board(poll_seq=4))
        self.assertNotEqual(first["record"], changed["record"])

    def test_19_no_extra_com_and_producer_has_no_launcher(self):
        surface = watcher_unchanged(ROOT)
        self.assertTrue(surface["matches_pinned"])
        self.assertEqual(surface["sha256"], WATCHER_SHA256)
        self.assertFalse(surface["modified"])
        audit = producer_audit(ROOT)
        self.assertEqual(audit["forbidden_hits"], [])
        self.assertFalse(audit["calls_python"])
        text = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8")
        self.assertEqual(text.count("Read-BoardDepth"), 2)
        self.assertEqual(hashlib.sha256((ROOT / "scripts" / "ms2_offline_observation_writer.py").read_bytes()).hexdigest(), WRITER_SHA)
        self.assertEqual(hashlib.sha256((ROOT / "scripts" / "ms2_watcher_sidecar_contract.py").read_bytes()).hexdigest(), CONTRACT_SHA)
        self.assertEqual(hashlib.sha256((ROOT / "paper_trade_history.json").read_bytes()).hexdigest(), HISTORY_SHA)
        self.assertEqual(bridge_contract()["extra_com_reads"], 0)
        producer = (ROOT / PRODUCER_RELATIVE).read_text(encoding="ascii")
        self.assertNotIn("Start-Sleep", producer)
        self.assertNotIn("while", producer)

    def test_20_price_voice_and_sign_source_are_unchanged(self):
        before = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_bytes()
        self.assertEqual(hashlib.sha256(before).hexdigest(), WATCHER_SHA256)
        contract = bridge_contract()
        self.assertEqual(contract["price_voice_sign_runtime"], "NOT_VERIFIED")
        self.assertEqual(contract["live_watcher_connection"], "P0_BLOCKED")
        self.assertEqual(contract["durable_writer_on_windows"], "OFFLINE_IMPLEMENTED")
        self.assertEqual(contract["durable_writer_via_handoff_worker"], "OFFLINE_IMPLEMENTED")
        self.assertIsNone(contract["durable_writer_blocker"])
        self.assertEqual(contract["durable_writer_owner_pc"], "NOT_VERIFIED")
        self.assertEqual(contract["power_loss_durability"], "NOT_VERIFIED")
        self.assertFalse(contract["producer_wired_to_watcher"])
        self.assertFalse(contract["watcher_modified"])
        self.assertFalse(contract["real_submit_allowed"])
        self.assertFalse(contract["promotion_eligible"])
        self.assertFalse(contract["statistical_edge_confirmed"])
        self.assertFalse(contract["autostart"])
        after = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_bytes()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
