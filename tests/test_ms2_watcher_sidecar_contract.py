import hashlib
import io
import json
import subprocess
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.execution_contract import _HASH_FIELDS
from scripts.ms2_watcher_sidecar_contract import (
    CURRENT_WATCHER_SOURCE,
    SCHEMA_VERSION,
    SIDECAR_WRITER_DEFAULT_ENABLED,
    audit_private_sidecar,
    audit_sidecar_bytes,
    future_watcher_edit_plan,
    join_poll_references,
    main,
    producer_audit,
    redact_report,
    windows_acceptance_checklist,
)

ROOT = Path(__file__).resolve().parents[1]
WATCHER = ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1"
HISTORY = ROOT / "paper_trade_history.json"
TZ = "+09:00"
REPORT_REASONS = {
    "COST_ABSENT",
    "CAPTURE_NOT_AUTHENTICATED",
    "FILL_EVALUATOR_NOT_COUPLED",
    "ECONOMICS_UNKNOWN",
    "ELIGIBLE_OBSERVED_N_ZERO",
}


def _dump(records) -> bytes:
    return ("\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n").encode("utf-8")


def _level(number, read_at, *, bid=100, ask=101, bid_qty=100, ask_qty=200, bid_known=True, ask_known=True):
    return {
        "level": number,
        "bid": bid,
        "ask": ask,
        "bid_qty": bid_qty,
        "ask_qty": ask_qty,
        "bid_qty_known": bid_known,
        "ask_qty_known": ask_known,
        "read_at": read_at,
    }


def _top(**kwargs):
    base = {"bid": 100, "ask": 101, "bid_qty": 100, "ask_qty": 200, "bid_qty_known": True, "ask_qty_known": True}
    base.update(kwargs)
    return base


def _gap_diag(poll_seq, *, overlap=3, window=10, prev=True, new=2):
    return {
        "poll_seq": poll_seq,
        "window_size": window,
        "overlap_with_prev": overlap,
        "prev_poll_nonempty": prev,
        "new_appended": new,
    }


def _shared(**overrides):
    record = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": "obs-1",
        "source": "synthetic-fixture",
        "symbol": "285A.T",
        "market": "TSE",
        "kind": "BOARD_SNAPSHOT",
        "poll_seq": 4,
        "poll_seq_basis": "WATCHER_LOOP",
        "sequence_basis": "EXCHANGE",
        "order_proven": True,
        "exchange_sequence": 9001,
        "event_time": "2026-10-14T01:00:00.000+09:00",
        "event_time_basis": "EXCHANGE_SUPPLIED",
        "watcher_observed_at": "2026-10-14T01:00:00.200+09:00",
        "watcher_observed_at_basis": "GET_DATE_LOCAL",
        "clock_source": "WINDOWS_LOCAL",
        "clock_quality": "UNSYNCHRONIZED_LOCAL",
        "timezone": TZ,
        "received_at": None,
        "received_at_basis": "NOT_SEPARATELY_EVIDENCED",
        "available_at": "2026-10-14T01:00:00.500+09:00",
        "available_at_basis": "DURABLE_CONSUMER_READ",
        "suspected_gap": False,
        "gap_evidence": "ATTACHED",
        "data_freshness": "OK",
        "freshness_basis": "EXCHANGE_AGE_WITHIN_BOUND",
        "quote_age_ms": 200,
        "freshness_bound_ms": 1000,
        "capture_authenticated": False,
        "poll_window_ms": None,
    }
    record.update(overrides)
    return record


def _board(**overrides):
    record = _shared()
    record.update({
        "snapshot_atomic": True,
        "read_method": "BULK_RANGE",
        "read_started_at": "2026-10-14T01:00:00.200+09:00",
        "read_finished_at": "2026-10-14T01:00:00.200+09:00",
        "read_skew_ms": 0,
        "gap_diag": _gap_diag(record["poll_seq"]),
        "book_qty_source": "RSS_LEVEL_QTY",
        "top": _top(),
        "levels": [_level(1, "2026-10-14T01:00:00.200+09:00")],
        "depth_claimed": 1,
        "over_qty": None,
        "under_qty": None,
        "last_trade_price": 100.5,
        "last_trade_qty": 100,
        "last_trade_known": True,
        "tick_size": 0.5,
        "tick_size_known": True,
    })
    record.update(overrides)
    if "poll_seq" in overrides and "gap_diag" not in overrides and record.get("gap_evidence") == "ATTACHED":
        record["gap_diag"] = _gap_diag(record["poll_seq"])
    return record


