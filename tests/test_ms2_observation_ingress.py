import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.ms2_observation_ingress import (
    BAR_HEADER,
    BOARD_HEADER,
    DIAG_HEADER,
    TICK_HEADER,
    audit_private_observation,
    cohort_report,
    main,
    redact_for_export,
    source_field_catalog,
)
from scripts.shadow_fill_model import FILL_MODEL_VERSION
from scripts.timeseries_fill_audit import scan_public_evidence

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DAY = datetime(2026, 10, 14, tzinfo=JST)
RELATIVE = "data/private/ms2_observations/{}"


def at(hour, minute, second=0):
    return DAY.replace(hour=hour, minute=minute, second=second)


def signal(**overrides):
    base = {
        "strategy_id": "day_ifo_long",
        "strategy_version": "1.0",
        "symbol": "285A",
        "side": "LONG",
        "entry_style": "LIMIT",
        "signal_known_at": at(9, 0),
        "entry": 1000,
        "stop": 990,
        "target": 1020,
        "valid_until": at(11, 0),
        "session": "OPENING_09",
        "regime": "RANGE",
        "horizon": "DAYTRADE",
        "family": "OR15",
        "sample_role": "SHADOW",
        "provenance": "synthetic-ordered-quotes",
        "quantity": 100,
        "symbol_class": "UNCLASSIFIED",
        "basis_event_ids": [],
    }
    base.update(overrides)
    return base


VERIFIED_COST = {
    "status": "VERIFIED",
    "fees_yen": 55,
    "slippage_yen": 10,
    "evidence_ref": "synthetic-fee-schedule-v1",
}


def quote_row(event_id, when, last, bid, ask, sequence, **overrides):
    row = {
        "schema_version": "ms2-pit-observation-0.1",
        "event_id": event_id,
        "source": "SYNTHETIC_QUOTE",
        "symbol": "285A",
        "kind": "QUOTE",
        "event_time": when.isoformat(),
        "available_at": when.isoformat(),
        "received_at": when.isoformat(),
        "recorded_at": when.isoformat(),
        "timezone": "+09:00",
        "sequence": sequence,
        "sequence_basis": "EXCHANGE",
        "order_proven": True,
        "bid": bid,
        "ask": ask,
        "bid_qty": 1000,
        "ask_qty": 1000,
        "last_trade_price": last,
        "last_trade_qty": 100,
        "tick_size": 1.0,
        "data_freshness": "OK",
        "suspected_gap": False,
        "session": "OPENING_09",
    }
    row.update(overrides)
    return row


def closed_rows():
    return [
        quote_row("e1", at(9, 1), 999, 998, 999.5, 1),
        quote_row("e2", at(9, 2), 1010, 1009, 1011, 2),
        quote_row("e3", at(9, 3), 1021, 1020, 1022, 3),
    ]


