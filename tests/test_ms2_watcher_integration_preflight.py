import errno
import fcntl
import hashlib
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.ms2_offline_observation_writer import watcher_integration_proposal
from scripts.ms2_watcher_integration_preflight import (
    ACCEPTED_PLACEMENT,
    AUDITED_CONTRACT_COMMIT,
    AUDITED_MAIN_SHA,
    AUDITED_WRITER_COMMIT,
    EXISTING_BOARD_COM_READS,
    PREFLIGHT_VERSION,
    REJECTED_PLACEMENT,
    WATCHER_RELATIVE,
    audit_bundle,
    hook_plan,
    main,
    measure_offline,
    new_session,
    run_poll,
    shutoff_budget_ms,
    trace_watcher_file,
    trace_watcher_text,
    windows_acceptance_protocol,
)
from tests.test_ms2_offline_observation_writer import PINNED_SHA256

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "data/private/ms2_sidecar/board.jsonl"
WRITER_SHA256 = "8efaa421a475286f1eab1bd3bf13900536530b554acdb60a6a08889bc77515c3"


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
        "source": "synthetic-fixture",
        "clock_source": "WINDOWS_LOCAL",
        "levels": [
            _level(1, "2026-10-14T01:00:00.010+09:00"),
            _level(2, "2026-10-14T01:00:00.050+09:00"),
        ],
        "watcher_observed_at": "2026-10-14T01:00:00.000+09:00",
    }
    payload.update(overrides)
    return payload


def _observed():
    return {"price": 100.5, "sign": "待機", "voice": "silent"}


def _synthetic():
    return {
        "symbol": "285A.T",
        "market": "TSE",
        "poll_seq": 4,
        "observation_id": "obs-1",
        "source": "synthetic-fixture",
        "clock_source": "WINDOWS_LOCAL",
        "sequence_basis": "EXCHANGE",
        "order_proven": True,
        "exchange_sequence": 9001,
        "event_time": "2026-10-14T01:00:00.000+09:00",
        "event_time_basis": "EXCHANGE_SUPPLIED",
        "watcher_observed_at": "2026-10-14T01:00:00.200+09:00",
        "available_at": "2026-10-14T01:00:00.500+09:00",
        "available_at_basis": "DURABLE_CONSUMER_READ",
        "data_freshness": "OK",
        "freshness_bound_ms": 1000,
        "read_method": "BULK_RANGE",
        "snapshot_atomic": True,
        "bulk_read_evidenced": True,
        "read_started_at": "2026-10-14T01:00:00.200+09:00",
        "read_finished_at": "2026-10-14T01:00:00.200+09:00",
        "levels": [_level(1, "2026-10-14T01:00:00.200+09:00", bid_qty=100, ask_qty=200)],
        "gap": {
            "window_size": 10,
            "overlap_with_prev": 3,
            "prev_poll_nonempty": True,
            "new_appended": 2,
        },
        "last_trade_price": 100.5,
        "last_trade_qty": 100,
        "tick_size": 0.5,
    }


class _Excel:
    def __init__(self):
        self.reads = 0
        self.errors = 0
        self.busy = True

    def value2(self):
        if self.busy:
            self.errors += 1
            raise RuntimeError("RPC_E_CALL_REJECTED")
        self.reads += 1
        return 1


class WatcherIntegrationPreflightTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.watcher_bytes = (ROOT / WATCHER_RELATIVE).read_bytes()

    def tearDown(self):
        self._tmp.cleanup()
        self.assertEqual((ROOT / WATCHER_RELATIVE).read_bytes(), self.watcher_bytes)

    def _poll(self, session, capture, **kwargs):
        params = {
            "placement": ACCEPTED_PLACEMENT,
            "enabled": True,
            "repo_root": self.root,
            "relative": RELATIVE,
            "capture": capture,
        }
        params.update(kwargs)
        return run_poll(session, _observed(), **params)

    def test_real_watcher_anchors_and_zero_extra_com(self):
        trace = trace_watcher_file(ROOT / WATCHER_RELATIVE)
        self.assertEqual(trace["status"], "OK")
        self.assertEqual(trace["reasons"], [])
        self.assertEqual(trace["read_board_depth_line"], 342)
        self.assertEqual(trace["value2_sites_in_reader"], 4)
        self.assertEqual(trace["cell_sites_in_reader"], 4)
        self.assertEqual(trace["loop_bound"], 10)
        self.assertTrue(trace["per_level_catch"])
        self.assertEqual(trace["board_com_reads_per_poll"], 40)
        self.assertEqual(trace["reader_call_lines"], [602])
        self.assertEqual(trace["board_variable_lines"], [602, 730])
        self.assertEqual(trace["assignment_line"], 602)
        self.assertEqual(trace["price_line"], 603)
        self.assertEqual(trace["sign_line"], 786)
        self.assertEqual(trace["json_line"], 864)
        self.assertEqual(trace["voice_line"], 871)
        self.assertEqual(trace["excel_save_line"], 888)
        self.assertEqual(trace["insert_after_line"], 897)
        self.assertEqual(trace["inner_catch_line"], 898)
        self.assertEqual(trace["poll_sleep_line"], 901)
        self.assertEqual(trace["poll_sleep_seconds"], 2)
        self.assertFalse(trace["snapshot_atomic"])
        self.assertFalse(trace["sidecar_writer_in_watcher"])
        self.assertEqual(trace["sha256"], PINNED_SHA256[WATCHER_RELATIVE])
        text = self.watcher_bytes.decode("utf-8")
        self.assertNotIn("record_captured_observation", text)
        self.assertNotIn("ms2_watcher_integration_preflight", text)

    def test_plan_is_unapplied_and_rejects_the_before_price_touch(self):
        trace = trace_watcher_file(ROOT / WATCHER_RELATIVE)
        plan = hook_plan(trace)
        proposal = watcher_integration_proposal()
        self.assertFalse(plan["applied"])
        self.assertFalse(plan["watcher_modified"])
        self.assertFalse(proposal["applied"])
        self.assertTrue(plan["isolation_shape_ok"])
        self.assertFalse(plan["default_enabled"])
        self.assertEqual(plan["com_reads_added"], 0)
        self.assertFalse(plan["calls_read_board_depth"])
        self.assertEqual(plan["budget_ms"], 50)
        self.assertEqual(shutoff_budget_ms(), 50)
        self.assertEqual(plan["retries_inside_poll"], 0)
        self.assertFalse(plan["blocking_lock"])
        self.assertTrue(plan["drop_on_overload"])
        self.assertFalse(plan["preemptive_timeout_available"])
        self.assertFalse(plan["background_thread"])
        self.assertEqual(plan["accepted_placement"], ACCEPTED_PLACEMENT)
        self.assertEqual(plan["insert_after_line"], 897)
        self.assertEqual(plan["insert_before_line"], 898)
        self.assertEqual(plan["rejected_placement"]["id"], REJECTED_PLACEMENT)
        self.assertEqual(plan["rejected_placement"]["isolation"], "FAIL")
        self.assertNotIn(".Value2", plan["sketch_not_applied"])
        self.assertNotIn("Read-BoardDepth", plan["sketch_not_applied"])
        self.assertEqual(plan["owner_approval"], "REQUIRED")
        self.assertFalse(plan["real_submit_allowed"])

    def test_malformed_watcher_text_fails_closed(self):
        empty = trace_watcher_text("")
        self.assertEqual(empty["status"], "BLOCKED")
        self.assertIn("WATCHER_SHAPE_UNKNOWN", empty["reasons"])
        self.assertFalse(hook_plan(empty)["isolation_shape_ok"])
        self.assertFalse(hook_plan(empty)["applied"])
        self.assertIsNone(hook_plan(empty)["accepted_placement"])

        original = self.watcher_bytes.decode("utf-8")
        doubled = original + "\n$board = @(Read-BoardDepth $rss)\n"
        extra_call = trace_watcher_text(doubled)
        self.assertEqual(extra_call["status"], "BLOCKED")
        self.assertIn("EXTRA_BOARD_READ", extra_call["reasons"])
        self.assertFalse(hook_plan(extra_call)["isolation_shape_ok"])

        changed = original.replace(
            "function Read-BoardDepth($sheet) {",
            "function Read-BoardDepth($sheet) {\n    $extra = $sheet.Cells.Item(1,1).Value2",
            1,
        )
        reshaped = trace_watcher_text(changed)
        self.assertEqual(reshaped["status"], "BLOCKED")
        self.assertIn("BOARD_READ_SHAPE_CHANGED", reshaped["reasons"])
        self.assertNotEqual(reshaped["board_com_reads_per_poll"], 40)

    def test_before_price_placement_delays_price_and_after_voice_does_not(self):
        def slow(repo_root, relative, capture, *, enabled=False, hooks=None):
            time.sleep(0.08)
            return {
                "writer_status": "ADMITTED_INCOMPLETE",
                "transition": "APPENDED",
                "reasons": ["SLOW"],
                "elapsed_ms": 0,
                "close_state": "NOT_CLOSED",
            }

        before = self._poll(new_session(), _board(), placement=REJECTED_PLACEMENT, writer=slow)
        after = self._poll(new_session(), _board(), placement=ACCEPTED_PLACEMENT, writer=slow)
        self.assertEqual(before["phases"], ["sidecar", "price", "sign", "voice", "sleep"])
        self.assertEqual(after["phases"], ["price", "sign", "voice", "sidecar", "sleep"])
        self.assertGreaterEqual(before["critical_delay_ms"], 70)
        self.assertEqual(after["critical_delay_ms"], 0)
        self.assertGreaterEqual(after["cycle_stretch_ms"], 70)
        self.assertEqual(before["verdict"], "FAIL_PLACEMENT")
        self.assertEqual(after["verdict"], "PASS_CRITICAL_CADENCE_STRETCHED")
        self.assertEqual(before["sleep_seconds"], 2)
        self.assertEqual(after["sleep_seconds"], 2)
        self.assertTrue(before["sleep_invoked"])
        self.assertTrue(after["sleep_invoked"])
        self.assertTrue(before["critical_unchanged"])
        self.assertTrue(after["critical_unchanged"])
        self.assertTrue(before["killed"])
        self.assertTrue(after["killed"])
        self.assertEqual(after["critical"]["price"], 100.5)
        self.assertEqual(after["critical"]["sign"], "待機")
        self.assertEqual(after["critical"]["voice"], "silent")

    def test_mutation_and_raised_writer_cannot_replace_the_later_critical_path(self):
        observed_box = _observed()

        def evil(repo_root, relative, capture, *, enabled=False, hooks=None):
            observed_box["price"] = "MUTATED"
            observed_box["sign"] = "MUTATED"
            observed_box["voice"] = "MUTATED"
            return {
                "writer_status": "ADMITTED_INCOMPLETE",
                "transition": "APPENDED",
                "reasons": ["MUTATE"],
                "elapsed_ms": 1,
                "real_submit_allowed": True,
                "close_state": "CLOSED",
            }

        def boom(repo_root, relative, capture, *, enabled=False, hooks=None):
            raise RuntimeError("storage failed")

        before = run_poll(
            new_session(), observed_box, placement=REJECTED_PLACEMENT, enabled=True,
            repo_root=self.root, relative=RELATIVE, capture=_board(), writer=evil,
        )
        self.assertEqual(before["verdict"], "FAIL_CRITICAL_PATH")
        self.assertEqual(before["critical"]["price"], "MUTATED")
        self.assertFalse(before["hook"]["real_submit_allowed"])
        self.assertFalse(before["hook"]["closed_eligible"])
        self.assertEqual(before["hook"]["close_state"], "NOT_CLOSED")
        self.assertIn("CLOSE_CLAIM_REFUSED", before["hook"]["reasons"])
        self.assertEqual(before["eligible_observed_n"], 0)

        after = run_poll(
            new_session(), _observed(), placement=ACCEPTED_PLACEMENT, enabled=True,
            repo_root=self.root, relative=RELATIVE, capture=_board(), writer=evil,
        )
        self.assertEqual(after["critical"], {"price": 100.5, "sign": "待機", "voice": "silent"})
        self.assertFalse(after["hook"]["real_submit_allowed"])
        self.assertEqual(after["verdict"], "PASS_CRITICAL")

        raised = self._poll(new_session(), _board(), writer=boom)
        self.assertIn("WRITER_EXCEPTION", raised["hook"]["reasons"])
        self.assertEqual(raised["session_state"], "LATCHED")
        self.assertTrue(raised["critical_unchanged"])
        self.assertTrue(raised["sleep_invoked"])
        self.assertEqual(raised["sleep_seconds"], 2)
        self.assertEqual(raised["verdict"], "PASS_CRITICAL")
        self.assertEqual(raised["hook_com_reads"], 0)

    def test_disk_permission_lock_and_corrupt_keep_price_sign_voice_and_sleep(self):
        def deny_open(*_args, **_kwargs):
            raise PermissionError(errno.EACCES, "denied")

        def lock_busy(fd, op):
            if op & fcntl.LOCK_EX:
                raise BlockingIOError()
            return fcntl.flock(fd, op)

        def write_full(fd, data):
            raise OSError(errno.ENOSPC, "full")

        faults = [
            ("disk", {"write": write_full}, "DISK_FULL"),
            ("permission", {"open": deny_open}, "WRITE_FAILED"),
            ("lock", {"flock": lock_busy}, "WRITE_LOCKED"),
        ]
        for index, (name, hooks, code) in enumerate(faults):
            session = new_session()
            result = self._poll(session, _board(poll_seq=20 + index), hooks=hooks)
            self.assertIn(code, result["hook"]["reasons"], name)
            self.assertEqual(result["critical"], {"price": 100.5, "sign": "待機", "voice": "silent"}, name)
            self.assertEqual(result["phases"][:3], ["price", "sign", "voice"], name)
            self.assertEqual(result["phases"][-1], "sleep", name)
            self.assertEqual(result["sleep_seconds"], 2, name)
            self.assertEqual(result["session_state"], "LATCHED", name)
            self.assertEqual(result["hook_com_reads"], 0, name)
            self.assertEqual(result["modeled_existing_board_reads"], EXISTING_BOARD_COM_READS, name)
            self.assertFalse(result["hook"]["real_submit_allowed"], name)
            follow = self._poll(session, _board(poll_seq=99), hooks=hooks)
            self.assertEqual(follow["session_state"], "DROPPED", name)
            self.assertEqual(follow["writer_calls"], 1, name)
            self.assertTrue(follow["critical_unchanged"], name)
            self.assertEqual(follow["sleep_seconds"], 2, name)

        path = self.root / RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        original = b"{not-json\n"
        path.write_bytes(original)
        session = new_session()
        corrupt = self._poll(session, _board())
        self.assertIn("DATA_CORRUPT", corrupt["hook"]["reasons"])
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(corrupt["critical_unchanged"])
        self.assertEqual(corrupt["session_state"], "LATCHED")
        again = self._poll(session, _board(poll_seq=8))
        self.assertEqual(again["session_state"], "DROPPED")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(again["critical"]["sign"], "待機")

    def test_disk_full_reason_codes_are_deterministic(self):
        def write_full(fd, data):
            raise OSError(errno.ENOSPC, "full")

        def slim(result):
            return {
                "phases": result["phases"],
                "reasons": result["hook"]["reasons"],
                "writer_status": result["hook"]["writer_status"],
                "transition": result["hook"]["transition"],
                "critical": result["critical"],
                "sleep_seconds": result["sleep_seconds"],
                "hook_com_reads": result["hook_com_reads"],
                "killed": result["killed"],
                "verdict": result["verdict"],
                "real_submit_allowed": result["real_submit_allowed"],
            }

        first = self._poll(new_session(), _board(), hooks={"write": write_full})
        second = self._poll(new_session(), _board(), hooks={"write": write_full})
        self.assertIn("DISK_FULL", first["hook"]["reasons"])
        self.assertEqual(slim(first), slim(second))

    def test_missing_and_naive_clocks_are_not_fabricated(self):
        missing = self._poll(new_session(), {
            "symbol": "285A.T",
            "market": "TSE",
            "poll_seq": 1,
            "source": "synthetic-fixture",
            "levels": [_level(1)],
        })
        self.assertTrue(missing["critical_unchanged"])
        self.assertEqual(missing["sleep_seconds"], 2)
        self.assertEqual(missing["eligible_observed_n"], 0)
        path = self.root / RELATIVE
        if path.exists():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("+09:00", text)
            self.assertNotIn("Asia/Tokyo", text)
            row = json.loads(text.splitlines()[0])
            self.assertIsNone(row["event_time"])
            self.assertIsNone(row["available_at"])
            self.assertIsNone(row["exchange_sequence"])
            self.assertFalse(row["snapshot_atomic"])
            self.assertEqual(row["poll_seq"], 1)
            self.assertEqual(row["poll_seq_basis"], "WATCHER_LOOP")
            self.assertNotEqual(row["close_state"] if "close_state" in row else "NOT_CLOSED", "CLOSED")
        else:
            self.assertEqual(missing["hook"]["writer_status"], "BLOCKED")

        naive_root = self.root / "naive"
        naive = run_poll(
            new_session(), _observed(), placement=ACCEPTED_PLACEMENT, enabled=True,
            repo_root=naive_root, relative=RELATIVE,
            capture=_board(watcher_observed_at="2026-10-14 01:00:00"),
        )
        self.assertIn("TIMEZONE_UNKNOWN", naive["hook"]["reasons"])
        self.assertEqual(naive["hook"]["close_state"], "NOT_CLOSED")
        self.assertFalse((naive_root / RELATIVE).exists())
        self.assertTrue(naive["critical_unchanged"])
        self.assertTrue(naive["killed"])
        self.assertFalse(naive["real_submit_allowed"])

    def test_com_reader_is_refused_while_excel_stays_busy(self):
        excel = _Excel()
        with self.assertRaises(RuntimeError):
            excel.value2()
        self.assertEqual(excel.errors, 1)
        excel.errors = 0
        session = new_session()
        result = self._poll(session, _board(), excel_reader=excel.value2)
        self.assertEqual(excel.reads, 0)
        self.assertEqual(excel.errors, 0)
        self.assertIn("COM_READ_REFUSED", result["hook"]["reasons"])
        self.assertEqual(result["hook_com_reads"], 0)
        self.assertEqual(result["modeled_existing_board_reads"], 40)
        self.assertTrue(result["critical_unchanged"])
        self.assertEqual(result["session_state"], "LATCHED")
        self.assertEqual(result["writer_calls"], 0)
        self.assertEqual(result["sleep_seconds"], 2)
        follow = self._poll(session, _board(poll_seq=5))
        self.assertEqual(follow["session_state"], "DROPPED")
        self.assertEqual(follow["writer_calls"], 0)
        self.assertEqual(excel.reads, 0)
        self.assertEqual(follow["critical"]["voice"], "silent")

    def test_disabled_default_writes_nothing_and_over_budget_drops_the_next_poll(self):
        session = new_session()
        disabled = self._poll(session, _board(), enabled=False)
        self.assertEqual(disabled["hook"]["writer_status"], "DISABLED")
        self.assertIn("SIDECAR_DISABLED", disabled["hook"]["reasons"])
        self.assertFalse(disabled["killed"])
        self.assertEqual(disabled["writer_calls"], 0)
        self.assertFalse((self.root / "data" / "private").exists())
        self.assertEqual(disabled["critical"]["sign"], "待機")
        self.assertEqual(disabled["verdict"], "PASS_CRITICAL")

        def slow(repo_root, relative, capture, *, enabled=False, hooks=None):
            return {
                "writer_status": "ADMITTED_INCOMPLETE",
                "transition": "APPENDED",
                "reasons": ["SLOW"],
                "elapsed_ms": 80,
                "close_state": "NOT_CLOSED",
            }

        armed = new_session()
        first = self._poll(armed, _board(), writer=slow)
        self.assertEqual(first["session_state"], "LATCHED")
        self.assertEqual(first["verdict"], "PASS_CRITICAL_CADENCE_STRETCHED")
        self.assertEqual(first["critical_delay_ms"], 0)
        second = self._poll(armed, _board(poll_seq=6), writer=slow)
        self.assertEqual(second["session_state"], "DROPPED")
        self.assertEqual(second["writer_calls"], 1)
        self.assertEqual(second["cycle_stretch_ms"], 0)
        self.assertEqual(second["verdict"], "PASS_CRITICAL")
        self.assertEqual(second["critical"]["price"], 100.5)

    def test_synthetic_record_stays_not_closed_on_the_critical_path(self):
        result = self._poll(new_session(), _synthetic())
        self.assertEqual(result["hook"]["close_state"], "NOT_CLOSED")
        self.assertEqual(result["hook"]["eligible_observed_n"], 0)
        self.assertNotEqual(result["hook"].get("pit_evidence_origin"), "RECORDED")
        self.assertFalse(result["hook"]["real_submit_allowed"])
        self.assertFalse(result["hook"]["promotion_eligible"])
        self.assertFalse(result["hook"]["statistical_edge_confirmed"])
        self.assertTrue(result["critical_unchanged"])
        self.assertEqual(result["sleep_seconds"], 2)
        if result["hook"]["writer_status"] != "BLOCKED":
            row = json.loads((self.root / RELATIVE).read_text(encoding="utf-8").splitlines()[0])
            self.assertNotEqual(row.get("evidence_origin"), "RECORDED")

    def test_offline_timing_is_labeled_and_windows_protocol_is_unverified(self):
        sample = measure_offline(self.root, RELATIVE, _board(poll_seq=1), polls=20, enabled=True)
        self.assertEqual(sample["label"], "OFFLINE_NOT_WINDOWS")
        self.assertEqual(sample["windows_performance"], "NOT_VERIFIED")
        self.assertFalse(sample["preemptive_timeout_available"])
        self.assertEqual(sample["polls"], 20)
        self.assertEqual(sample["budget_ms"], 50)
        self.assertGreaterEqual(sample["max_ms"], sample["median_ms"])
        self.assertEqual(sample["eligible_observed_n"], 0)
        quiet_root = self.root / "quiet"
        quiet = measure_offline(quiet_root, RELATIVE, _board(), polls=20, enabled=False)
        self.assertLessEqual(quiet["median_ms"], 20)
        self.assertFalse((quiet_root / "data" / "private").exists())

        protocol = windows_acceptance_protocol()
        self.assertEqual([item["id"] for item in protocol], ["W1", "W2", "W3", "W4"])
        self.assertEqual([item["theme"] for item in protocol], ["startup", "com_contention", "storage_fault", "graceful_stop"])
        for item in protocol:
            self.assertEqual(item["status"], "NOT_VERIFIED")
            self.assertFalse(item["this_pr_runs_it"])
            self.assertIn("市場が閉まっている", item["when"])
            self.assertTrue(item["steps"])
            self.assertTrue(item["pass"])
            self.assertTrue(item["abort"])
            self.assertTrue(item["recovery"])
        joined = json.dumps(protocol, ensure_ascii=False)
        self.assertIn("Ctrl+C", joined)
        self.assertIn("Stop-Process", joined)
        self.assertIn("気配値ログ", joined)
        self.assertIn(AUDITED_MAIN_SHA, joined)

    def test_compatibility_hashes_history_and_cli_do_not_write(self):
        bundle = audit_bundle(ROOT)
        pinned = bundle["compatibility"]["pinned_sha256"]
        for relative, digest in PINNED_SHA256.items():
            self.assertEqual(pinned[relative], digest, relative)
        self.assertEqual(pinned["scripts/ms2_offline_observation_writer.py"], WRITER_SHA256)
        self.assertEqual(bundle["compatibility"]["history_rows"], 263)
        self.assertEqual(bundle["compatibility"]["pr_347_schema"], "ms2-watcher-sidecar-0.1")
        self.assertEqual(bundle["compatibility"]["pr_349_writer_commit"], AUDITED_WRITER_COMMIT)
        self.assertEqual(bundle["compatibility"]["pr_347_contract_commit"], AUDITED_CONTRACT_COMMIT)
        self.assertEqual(bundle["compatibility"]["pr_345_pit_schema"], "ms2-pit-observation-0.1")
        self.assertFalse(bundle["compatibility"]["pr_343_evaluator_imported"])
        self.assertFalse(bundle["compatibility"]["pr_345_ingress_imported"])
        self.assertFalse(bundle["compatibility"]["forwards_recorded_evidence"])
        self.assertFalse(bundle["compatibility"]["emits_virtual_close"])
        self.assertFalse(bundle["compatibility"]["proposal_applied"])
        self.assertEqual(bundle["safety"]["audited_main_sha"], AUDITED_MAIN_SHA)
        self.assertEqual(bundle["safety"]["preflight_version"], PREFLIGHT_VERSION)
        self.assertIsNone(bundle["safety"]["expectancy_yen"])
        self.assertIsNone(bundle["safety"]["remaining_to_10b_yen"])
        history = json.loads((ROOT / "paper_trade_history.json").read_text(encoding="utf-8"))
        self.assertEqual(len(history), 263)

        module = (ROOT / "scripts/ms2_watcher_integration_preflight.py").read_text(encoding="utf-8")
        self.assertNotIn("evaluate_virtual_fill", module)
        self.assertNotIn("ms2_observation_ingress", module)
        self.assertNotIn("subprocess", module)
        self.assertNotIn("win32com", module)

        before = (ROOT / WATCHER_RELATIVE).read_bytes()
        private = ROOT / "data" / "private" / "ms2_sidecar"
        existed = private.exists()
        stdout = StringIO()
        with redirect_stdout(stdout):
            code = main(["--repo-root", str(ROOT)])
        self.assertEqual(code, 0)
        self.assertEqual((ROOT / WATCHER_RELATIVE).read_bytes(), before)
        self.assertEqual(private.exists(), existed)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["trace"]["status"], "OK")
        self.assertFalse(payload["plan"]["applied"])
        self.assertNotIn("levels", payload)


if __name__ == "__main__":
    unittest.main()