def _incomplete(**overrides):
    record = _board(
        observation_id="board-incomplete-1",
        poll_seq=3,
        sequence_basis="POLL",
        order_proven=False,
        exchange_sequence=None,
        event_time=None,
        event_time_basis="ABSENT",
        watcher_observed_at="2026-10-14T01:00:00.000+09:00",
        available_at=None,
        available_at_basis="NOT_DEMONSTRATED",
        snapshot_atomic=False,
        read_method="SEQUENTIAL_CELL",
        read_started_at="2026-10-14T01:00:00.010+09:00",
        read_finished_at="2026-10-14T01:00:00.050+09:00",
        read_skew_ms=40,
        suspected_gap=None,
        gap_evidence="NOT_ATTACHED",
        gap_diag=None,
        data_freshness="UNKNOWN",
        freshness_basis="NOT_EVIDENCED",
        quote_age_ms=None,
        freshness_bound_ms=None,
        book_qty_source="UNKNOWN",
        top=_top(bid_qty=None, ask_qty=None, bid_qty_known=False, ask_qty_known=False),
        levels=[
            _level(1, "2026-10-14T01:00:00.010+09:00", bid_qty=None, ask_qty=None, bid_known=False, ask_known=False),
            _level(2, "2026-10-14T01:00:00.050+09:00", bid_qty=None, ask_qty=None, bid_known=False, ask_known=False),
        ],
        depth_claimed=2,
        last_trade_price=None,
        last_trade_qty=None,
        last_trade_known=False,
        tick_size=None,
        tick_size_known=False,
    )
    record.update(overrides)
    return record


def _tick(**overrides):
    record = _shared(kind="TICK_PRINT", observation_id="tick-1")
    record.update({
        "snapshot_atomic": None,
        "read_method": "NOT_APPLICABLE",
        "read_started_at": None,
        "read_finished_at": None,
        "read_skew_ms": None,
        "gap_diag": _gap_diag(record["poll_seq"]),
        "price": 100.5,
        "volume": 100,
    })
    record.update(overrides)
    return record


def _diag(**overrides):
    record = _shared(kind="GAP_DIAG", observation_id="gap-1", sequence_basis="POLL", order_proven=False, exchange_sequence=None)
    record.update({
        "event_time": None,
        "event_time_basis": "ABSENT",
        "available_at": None,
        "available_at_basis": "NOT_DEMONSTRATED",
        "data_freshness": "UNKNOWN",
        "freshness_basis": "NOT_EVIDENCED",
        "quote_age_ms": None,
        "freshness_bound_ms": None,
        "read_method": "NOT_APPLICABLE",
        "window_size": 10,
        "overlap_with_prev": 3,
        "prev_poll_nonempty": True,
        "new_appended": 2,
        "suspected_gap": False,
        "gap_evidence": "ATTACHED",
    })
    record.update(overrides)
    return record