class Ms2ObservationIngressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.directory = self.root / "data" / "private" / "ms2_observations"
        self.directory.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_jsonl(self, rows, name="obs.jsonl"):
        path = self.directory / name
        payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
        path.write_text(payload, encoding="utf-8")
        return path

    def write_csv(self, name, header, rows, bom=False):
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
        data = buffer.getvalue().encode("utf-8")
        if bom:
            data = b"\xef\xbb\xbf" + data
        path = self.directory / name
        path.write_bytes(data)
        return path

    def audit(self, name="obs.jsonl", **kwargs):
        params = {
            "signal": signal(),
            "as_of": at(10, 0),
            "evidence_origin": "SYNTHETIC",
            "cost": VERIFIED_COST,
        }
        params.update(kwargs)
        return audit_private_observation(self.root, RELATIVE.format(name), **params)

    def test_01_complete_synthetic_quote_reaches_virtual_closed(self):
        self.write_jsonl(closed_rows())
        report = self.audit()
        decision = report["decision"]
        self.assertEqual(report["status"], "FORWARDED")
        self.assertEqual(report["state"], "CLOSED")
        self.assertEqual(decision["state"], "CLOSED")
        self.assertEqual(decision["reasons"], ["VIRTUAL_ESTIMATE_CLOSED"])
        self.assertEqual(decision["lane"], "VIRTUAL_ESTIMATE")
        self.assertTrue(decision["estimated_fill"])
        self.assertFalse(decision["real_fill"])
        self.assertFalse(decision["independent_execution_evidence"])
        self.assertEqual(decision["observed_entry_price"], 1000)
        self.assertEqual(decision["observed_entry_at"], at(9, 1).isoformat())
        self.assertEqual(decision["entry_fill_confidence"], "CERTAIN")
        self.assertEqual(decision["observed_exit_price"], 1020)
        self.assertEqual(decision["exit_reason"], "TARGET")
        self.assertEqual(decision["fill_model_version"], FILL_MODEL_VERSION)
        self.assertEqual(decision["fill_model_slippage_status"], "NOT_MODELED_V0_1")
        self.assertIsNone(decision["fill_model_slippage_yen"])
        self.assertEqual(decision["verified_net_pnl_yen"], 1935)
        self.assertEqual(report["forwarded_event_ids"], ["e1", "e2", "e3"])
        self.assertEqual(report["eligible_observed_n"], 0)
        self.assertEqual(report["synthetic_decision_n"], 1)
        self.assertIsNone(report["rollup"]["expectancy_yen"])
        self.assertIsNone(report["rollup"]["profit_factor"])
        self.assertIsNone(report["rollup"]["max_drawdown_yen"])
        self.assertIsNone(report["rollup"]["verified_net_pnl_yen"])
        self.assertIn("NO_ELIGIBLE_OBSERVED_SAMPLE", report["rollup"]["reasons"])
        self.assertFalse(report["quote_fields_invented"])
        self.assertFalse(report["timezone_imputed"])
        self.assertFalse(decision["real_submit_allowed"])
        self.assertFalse(decision["promotion_eligible"])
        self.assertFalse(decision["statistical_edge_confirmed"])

    def test_02_private_path_is_confined(self):
        self.write_jsonl(closed_rows())
        outside = self.root / "outside.csv"
        outside.write_text("recorded_at,tick_time,price,volume,poll_seq\n", encoding="utf-8")
        link = self.directory / "link.csv"
        link.symlink_to(outside)
        cases = [
            "data/private/ms2_observations/../../outside.csv",
            "/tmp/outside.csv",
            "data/private/broker_exports/outside.csv",
            "data/private/ms2_observations/link.csv",
            "data/private/ms2_observations/missing.csv",
            "data/private/ms2_observations/nested/obs.jsonl",
        ]
        for relative in cases:
            report = audit_private_observation(self.root, relative, signal=signal(), as_of=at(10, 0))
            self.assertEqual(report["bytes_read"], 0, relative)
            self.assertIsNone(report["decision"], relative)
            self.assertTrue(report["reasons"], relative)
            self.assertNotIn("FORWARDED", report["status"])
        self.assertEqual(outside.read_text(encoding="utf-8").count("1000"), 0)

    def test_03_read_only_and_unset_path_reads_nothing(self):
        path = self.write_jsonl(closed_rows())
        before = path.read_bytes()
        path.chmod(0o444)
        names_before = sorted(item.name for item in self.directory.iterdir())
        report = self.audit()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(item.name for item in self.directory.iterdir()), names_before)
        self.assertEqual(report["state"], "CLOSED")
        self.assertFalse(report["safety"]["writes_performed"])
        empty = Path(tempfile.mkdtemp())
        try:
            unread = audit_private_observation(empty, None)
            self.assertEqual(unread["status"], "NOT_READ")
            self.assertEqual(unread["state"], "UNKNOWN")
            self.assertEqual(unread["reasons"], ["PRIVATE_PATH_UNSET"])
            self.assertEqual(unread["bytes_read"], 0)
            self.assertFalse((empty / "data").exists())
        finally:
            empty.rmdir()
        source = (ROOT / "scripts" / "ms2_observation_ingress.py").read_text(encoding="utf-8")
        self.assertNotIn("write_text", source)
        self.assertNotIn("write_bytes", source)
        self.assertNotIn("RssOrder", source)

    def test_04_missing_timestamps_are_not_invented(self):
        missing_event = quote_row("e1", at(9, 1), 999, 998, 999.5, 1)
        missing_event.pop("event_time")
        missing_event["recorded_at"] = at(9, 1).isoformat()
        self.write_jsonl([missing_event])
        report = self.audit()
        self.assertFalse(report["forwarded_to_evaluator"])
        self.assertIsNone(report["decision"])
        self.assertIn("EVENT_TIME_ABSENT", report["reasons"])
        self.assertIn("RECORDED_AT_NOT_USED_AS_EVENT_TIME", report["reasons"])
        self.assertFalse(report["dates_joined_from_recorded_at"])
        self.assertFalse(report["timezone_imputed"])

        missing_available = quote_row("e1", at(9, 1), 999, 998, 999.5, 1)
        missing_available.pop("available_at")
        self.write_jsonl([missing_available], name="available.jsonl")
        available = self.audit("available.jsonl")
        self.assertIn("AVAILABLE_AT_ABSENT", available["reasons"])
        self.assertIsNone(available["decision"])

        inverted = quote_row("e1", at(9, 1), 999, 998, 999.5, 1, available_at=at(8, 59).isoformat())
        self.write_jsonl([inverted], name="inverted.jsonl")
        inverted_report = self.audit("inverted.jsonl")
        self.assertEqual(inverted_report["state"], "BLOCKED")
        self.assertIn("TIMESTAMP_INCONSISTENT", inverted_report["decision"]["reasons"])
        self.assertIsNone(inverted_report["decision"]["observed_entry_price"])

    def test_05_timezone_label_is_not_treated_as_jst(self):
        naive = quote_row("e1", at(9, 1), 999, 998, 999.5, 1)
        naive["event_time"] = "2026-10-14T09:01:00"
        naive["available_at"] = "2026-10-14T09:01:00"
        naive["timezone"] = "JST"
        self.write_jsonl([naive])
        report = self.audit()
        self.assertIn("TIMEZONE_UNKNOWN", report["reasons"])
        self.assertIsNone(report["decision"])
        self.assertFalse(report["timezone_imputed"])
        self.assertNotIn("+09:00", json.dumps(report["reasons"]))

        self.write_csv(
            "ticks.csv",
            TICK_HEADER,
            [["2026-10-14 09:00:01", "09:00:01", "1000", "100", "1"]],
            bom=True,
        )
        legacy = self.audit("ticks.csv")
        self.assertEqual(legacy["producer_id"], "ms2_live.kioxia_tick_log")
        self.assertIn("TIMEZONE_ABSENT", legacy["reasons"])
        self.assertIn("EVENT_TIME_DATE_ABSENT", legacy["reasons"])
        self.assertIn("RECORDED_AT_IS_COLLECTOR_CLOCK", legacy["reasons"])
        self.assertFalse(legacy["timezone_imputed"])
        self.assertFalse(legacy["dates_joined_from_recorded_at"])
        self.assertIsNone(legacy["decision"])
        self.assertNotIn("1000", json.dumps(legacy))

    def test_06_future_and_lookahead_are_not_used(self):
        rows = closed_rows()
        rows[2]["data_freshness"] = "FUTURE"
        self.write_jsonl(rows)
        fresh = self.audit()
        self.assertEqual(fresh["state"], "BLOCKED")
        self.assertIn("OBSERVATION_FRESHNESS_FUTURE", fresh["decision"]["reasons"])
        self.assertIsNone(fresh["decision"]["verified_net_pnl_yen"])

        later = quote_row("future", at(11, 30), 1021, 1020, 1022, 4)
        self.write_jsonl([closed_rows()[0], later], name="later.jsonl")
        report = self.audit("later.jsonl")
        self.assertEqual(report["decision"]["lookahead_excluded_event_ids"], ["future"])
        self.assertEqual(report["state"], "ENTRY_OBSERVED")
        self.assertEqual(report["decision"]["reasons"], ["EXIT_NOT_OBSERVED"])
        self.assertEqual(report["decision"]["observed_entry_at"], at(9, 1).isoformat())
        self.assertIsNone(report["decision"]["observed_exit_price"])
        self.assertIsNone(report["decision"]["verified_net_pnl_yen"])

    def test_07_stale_blocks(self):
        rows = closed_rows()
        rows[1]["data_freshness"] = "STALE"
        self.write_jsonl(rows)
        report = self.audit()
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["decision"]["reasons"], ["STALE"])
        self.assertIsNone(report["decision"]["observed_entry_price"])
        self.assertIsNone(report["decision"]["verified_net_pnl_yen"])

    def test_08_suspected_gap_blocks(self):
        rows = closed_rows()
        rows[0]["suspected_gap"] = True
        self.write_jsonl(rows)
        report = self.audit()
        self.assertEqual(report["state"], "BLOCKED")
        self.assertIn("SUSPECTED_GAP", report["decision"]["reasons"])
        self.assertIsNone(report["decision"]["verified_net_pnl_yen"])

        self.write_csv(
            "ticks.csv",
            TICK_HEADER,
            [["2026-10-14 09:00:01", "09:00:01", "1000", "100", "7"]],
        )
        self.write_csv(
            "diag.csv",
            DIAG_HEADER,
            [["2026-10-14 09:00:02", "300", "0", "1", "True"]],
        )
        legacy = audit_private_observation(
            self.root,
            RELATIVE.format("ticks.csv"),
            diag_relative_path=RELATIVE.format("diag.csv"),
            signal=signal(),
            as_of=at(10, 0),
        )
        self.assertIn("SUSPECTED_GAP", legacy["reasons"])
        self.assertIn("GAP_NOT_JOINED_TO_PRINT", legacy["reasons"])
        self.assertIn("POLL_SEQUENCE_IS_NOT_EXCHANGE_ORDER", legacy["reasons"])
        self.assertFalse(legacy["forwarded_to_evaluator"])
        self.assertFalse(legacy["exchange_order_assumed_from_poll"])

        absent = self.audit("ticks.csv")
        self.assertIn("GAP_DIAGNOSTIC_ABSENT", absent["reasons"])
        self.write_csv(
            "clean_diag.csv",
            DIAG_HEADER,
            [["2026-10-14 09:00:02", "300", "10", "1", "False"]],
        )
        clean = audit_private_observation(
            self.root,
            RELATIVE.format("ticks.csv"),
            diag_relative_path=RELATIVE.format("clean_diag.csv"),
        )
        self.assertIn("GAP_NOT_JOINED_TO_PRINT", clean["reasons"])
        self.assertNotIn("SUSPECTED_GAP", clean["reasons"])
        self.assertIsNone(clean["decision"])

    def test_09_duplicate_and_conflicting_event_ids(self):
        row = quote_row("e1", at(9, 1), 999, 998, 999.5, 1)
        self.write_jsonl([row, dict(row)])
        duplicate = self.audit()
        self.assertTrue(duplicate["forwarded_to_evaluator"])
        self.assertEqual(duplicate["state"], "BLOCKED")
        self.assertIn("DUPLICATE_EVENT", duplicate["decision"]["reasons"])
        self.assertIsNone(duplicate["decision"]["observed_entry_price"])

        other = quote_row("e1", at(9, 1), 990, 989, 991, 1)
        self.write_jsonl([row, other], name="conflict.jsonl")
        conflict = self.audit("conflict.jsonl")
        self.assertFalse(conflict["forwarded_to_evaluator"])
        self.assertIn("CONFLICTING_EVENT_ID", conflict["reasons"])
        self.assertIsNone(conflict["decision"])
        self.assertEqual(conflict["forwarded_event_ids"], [])

    def test_10_same_timestamp_order_unknown(self):
        first = quote_row("e1", at(9, 1), 999, 998, 999.5, 1)
        second = quote_row("e2", at(9, 1), 1021, 1020, 1022, 2)
        self.write_jsonl([second, first])
        report = self.audit()
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["decision"]["reasons"], ["TIMESTAMP_TIE_ORDER_UNKNOWN"])
        self.assertEqual(report["forwarded_event_ids"], ["e1", "e2"])
        self.assertIsNone(report["decision"]["observed_exit_price"])
        self.assertFalse(report["exchange_order_assumed_from_poll"])

    def test_11_fifteen_second_bar_does_not_order_the_bucket(self):
        self.write_csv(
            "bars.csv",
            BAR_HEADER,
            [["09:00:00", "1000", "1030", "980", "1010", "500", "4"]],
        )
        legacy = self.audit("bars.csv")
        self.assertEqual(legacy["producer_id"], "ms2_live.kioxia_15s")
        self.assertIn("BAR_15S_INTRABAR_ORDER_UNKNOWN", legacy["reasons"])
        self.assertIn("EMPTY_BUCKETS_OMITTED", legacy["reasons"])
        self.assertIn("TIMEZONE_ABSENT", legacy["reasons"])
        self.assertFalse(legacy["forwarded_to_evaluator"])
        self.assertIsNone(legacy["decision"])

        bars = []
        for index, (low, high) in enumerate(((980, 1030), (970, 1040)), start=1):
            start = at(9, 1, (index - 1) * 15)
            bars.append({
                "schema_version": "ms2-pit-observation-0.1",
                "event_id": f"b{index}",
                "source": "SYNTHETIC_15S",
                "symbol": "285A",
                "kind": "OHLCV_BAR",
                "event_time": start.isoformat(),
                "event_time_end": (start + timedelta(seconds=15)).isoformat(),
                "available_at": (start + timedelta(seconds=15)).isoformat(),
                "timezone": "+09:00",
                "sequence": index,
                "sequence_basis": "EXCHANGE",
                "order_proven": True,
                "open": (low + high) / 2,
                "high": high,
                "low": low,
                "close": (low + high) / 2,
                "volume": 100,
                "bar_seconds": 15,
                "data_freshness": "OK",
                "suspected_gap": False,
                "session": "OPENING_09",
            })
        self.write_jsonl(bars, name="bars.jsonl")
        report = self.audit("bars.jsonl")
        self.assertEqual(report["state"], "UNKNOWN")
        self.assertEqual(report["decision"]["reasons"], ["INTRABAR_EXTREME_ORDER_UNKNOWN"])
        self.assertEqual(report["decision"]["intrabar_extreme_order"], "UNKNOWN")
        self.assertIsNone(report["decision"]["observed_entry_price"])
        self.assertIsNone(report["decision"]["verified_net_pnl_yen"])

    def test_12_book_is_not_invented_from_a_print(self):
        printed = {
            "schema_version": "ms2-pit-observation-0.1",
            "event_id": "p1",
            "source": "MS2_RSS_TICKLIST",
            "symbol": "285A",
            "kind": "ORDERED_PRINT",
            "event_time": at(9, 1).isoformat(),
            "available_at": at(9, 1).isoformat(),
            "timezone": "+09:00",
            "sequence": 1,
            "sequence_basis": "EXCHANGE",
            "order_proven": True,
            "price": 999,
            "volume": 100,
            "data_freshness": "OK",
            "suspected_gap": False,
            "session": "OPENING_09",
        }
        self.write_jsonl([printed])
        report = self.audit()
        self.assertEqual(report["state"], "ENTRY_ELIGIBLE")
        self.assertEqual(report["decision"]["reasons"], ["FILL_MODEL_INPUT_INCOMPLETE"])
        self.assertFalse(report["decision"]["estimated_fill"])
        self.assertIsNone(report["decision"]["observed_entry_price"])
        self.assertFalse(report["quote_fields_invented"])
        self.assertNotIn("bid", json.dumps(redact_for_export(report)))

        incomplete = quote_row("e1", at(9, 1), 999, 998, 999.5, 1)
        incomplete.pop("ask_qty")
        self.write_jsonl([incomplete], name="incomplete.jsonl")
        missing_book = self.audit("incomplete.jsonl")
        self.assertIn("BOOK_INCOMPLETE", missing_book["reasons"])
        self.assertIsNone(missing_book["decision"])

        self.write_csv(
            "board.csv",
            BOARD_HEADER,
            [["2026-10-14", "09:01", "1000", "2000", "0.6667", "1001", "1000", "約定あり"]],
        )
        board = self.audit("board.csv")
        self.assertEqual(board["producer_id"], "ms2_live.board_log")
        self.assertIn("BOARD_QTY_ABSENT", board["reasons"])
        self.assertIn("BOOK_LOG_IS_NOT_A_QUOTE", board["reasons"])
        self.assertIn("MINUTE_CLOCK_ONLY", board["reasons"])
        self.assertIsNone(board["decision"])
        self.assertNotIn("1001", json.dumps(board))

    def test_13_abnormal_price_and_volume_block(self):
        crossed = quote_row("e1", at(9, 1), 999, 1002, 1000, 1)
        self.write_jsonl([crossed])
        price = self.audit()
        self.assertEqual(price["state"], "BLOCKED")
        self.assertIn("ABNORMAL_PRICE", price["decision"]["reasons"])
        self.assertIsNone(price["decision"]["observed_entry_price"])

        printed = {
            "schema_version": "ms2-pit-observation-0.1",
            "event_id": "p1",
            "source": "MS2_RSS_TICKLIST",
            "symbol": "285A",
            "kind": "ORDERED_PRINT",
            "event_time": at(9, 1).isoformat(),
            "available_at": at(9, 1).isoformat(),
            "timezone": "+09:00",
            "sequence": 1,
            "sequence_basis": "EXCHANGE",
            "order_proven": True,
            "price": 999,
            "volume": -5,
            "data_freshness": "OK",
            "suspected_gap": False,
            "session": "OPENING_09",
        }
        self.write_jsonl([printed], name="volume.jsonl")
        volume = self.audit("volume.jsonl")
        self.assertEqual(volume["state"], "BLOCKED")
        self.assertIn("ABNORMAL_VOLUME", volume["decision"]["reasons"])

    def test_14_corrupt_input_is_not_repaired(self):
        path = self.directory / "broken.jsonl"
        path.write_text('{"event_id": "e1", "event_id": "e2"}\n', encoding="utf-8")
        before = path.read_bytes()
        duplicate_key = self.audit("broken.jsonl")
        self.assertEqual(duplicate_key["reasons"], ["DATA_CORRUPT"])
        self.assertEqual(duplicate_key["forwarded_event_ids"], [])
        self.assertEqual(path.read_bytes(), before)

        path.write_text("{", encoding="utf-8")
        truncated = self.audit("broken.jsonl")
        self.assertEqual(truncated["reasons"], ["DATA_CORRUPT"])
        self.assertIsNone(truncated["decision"])

        self.write_csv("short.csv", TICK_HEADER, [["2026-10-14 09:00:01", "09:00:01", "1000", "100"]])
        short = self.audit("short.csv")
        self.assertEqual(short["reasons"], ["DATA_CORRUPT"])
        self.assertEqual(short["row_count"], 0)
        self.assertIsNone(short["decision"])

        self.write_csv("unknown.csv", ("foo", "bar"), [["1", "2"]])
        unknown = self.audit("unknown.csv")
        self.assertEqual(unknown["reasons"], ["UNKNOWN_MS2_SCHEMA"])

    def test_14b_valid_jsonl_without_terminating_newline_is_not_published(self):
        # Even a syntactically complete JSON object without the Writer's final
        # newline can be an interrupted write. Its content cannot be admitted.
        path = self.directory / "torn.jsonl"
        rows = closed_rows()
        first = json.dumps(rows[0], ensure_ascii=False).encode("utf-8")
        second = json.dumps(rows[1], ensure_ascii=False).encode("utf-8")
        third = json.dumps(rows[2], ensure_ascii=False).encode("utf-8")
        for payload in (
            first,
            first + b"\\n" + second,
            first + b"\\n" + second + b"\\n" + third,
        ):
            with self.subTest(size=len(payload)):
                path.write_bytes(payload)
                unchanged = path.read_bytes()
                report = self.audit("torn.jsonl")
                self.assertEqual(report["status"], "BLOCKED")
                self.assertEqual(report["state"], "BLOCKED")
                self.assertEqual(report["reasons"], ["PARTIAL_PUBLISHED_JSONL"])
                self.assertEqual(report["forwarded_event_ids"], [])
                self.assertFalse(report["forwarded_to_evaluator"])
                self.assertIsNone(report["decision"])
                self.assertEqual(report["eligible_observed_n"], 0)
                self.assertEqual(path.read_bytes(), unchanged)

        # A fully terminated CRLF stream is valid and retains the original
        # synthetic-vs-recorded boundary; this check never promotes live data.
        path.write_bytes(first + b"\\r\\n" + second + b"\\r\\n" + third + b"\\r\\n")
        accepted = self.audit("torn.jsonl")
        self.assertEqual(accepted["status"], "FORWARDED")
        self.assertEqual(accepted["state"], "CLOSED")
        self.assertEqual(accepted["eligible_observed_n"], 0)
        self.assertEqual(accepted["synthetic_decision_n"], 1)

    def test_15_replay_is_deterministic(self):
        rows = list(reversed(closed_rows()))
        self.write_jsonl(rows)
        first = self.audit()
        second = self.audit()
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )
        self.write_jsonl(closed_rows(), name="ordered.jsonl")
        ordered = self.audit("ordered.jsonl")
        self.assertEqual(first["decision"], ordered["decision"])
        self.assertNotEqual(first["input_sha256"], ordered["input_sha256"])
        self.assertEqual(first["state"], "CLOSED")

    def test_16_train_test_shadow_are_not_blended(self):
        self.write_jsonl(closed_rows())
        decisions = []
        for role in ("TRAIN", "TEST", "SHADOW"):
            report = self.audit(signal=signal(sample_role=role))
            self.assertEqual(report["state"], "CLOSED")
            self.assertEqual(report["decision"]["sample_role"], role)
            decisions.append(report["decision"])
        summary = cohort_report(decisions)
        self.assertTrue(summary["mixed_cohort"])
        self.assertEqual(summary["eligible_observed_n"], 0)
        self.assertIsNone(summary["expectancy_yen"])
        self.assertIsNone(summary["profit_factor"])
        self.assertIsNone(summary["max_drawdown_yen"])
        self.assertIsNone(summary["verified_net_pnl_yen"])
        self.assertIn("MIXED_COHORT", summary["reasons"])
        self.assertFalse(summary["statistical_edge_confirmed"])

    def test_17_real_lane_is_not_a_virtual_close(self):
        self.write_jsonl(closed_rows())
        recorded = self.audit(evidence_origin="RECORDED")
        self.assertEqual(recorded["reasons"], ["RECORDED_PROVENANCE_NOT_AUTHENTICATED"])
        self.assertFalse(recorded["forwarded_to_evaluator"])
        self.assertEqual(recorded["eligible_observed_n"], 0)
        self.assertFalse(recorded["safety"]["source_authenticated"])

        broker = closed_rows()
        for row in broker:
            row["source"] = "BROKER_EXECUTION_EXPORT"
        self.write_jsonl(broker, name="broker.jsonl")
        refused = self.audit("broker.jsonl")
        self.assertEqual(refused["state"], "BLOCKED")
        self.assertIn("REAL_SOURCE_NOT_ACCEPTED_IN_VIRTUAL_AUDIT", refused["decision"]["reasons"])
        self.assertFalse(refused["decision"]["real_fill"])

        real_signal = self.audit(signal=signal(lane="REAL", sample_role="SHADOW"))
        self.assertIn("REAL_LANE_NOT_VIRTUAL_AUDIT", real_signal["decision"]["reasons"])
        self.assertFalse(real_signal["decision"]["real_fill"])
        self.assertIsNone(real_signal["decision"]["verified_net_pnl_yen"])

    def test_18_unverified_zero_cost_is_not_verified_net(self):
        self.write_jsonl(closed_rows())
        zero = self.audit(cost={"fees_yen": 0, "slippage_yen": 0})
        self.assertEqual(zero["state"], "EXIT_OBSERVED")
        self.assertEqual(zero["decision"]["reasons"], ["COST_UNVERIFIED"])
        self.assertEqual(zero["decision"]["cost_status"], "UNVERIFIED")
        self.assertIsNone(zero["decision"]["fees_yen"])
        self.assertIsNone(zero["decision"]["verified_net_pnl_yen"])
        self.assertTrue(zero["decision"]["estimated_fill"])

        modeled = self.audit(cost={
            "status": "MODEL",
            "fees_yen": 0,
            "slippage_yen": 0,
            "model_version": "fee-model-unverified",
            "assumptions": "zero is a model input, not a broker invoice",
            "evidence_ref": "model-note",
        })
        self.assertEqual(modeled["state"], "EXIT_OBSERVED")
        self.assertEqual(modeled["decision"]["reasons"], ["COST_MODEL_NOT_VERIFIED_NET"])
        self.assertIsNone(modeled["decision"]["verified_net_pnl_yen"])
        self.assertIsNotNone(modeled["decision"]["model_net_pnl_yen"])

        claimed = self.audit(cost={"status": "VERIFIED", "fees_yen": 0, "slippage_yen": 0})
        self.assertEqual(claimed["state"], "EXIT_OBSERVED")
        self.assertEqual(claimed["decision"]["reasons"], ["COST_INVALID"])
        self.assertIsNone(claimed["decision"]["verified_net_pnl_yen"])

    def test_19_existing_263_history_bytes_stay_unchanged(self):
        history = ROOT / "paper_trade_history.json"
        before = history.read_bytes()
        self.assertEqual(len(json.loads(before.decode("utf-8"))), 263)
        watched = [
            ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1",
            ROOT / "ms2_live" / "Resample_Kioxia_Ticks_15s.ps1",
            ROOT / "scripts" / "shadow_fill_model.py",
            ROOT / "scripts" / "execution_contract.py",
            ROOT / "scripts" / "timeseries_fill_audit.py",
            ROOT / "scripts" / "fill_execution_collector_contract.py",
        ]
        snapshots = {path: path.read_bytes() for path in watched}
        self.write_jsonl(closed_rows())
        report = self.audit()
        self.assertEqual(report["state"], "CLOSED")
        self.assertEqual(history.read_bytes(), before)
        for path, blob in snapshots.items():
            self.assertEqual(path.read_bytes(), blob, path.name)
        scan = scan_public_evidence(ROOT)
        self.assertEqual(scan["paper_history_n"], 263)
        self.assertEqual(scan["paper_history_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(scan["paper_history_admissible_n"], 0)
        self.assertEqual(scan["observed_eligible_n"], 0)
        self.assertEqual(scan["tick_log_files"], [])
        self.assertEqual(scan["bar_15s_files"], [])

    def test_20_real_submit_stays_refused(self):
        self.write_jsonl(closed_rows())
        report = self.audit(signal=signal(
            real_submit_allowed=True,
            promotion_eligible=True,
            statistical_edge_confirmed=True,
        ))
        self.assertEqual(report["state"], "BLOCKED")
        self.assertIn("REAL_SUBMIT_REQUEST_REJECTED", report["decision"]["reasons"])
        self.assertFalse(report["decision"]["real_submit_allowed"])
        self.assertFalse(report["decision"]["promotion_eligible"])
        self.assertFalse(report["decision"]["statistical_edge_confirmed"])
        self.assertFalse(report["safety"]["rss_order_enabled"])
        source = (ROOT / "scripts" / "ms2_observation_ingress.py").read_text(encoding="utf-8")
        self.assertNotIn("RssOrder", source)
        self.assertNotIn("real_submit_allowed = True", source)
        self.assertNotIn("promotion_eligible = True", source)

    def test_source_catalog_matches_watcher_files(self):
        catalog = {row["field"]: row for row in source_field_catalog()}
        expected = {
            "symbol", "source", "event_id", "event_time", "available_at", "received_at",
            "recorded_at", "timezone", "poll_seq", "price", "volume", "bid", "ask",
            "bid_qty", "ask_qty", "suspected_gap", "data_freshness",
        }
        self.assertEqual(set(catalog), expected)
        self.assertIn("Do not assume", catalog["timezone"]["missing_treatment"])
        self.assertIn("as exchange execution order", catalog["poll_seq"]["missing_treatment"])
        self.assertIn("Do not use the print price as the bid", catalog["bid"]["missing_treatment"])
        self.assertIn("not joined", catalog["suspected_gap"]["missing_treatment"].lower())
        watcher = (ROOT / "ms2_live" / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8")
        resample = (ROOT / "ms2_live" / "Resample_Kioxia_Ticks_15s.ps1").read_text(encoding="utf-8")
        self.assertIn(",".join(TICK_HEADER), watcher)
        self.assertIn(",".join(DIAG_HEADER), watcher)
        self.assertIn(",".join(BOARD_HEADER), watcher)
        self.assertIn(",".join(BAR_HEADER), resample)
        self.assertIn("recorded_at→poll_seq", resample)

    def test_poll_order_is_not_exchange_order(self):
        rows = closed_rows()
        for index, row in enumerate(rows, start=1):
            row["sequence_basis"] = "POLL"
            row["sequence"] = index
            row["order_proven"] = False
            row["poll_seq"] = index
        self.write_jsonl(rows)
        report = self.audit()
        self.assertIn("POLL_ORDER_NOT_EXCHANGE_ORDER", report["reasons"])
        self.assertFalse(report["forwarded_to_evaluator"])
        self.assertFalse(report["exchange_order_assumed_from_poll"])
        self.assertIsNone(report["decision"])

        reversed_seq = closed_rows()
        reversed_seq[0]["sequence"] = 2
        reversed_seq[1]["sequence"] = 1
        self.write_jsonl(reversed_seq, name="reversed.jsonl")
        conflict = self.audit("reversed.jsonl")
        self.assertIn("SEQUENCE_TIME_CONFLICT", conflict["reasons"])
        self.assertIsNone(conflict["decision"])

    def test_mixed_market_and_session_block(self):
        rows = [
            quote_row("e1", at(9, 1), 999, 998, 999.5, 1, market="TSE"),
            quote_row("e2", at(9, 2), 1010, 1009, 1011, 2, market="JNX"),
        ]
        self.write_jsonl(rows)
        mixed = self.audit()
        self.assertIn("MIXED_MARKET", mixed["reasons"])
        self.assertIsNone(mixed["decision"])

        session_rows = [
            quote_row("e1", at(9, 1), 999, 998, 999.5, 1),
            quote_row("e2", at(9, 2), 1010, 1009, 1011, 2, session="AFTERNOON"),
        ]
        self.write_jsonl(session_rows, name="session.jsonl")
        session = self.audit("session.jsonl")
        self.assertEqual(session["state"], "BLOCKED")
        self.assertIn("MIXED_SESSION", session["decision"]["reasons"])
        self.assertIsNone(session["decision"]["verified_net_pnl_yen"])

    def test_export_omits_fill_prices(self):
        self.write_jsonl(closed_rows())
        report = self.audit()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(["--repo-root", str(self.root), "--input", RELATIVE.format("obs.jsonl")])
        self.assertEqual(code, 0)
        exported = buffer.getvalue()
        self.assertNotIn("observed_entry_price", exported)
        self.assertNotIn("998", exported)
        self.assertNotIn("1935", exported)
        self.assertIn("BLOCKED", exported)
        redacted = redact_for_export(report)
        self.assertNotIn("decision", redacted)
        self.assertEqual(redacted["decision_state"], "CLOSED")
        self.assertNotIn("observed_entry_price", json.dumps(redacted))


if __name__ == "__main__":
    unittest.main()