class SidecarContractTests(unittest.TestCase):
    def test_writer_defaults_off_and_plan_is_not_applied(self):
        self.assertFalse(SIDECAR_WRITER_DEFAULT_ENABLED)
        plan = future_watcher_edit_plan()
        self.assertFalse(plan["applied"])
        self.assertFalse(plan["default_enabled"])
        self.assertIn("Read-BoardDepth", " ".join(plan["touch_points"]))
        self.assertTrue(any("Ctrl+C" in step for step in plan["rollback"]))
        audit = producer_audit()
        self.assertFalse(audit["sidecar_writer_present"])
        self.assertFalse(audit["atomic_snapshot"])
        self.assertFalse(audit["ten_level_qty_persisted_in_csv"])
        self.assertFalse(audit["available_at_persisted"])
        self.assertEqual(audit["poll_sleep_seconds"], 2)
        checklist = windows_acceptance_checklist()
        self.assertTrue(checklist)
        self.assertTrue(all(item["status"] == "NOT_VERIFIED" for item in checklist))

    def test_disabled_path_reads_nothing(self):
        report = audit_private_sidecar(ROOT, None)
        self.assertEqual(report["contract_status"], "NOT_READ")
        self.assertEqual(report["decision_state"], "DISABLED")
        self.assertIn("SIDECAR_DISABLED", report["reasons"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertEqual(report["bytes_read"], 0)
        self.assertFalse(report["real_submit_allowed"])
        self.assertFalse(report["writes_performed"])

    def test_cli_default_is_redacted_and_disabled(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main([])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["contract_status"], "NOT_READ")
        self.assertNotIn("pit_records", payload)

    def test_honest_sequential_board_is_admitted_and_not_forwarded(self):
        report = audit_sidecar_bytes(_dump([_incomplete()]))
        self.assertEqual(report["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(report["decision_state"], "BLOCKED")
        self.assertEqual(report["close_state"], "NOT_CLOSED")
        self.assertEqual(report["pit_records"], [])
        self.assertEqual(report["synthetic_n"], 0)
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertFalse(report["closed_eligible"])
        self.assertEqual(set(report["reasons"]), REPORT_REASONS | {
            "EVENT_TIME_ABSENT",
            "AVAILABLE_AT_ABSENT",
            "EXCHANGE_SEQUENCE_ABSENT",
            "POLL_ORDER_NOT_EXCHANGE_ORDER",
            "FRESHNESS_UNKNOWN",
            "SUSPECTED_GAP_UNKNOWN",
            "SNAPSHOT_NOT_ATOMIC",
            "BOOK_QTY_UNKNOWN",
            "TRADE_PRINT_ABSENT",
            "TICK_SIZE_UNKNOWN",
        })

    def test_complete_synthetic_quote_projects_and_stays_unclosed(self):
        report = audit_sidecar_bytes(_dump([_board()]))
        self.assertEqual(report["contract_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(report["decision_state"], "BLOCKED")
        self.assertEqual(report["pit_evidence_origin"], "SYNTHETIC")
        self.assertFalse(report["recorded_forward_allowed"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertEqual(report["synthetic_n"], 1)
        self.assertFalse(report["closed_eligible"])
        self.assertIsNone(report["expectancy_yen"])
        self.assertIsNone(report["profit_factor"])
        self.assertIsNone(report["max_drawdown_yen"])
        self.assertIsNone(report["verified_net_pnl_yen"])
        self.assertIsNone(report["remaining_to_10b_yen"])
        pit = report["pit_records"][0]
        self.assertEqual(pit["schema_version"], "ms2-pit-observation-0.1")
        self.assertEqual(pit["kind"], "QUOTE")
        self.assertEqual(pit["sequence_basis"], "EXCHANGE")
        self.assertTrue(pit["order_proven"])
        self.assertNotEqual(pit["sequence"], pit["poll_seq"])
        self.assertEqual(pit["suspected_gap"], False)
        self.assertEqual(pit["data_freshness"], "OK")
        self.assertEqual(set(report["reasons"]), REPORT_REASONS)

    def test_same_bytes_are_deterministic(self):
        raw = _dump([_board()])
        self.assertEqual(audit_sidecar_bytes(raw), audit_sidecar_bytes(raw))

    def test_key_order_does_not_change_the_decision(self):
        first = _board()
        second = {key: first[key] for key in reversed(list(first))}
        left = audit_sidecar_bytes((json.dumps(first, ensure_ascii=False) + "\n").encode("utf-8"))
        right = audit_sidecar_bytes((json.dumps(second, ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertEqual(left["contract_status"], right["contract_status"])
        self.assertEqual(left["reasons"], right["reasons"])
        self.assertEqual(left["pit_records"], right["pit_records"])
        self.assertNotEqual(left["input_sha256"], right["input_sha256"])

    def test_equal_clocks_and_asserted_availability_are_rejected(self):
        same = "2026-10-14T01:00:00.200+09:00"
        report = audit_sidecar_bytes(_dump([_board(
            event_time=same,
            watcher_observed_at=same,
            available_at=same,
            read_started_at=same,
            read_finished_at=same,
            quote_age_ms=0,
        )]))
        self.assertEqual(report["contract_status"], "BLOCKED")
        self.assertIn("CLOCKS_NOT_DISTINGUISHED", report["reasons"])
        self.assertIn("AVAILABLE_AT_ASSERTED_EQUAL", report["reasons"])
        self.assertEqual(report["pit_records"], [])

    def test_naive_named_and_mismatched_timezones_fail_closed(self):
        naive = audit_sidecar_bytes(_dump([_board(event_time="2026-10-14T01:00:00")]))
        self.assertIn("TIMEZONE_UNKNOWN", naive["reasons"])
        named = audit_sidecar_bytes(_dump([_board(event_time="2026-10-14T01:00:00.000+09:00 JST")]))
        self.assertIn("TIMEZONE_UNKNOWN", named["reasons"])
        tokyo = audit_sidecar_bytes(_dump([_board(timezone="Asia/Tokyo")]))
        self.assertIn("TIMEZONE_UNKNOWN", tokyo["reasons"])
        shifted = audit_sidecar_bytes(_dump([_board(timezone="+10:00")]))
        self.assertIn("TIMEZONE_MISMATCH", shifted["reasons"])
        for report in (naive, named, tokyo, shifted):
            self.assertEqual(report["contract_status"], "BLOCKED")
            self.assertEqual(report["admitted_count"], 0)

    def test_submillisecond_and_future_exchange_time_are_rejected(self):
        fine = audit_sidecar_bytes(_dump([_board(watcher_observed_at="2026-10-14T01:00:00.200100+09:00")]))
        self.assertIn("SUBMILLISECOND_UNRECORDED", fine["reasons"])
        future = audit_sidecar_bytes(_dump([_board(
            event_time="2026-10-14T01:00:00.900+09:00",
            quote_age_ms=0,
        )]))
        self.assertEqual(future["contract_status"], "BLOCKED")
        self.assertTrue(
            "TIME_ORDER_CONTRADICTION" in future["reasons"] or "CLOCKS_NOT_DISTINGUISHED" in future["reasons"]
        )

    def test_day_boundary_keeps_exchange_time_before_availability(self):
        report = audit_sidecar_bytes(_dump([_board(
            event_time="2026-10-14T23:59:59.000+09:00",
            watcher_observed_at="2026-10-15T00:00:00.100+09:00",
            read_started_at="2026-10-15T00:00:00.100+09:00",
            read_finished_at="2026-10-15T00:00:00.100+09:00",
            available_at="2026-10-15T00:00:00.400+09:00",
            levels=[_level(1, "2026-10-15T00:00:00.100+09:00")],
            quote_age_ms=1100,
            freshness_bound_ms=2000,
        )]))
        self.assertEqual(report["contract_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(report["eligible_observed_n"], 0)

    def test_poll_sequence_cannot_pose_as_exchange_sequence(self):
        reused = audit_sidecar_bytes(_dump([_board(exchange_sequence=4)]))
        self.assertIn("POLL_SEQ_REUSED_AS_EXCHANGE_SEQUENCE", reused["reasons"])
        claimed = audit_sidecar_bytes(_dump([_board(sequence_basis="POLL", order_proven=True, exchange_sequence=None)]))
        self.assertIn("POLL_ORDER_NOT_EXCHANGE_ORDER", claimed["reasons"])
        self.assertEqual(reused["contract_status"], "BLOCKED")
        self.assertEqual(claimed["contract_status"], "BLOCKED")

    def test_stale_gap_and_unknown_quantity_do_not_project(self):
        stale = audit_sidecar_bytes(_dump([_board(
            data_freshness="STALE", freshness_basis="STALE_DECLARED", quote_age_ms=None, freshness_bound_ms=None,
        )]))
        self.assertEqual(stale["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertIn("FRESHNESS_STALE", stale["reasons"])
        gap = audit_sidecar_bytes(_dump([_board(
            suspected_gap=True,
            gap_diag=_gap_diag(4, overlap=0, new=0),
        )]))
        self.assertIn("GAP_SUSPECTED", gap["reasons"])
        self.assertEqual(gap["pit_records"], [])
        unknown = audit_sidecar_bytes(_dump([_board(
            book_qty_source="UNKNOWN",
            top=_top(bid_qty=None, ask_qty=None, bid_qty_known=False, ask_qty_known=False),
            levels=[_level(1, "2026-10-14T01:00:00.200+09:00", bid_qty=None, ask_qty=None, bid_known=False, ask_known=False)],
        )]))
        self.assertIn("BOOK_QTY_UNKNOWN", unknown["reasons"])
        self.assertEqual(unknown["synthetic_n"], 0)

    def test_gap_flag_contradiction_and_over_under_quantity_are_rejected(self):
        contradicted = audit_sidecar_bytes(_dump([_board(
            suspected_gap=False,
            gap_diag=_gap_diag(4, overlap=0, new=0),
        )]))
        self.assertEqual(contradicted["contract_status"], "BLOCKED")
        self.assertIn("GAP_FLAG_CONTRADICTION", contradicted["reasons"])
        laundered = audit_sidecar_bytes(_dump([_board(book_qty_source="OVER_UNDER", under_qty=200, over_qty=100)]))
        self.assertIn("BOOK_QTY_NOT_TOP_OF_BOOK", laundered["reasons"])
        self.assertEqual(laundered["admitted_count"], 0)

    def test_claiming_an_atomic_sequential_read_is_rejected(self):
        report = audit_sidecar_bytes(_dump([_board(
            snapshot_atomic=True,
            read_method="SEQUENTIAL_CELL",
            read_started_at="2026-10-14T01:00:00.200+09:00",
            read_finished_at="2026-10-14T01:00:00.240+09:00",
            read_skew_ms=40,
        )]))
        self.assertEqual(report["contract_status"], "BLOCKED")
        self.assertIn("SNAPSHOT_ATOMIC_CONTRADICTION", report["reasons"])

    def test_ten_levels_with_one_unknown_size_stay_incomplete(self):
        read_at = "2026-10-14T01:00:00.200+09:00"
        levels = [_level(index, read_at) for index in range(1, 11)]
        levels[6] = _level(7, read_at, bid_qty=None, ask_qty=None, bid_known=False, ask_known=False)
        report = audit_sidecar_bytes(_dump([_board(depth_claimed=10, levels=levels, snapshot_atomic=True)]))
        self.assertEqual(report["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertIn("BOOK_QTY_UNKNOWN", report["reasons"])
        self.assertEqual(report["pit_records"], [])

    def test_duplicate_conflict_blocks_and_identical_lines_collapse(self):
        conflict = audit_sidecar_bytes(_dump([_board(), _board(poll_seq=5, exchange_sequence=9002)]))
        self.assertEqual(conflict["contract_status"], "BLOCKED")
        self.assertIn("DUPLICATE_CONFLICT", conflict["reasons"])
        self.assertEqual(conflict["admitted_count"], 0)
        raw = _dump([_board(), _board()])
        collapsed = audit_sidecar_bytes(raw)
        self.assertEqual(collapsed["contract_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(collapsed["row_count"], 2)
        self.assertEqual(collapsed["admitted_count"], 1)
        self.assertEqual(collapsed["synthetic_n"], 1)

    def test_sequence_time_conflict_and_mixed_market_block_the_file(self):
        later = _board(
            observation_id="obs-2",
            poll_seq=5,
            exchange_sequence=9000,
            event_time="2026-10-14T01:00:01.000+09:00",
            watcher_observed_at="2026-10-14T01:00:01.200+09:00",
            read_started_at="2026-10-14T01:00:01.200+09:00",
            read_finished_at="2026-10-14T01:00:01.200+09:00",
            available_at="2026-10-14T01:00:01.500+09:00",
            levels=[_level(1, "2026-10-14T01:00:01.200+09:00")],
        )
        conflict = audit_sidecar_bytes(_dump([_board(), later]))
        self.assertIn("SEQUENCE_TIME_CONFLICT", conflict["reasons"])
        self.assertEqual(conflict["contract_status"], "BLOCKED")
        mixed = audit_sidecar_bytes(_dump([
            _board(),
            _board(observation_id="obs-jnx", symbol="285A.JNX", market="JNX", poll_seq=6, exchange_sequence=9003),
        ]))
        self.assertIn("MIXED_MARKET", mixed["reasons"])
        self.assertEqual(mixed["pit_records"], [])

    def test_corrupt_partial_duplicate_key_and_empty_files_fail_closed(self):
        good = _dump([_board()])
        torn = good + b'{"schema_version":'
        blank = good + b"\n"
        duplicate_key = b'{"schema_version":"ms2-watcher-sidecar-0.1","schema_version":"other"}\n'
        empty = b""
        for raw, code in (
            (torn, "DATA_CORRUPT"),
            (blank, "DATA_CORRUPT"),
            (duplicate_key, "DATA_CORRUPT"),
            (empty, "EMPTY_INPUT"),
            (b"\xff\xfe", "DATA_CORRUPT"),
        ):
            report = audit_sidecar_bytes(raw)
            self.assertEqual(report["contract_status"], "BLOCKED", code)
            self.assertIn(code, report["reasons"])
            self.assertEqual(report["pit_records"], [])
            self.assertEqual(report["admitted_count"], 0)

    def test_legacy_csv_is_not_migrated_or_rewritten(self):
        sentinel = "424242"
        board = (
            "日付,時刻,OVER気配数量,UNDER気配数量,UNDER比率,最良売気配値,最良買気配値,状態\n"
            f"2026-10-14,09:00,1,{sentinel},0.5,101,100,約定あり\n"
        ).encode("utf-8")
        tick = f"recorded_at,tick_time,price,volume,poll_seq\n2026-10-14 09:00:00,09:00:01,{sentinel},100,1\n".encode("utf-8")
        bars = f"bucket_start,open,high,low,close,volume,tick_count\n09:00:00,{sentinel},1,1,1,1,1\n".encode("utf-8")
        diag = "poll_time,window_size,overlap_with_prev,new_appended,suspected_gap\n2026-10-14 09:00:00,1,1,0,False\n".encode("utf-8")
        for raw, code in (
            (board, "LEGACY_BOARD_CSV"),
            (tick, "LEGACY_TICK_CSV"),
            (bars, "LEGACY_15S_CSV"),
            (diag, "LEGACY_DIAG_CSV"),
        ):
            before = hashlib.sha256(raw).hexdigest()
            report = audit_sidecar_bytes(raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), before)
            self.assertEqual(report["contract_status"], "BLOCKED")
            self.assertIn(code, report["reasons"])
            self.assertIn("LEGACY_CSV_NOT_MIGRATED", report["reasons"])
            self.assertNotIn(sentinel, json.dumps(report))

    def test_current_watcher_source_cannot_emit_a_sidecar(self):
        report = audit_sidecar_bytes(_dump([_board(source=CURRENT_WATCHER_SOURCE)]))
        self.assertEqual(report["contract_status"], "BLOCKED")
        self.assertIn("WATCHER_SOURCE_HAS_NO_SIDECAR", report["reasons"])

    def test_authentication_and_order_flags_are_refused(self):
        authenticated = audit_sidecar_bytes(_dump([_board(capture_authenticated=True)]))
        self.assertIn("CAPTURE_AUTHENTICATION_REFUSED", authenticated["reasons"])
        flagged = _board()
        flagged["real_submit_allowed"] = True
        report = audit_sidecar_bytes(_dump([flagged]))
        self.assertEqual(report["contract_status"], "BLOCKED")
        self.assertIn("SAFETY_FLAG_REFUSED", report["reasons"])
        self.assertFalse(report["real_submit_allowed"])
        self.assertFalse(report["promotion_eligible"])
        self.assertFalse(report["statistical_edge_confirmed"])
        self.assertFalse(report["rss_order_enabled"])

    def test_unverified_and_verified_cost_both_stay_unclosed(self):
        raw = _dump([_board()])
        unverified = audit_sidecar_bytes(raw, cost={"status": "UNVERIFIED", "amount_yen": 0})
        self.assertIn("COST_UNVERIFIED", unverified["reasons"])
        self.assertFalse(unverified["closed_eligible"])
        self.assertEqual(unverified["close_state"], "NOT_CLOSED")
        modeled = audit_sidecar_bytes(raw, cost={"status": "MODEL", "amount_yen": 12})
        self.assertIn("COST_MODELED_NOT_VERIFIED", modeled["reasons"])
        sentinel = "private://fee/do-not-export"
        verified = audit_sidecar_bytes(raw, cost={"status": "VERIFIED", "amount_yen": 0, "evidence_ref": sentinel})
        self.assertEqual(verified["cost_status"], "VERIFIED")
        self.assertIn("COST_VERIFIED_NOT_A_FILL", verified["reasons"])
        self.assertFalse(verified["closed_eligible"])
        self.assertEqual(verified["eligible_observed_n"], 0)
        self.assertNotIn(sentinel, json.dumps(redact_report(verified)))
        self.assertNotIn(sentinel, json.dumps(verified))

    def test_redaction_drops_prices(self):
        report = audit_sidecar_bytes(_dump([_board(last_trade_price=515151)]))
        hidden = json.dumps(redact_report(report))
        self.assertNotIn("515151", hidden)
        self.assertNotIn("pit_records", hidden)
        self.assertEqual(json.loads(hidden)["pit_count"], 1)

    def test_a_print_is_not_copied_into_a_quote(self):
        copied = _tick()
        copied["bid"] = copied["price"]
        copied["ask"] = copied["price"] + 1
        report = audit_sidecar_bytes(_dump([copied]))
        self.assertEqual(report["contract_status"], "BLOCKED")
        self.assertIn("UNKNOWN_FIELD", report["reasons"])
        self.assertEqual(report["pit_records"], [])

    def test_ordered_print_projection_stays_synthetic(self):
        report = audit_sidecar_bytes(_dump([_tick()]))
        self.assertEqual(report["contract_status"], "PROJECTABLE_SYNTHETIC")
        self.assertEqual(report["pit_records"][0]["kind"], "ORDERED_PRINT")
        self.assertNotIn("bid", report["pit_records"][0])
        self.assertEqual(report["eligible_observed_n"], 0)

    def test_join_requires_the_same_poll_and_does_not_invent_exchange_order(self):
        stamp = "2026-10-14T01:00:01.000+09:00"
        finish = "2026-10-14T01:00:01.040+09:00"
        board = _incomplete(
            observation_id="join-board",
            poll_seq=7,
            watcher_observed_at=stamp,
            read_started_at=stamp,
            read_finished_at=finish,
            read_skew_ms=40,
            poll_window_ms=2000,
            suspected_gap=False,
            gap_evidence="ATTACHED",
            gap_diag=_gap_diag(7),
            levels=[
                _level(1, stamp, bid_qty=None, ask_qty=None, bid_known=False, ask_known=False),
                _level(2, finish, bid_qty=None, ask_qty=None, bid_known=False, ask_known=False),
            ],
        )
        tick = _tick(
            observation_id="join-tick",
            poll_seq=7,
            sequence_basis="POLL",
            order_proven=False,
            exchange_sequence=None,
            event_time=None,
            event_time_basis="ABSENT",
            watcher_observed_at=stamp,
            available_at=None,
            available_at_basis="NOT_DEMONSTRATED",
            data_freshness="UNKNOWN",
            freshness_basis="NOT_EVIDENCED",
            quote_age_ms=None,
            freshness_bound_ms=None,
            suspected_gap=False,
            gap_evidence="ATTACHED",
            gap_diag=_gap_diag(7),
            price=515151,
            poll_window_ms=2000,
        )
        diag = _diag(observation_id="join-gap", poll_seq=7, watcher_observed_at=stamp, poll_window_ms=2000)
        matched = join_poll_references(board, tick, diag)
        self.assertEqual(matched["status"], "POLL_REFERENCE_MATCHED")
        self.assertFalse(matched["exchange_order_proven"])
        self.assertFalse(matched["pit_projectable"])
        self.assertEqual(matched["eligible_observed_n"], 0)
        self.assertNotIn("515151", json.dumps(matched))
        mismatched_tick = {**tick, "poll_seq": 8, "gap_diag": _gap_diag(8)}
        mismatched = join_poll_references(board, mismatched_tick, diag)
        self.assertEqual(mismatched["status"], "NOT_JOINED")
        self.assertIn("POLL_REFERENCE_MISMATCH", mismatched["reasons"])
        gapped = join_poll_references(
            {**board, "suspected_gap": True, "gap_diag": _gap_diag(7, overlap=0, new=0)},
            tick,
            {**diag, "suspected_gap": True, "overlap_with_prev": 0, "new_appended": 0},
        )
        self.assertEqual(gapped["status"], "BLOCKED")
        self.assertIn("GAP_SUSPECTED", gapped["reasons"])
        late = {**board, "read_finished_at": "2026-10-14T01:00:04.000+09:00", "read_skew_ms": 3000}
        late["levels"] = [
            _level(1, stamp, bid_qty=None, ask_qty=None, bid_known=False, ask_known=False),
            _level(2, "2026-10-14T01:00:04.000+09:00", bid_qty=None, ask_qty=None, bid_known=False, ask_known=False),
        ]
        outside = join_poll_references(late, tick, diag)
        self.assertEqual(outside["status"], "BLOCKED")
        self.assertIn("TIME_REFERENCE_CONTRADICTION", outside["reasons"])
        untimed = join_poll_references(
            {**board, "poll_window_ms": None},
            {**tick, "poll_window_ms": None},
            {**diag, "poll_window_ms": None},
        )
        self.assertEqual(untimed["status"], "NOT_JOINED")
        self.assertIn("TIME_REFERENCE_UNPROVEN", untimed["reasons"])

    def test_private_path_refuses_escape_links_and_missing_files(self):
        self.assertIn("PRIVATE_PATH_INVALID", audit_private_sidecar(ROOT, "data/private/ms2_sidecar/../../paper_trade_history.json")["reasons"])
        self.assertIn("PRIVATE_PATH_INVALID", audit_private_sidecar(ROOT, "/etc/passwd")["reasons"])
        self.assertIn("PRIVATE_PATH_NOT_FOUND", audit_private_sidecar(ROOT, "data/private/ms2_sidecar/missing.jsonl")["reasons"])
        sandbox = ROOT / "data" / "private" / "ms2_sidecar"
        sandbox.mkdir(parents=True, exist_ok=True)
        target = sandbox / "real.jsonl"
        link = sandbox / "link.jsonl"
        target.write_bytes(_dump([_incomplete(observation_id="path-1")]))
        try:
            link.symlink_to(target)
            linked = audit_private_sidecar(ROOT, "data/private/ms2_sidecar/link.jsonl")
            self.assertIn("PRIVATE_PATH_LINK", linked["reasons"])
            admitted = audit_private_sidecar(ROOT, "data/private/ms2_sidecar/real.jsonl")
            self.assertEqual(admitted["contract_status"], "ADMITTED_INCOMPLETE")
            self.assertEqual(target.read_bytes(), _dump([_incomplete(observation_id="path-1")]))
        finally:
            if link.exists() or link.is_symlink():
                link.unlink()
            if target.exists():
                target.unlink()

    def test_oversized_input_is_refused(self):
        report = audit_sidecar_bytes(b"{" * (8 * 1024 * 1024 + 1))
        self.assertEqual(report["contract_status"], "BLOCKED")
        self.assertIn("PRIVATE_FILE_TOO_LARGE", report["reasons"])

    def test_many_incomplete_records_stay_deterministic(self):
        records = [
            _incomplete(observation_id=f"bulk-{index}", poll_seq=index)
            for index in range(1, 201)
        ]
        raw = _dump(records)
        started = time.perf_counter()
        report = audit_sidecar_bytes(raw)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 2.0)
        self.assertEqual(report, audit_sidecar_bytes(raw))
        self.assertEqual(report["contract_status"], "ADMITTED_INCOMPLETE")
        self.assertEqual(report["eligible_observed_n"], 0)

    def test_watcher_history_and_canonical_hash_bytes_stay_at_head(self):
        for relative in (
            "ms2_live/Kioxia_RSS_Live_Watcher.ps1",
            "ms2_live/Resample_Kioxia_Ticks_15s.ps1",
            "scripts/execution_contract.py",
            "scripts/shadow_fill_model.py",
            "scripts/fill_execution_collector_contract.py",
            "paper_trade_history.json",
        ):
            committed = subprocess.check_output(["git", "show", f"HEAD:{relative}"])
            self.assertEqual((ROOT / relative).read_bytes(), committed, relative)
        self.assertEqual(_HASH_FIELDS, (
            "symbol", "side", "quantity", "order_type", "limit_price",
            "planned_entry", "planned_stop", "strategy_id", "strategy_version",
            "decision_snapshot_id", "execution_policy_version",
        ))
        history = json.loads(HISTORY.read_text(encoding="utf-8"))
        self.assertEqual(len(history), 263)
        text = WATCHER.read_text(encoding="utf-8")
        self.assertIn("function Read-BoardDepth", text)
        self.assertIn("function Write-TickLogDiff", text)
        self.assertIn("Start-Sleep -Seconds 2", text)
        self.assertIn("recorded_at,tick_time,price,volume,poll_seq", text)
        self.assertIn("日付,時刻,OVER気配数量,UNDER気配数量,UNDER比率,最良売気配値,最良買気配値,状態", text)
        self.assertNotIn("ms2-watcher-sidecar", text)


if __name__ == "__main__":
    unittest.main()
