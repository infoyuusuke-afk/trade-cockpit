import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.timeseries_fill_audit import (
    evaluate_virtual_fill,
    scan_public_evidence,
    summarize_cohort,
)

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
DAY = datetime(2026, 10, 14, tzinfo=JST)


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


def quote(event_id, when, last, bid, ask, **overrides):
    base = {
        "event_id": event_id,
        "source": "SYNTHETIC_QUOTE",
        "symbol": "285A",
        "kind": "QUOTE",
        "event_time": when,
        "available_at": when,
        "received_at": when,
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
    base.update(overrides)
    return base


def bar(event_id, when, low, high, **overrides):
    base = {
        "event_id": event_id,
        "source": "SYNTHETIC_15S",
        "symbol": "285A",
        "kind": "OHLCV_BAR",
        "event_time": when,
        "event_time_end": when + timedelta(seconds=15),
        "available_at": when + timedelta(seconds=15),
        "open": (low + high) / 2,
        "high": high,
        "low": low,
        "close": (low + high) / 2,
        "volume": 100,
        "bar_seconds": 15,
        "data_freshness": "OK",
        "suspected_gap": False,
        "session": "OPENING_09",
    }
    base.update(overrides)
    return base


VERIFIED_COST = {
    "status": "VERIFIED",
    "fees_yen": 55,
    "slippage_yen": 10,
    "evidence_ref": "synthetic-fee-schedule-v1",
}


def evaluate(observations, **kwargs):
    params = {
        "signal": signal(),
        "observations": observations,
        "as_of": at(10, 0),
        "evidence_origin": "SYNTHETIC",
        "cost": VERIFIED_COST,
    }
    params.update(kwargs)
    return evaluate_virtual_fill(**params)


class TimeseriesFillAuditTests(unittest.TestCase):
    def test_01_ordered_entry_then_exit_closes_only_as_virtual_estimate(self):
        result = evaluate([
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e2", at(9, 2), 1010, 1009, 1011),
            quote("e3", at(9, 3), 1021, 1020, 1022),
        ])
        self.assertEqual(result["state"], "CLOSED")
        self.assertEqual(result["reasons"], ["VIRTUAL_ESTIMATE_CLOSED"])
        self.assertEqual(result["lane"], "VIRTUAL_ESTIMATE")
        self.assertTrue(result["estimated_fill"])
        self.assertFalse(result["real_fill"])
        self.assertFalse(result["independent_execution_evidence"])
        self.assertEqual(result["observed_entry_price"], 1000)
        self.assertEqual(result["observed_entry_at"], at(9, 1).isoformat())
        self.assertEqual(result["entry_fill_confidence"], "CERTAIN")
        self.assertEqual(result["entry_fill_reason"], "TRADE_THROUGH")
        self.assertEqual(result["observed_exit_price"], 1020)
        self.assertEqual(result["exit_reason"], "TARGET")
        self.assertEqual(result["exit_fill_confidence"], "CERTAIN")
        self.assertEqual(result["fill_model_version"], "shadow-fill-model-0.1")
        self.assertIsNone(result["fill_model_slippage_yen"])
        self.assertEqual(result["fill_model_slippage_status"], "NOT_MODELED_V0_1")
        self.assertEqual(result["verified_net_pnl_yen"], 1935)
        self.assertEqual(result["mfe_per_share"], 21)
        self.assertEqual(result["mae_per_share"], 0)
        self.assertFalse(result["mfe_mae_uses_pre_entry_extreme"])
        self.assertFalse(result["real_submit_allowed"])
        self.assertFalse(result["promotion_eligible"])
        self.assertFalse(result["statistical_edge_confirmed"])

    def test_02_entry_not_established_stays_at_signal(self):
        result = evaluate([
            quote("e1", at(9, 1), 1005, 1004, 1006),
            quote("e2", at(9, 2), 1010, 1009, 1011),
        ])
        self.assertEqual(result["state"], "SIGNAL")
        self.assertEqual(result["reasons"], ["ENTRY_NOT_REACHED"])
        self.assertIsNone(result["observed_entry_price"])
        self.assertIsNone(result["observed_exit_price"])
        self.assertIsNone(result["verified_net_pnl_yen"])
        self.assertFalse(result["estimated_fill"])

    def test_03_pre_entry_high_is_not_a_target_or_mfe(self):
        result = evaluate([
            quote("before", at(9, 1), 1030, 1029, 1031),
            quote("entry", at(9, 2), 999, 998, 999.5),
            quote("after", at(9, 3), 1005, 1004, 1006),
        ])
        self.assertEqual(result["state"], "ENTRY_OBSERVED")
        self.assertEqual(result["reasons"], ["EXIT_NOT_OBSERVED"])
        self.assertIsNone(result["exit_reason"])
        self.assertIsNone(result["observed_exit_price"])
        self.assertEqual(result["observed_entry_price"], 1000)
        self.assertEqual(result["mfe_per_share"], 5)
        self.assertNotEqual(result["mfe_per_share"], 30)
        self.assertFalse(result["mfe_mae_uses_pre_entry_extreme"])

    def test_04_pre_entry_low_is_not_a_stop_or_mae(self):
        result = evaluate(
            [
                quote("before", at(9, 1), 980, 979, 981),
                quote("entry", at(9, 2), 1001, 1000, 1002),
                quote("after", at(9, 3), 1003, 1002, 1004),
            ],
            signal=signal(entry_style="BREAKOUT", provenance="synthetic-breakout"),
        )
        self.assertEqual(result["state"], "ENTRY_OBSERVED")
        self.assertIsNone(result["exit_reason"])
        self.assertNotEqual(result["exit_reason"], "STOP")
        self.assertEqual(result["observed_entry_price"], 1002)
        self.assertEqual(result["mae_per_share"], 0)
        self.assertNotEqual(result["mae_per_share"], 22)

    def test_05_same_bar_stop_and_target_is_not_chosen(self):
        result = evaluate([
            quote("entry", at(9, 1), 999, 998, 999.5),
            bar("both", at(9, 2), 980, 1030),
        ])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["reasons"], ["INTRABAR_EXIT_ORDER_UNKNOWN"])
        self.assertEqual(result["intrabar_extreme_order"], "UNKNOWN")
        self.assertIsNone(result["exit_reason"])
        self.assertIsNone(result["observed_exit_price"])
        self.assertIsNone(result["verified_net_pnl_yen"])
        self.assertNotEqual(result["state"], "CLOSED")

    def test_06_fifteen_second_bar_does_not_order_high_and_low(self):
        result = evaluate([
            bar("only", at(9, 1), 980, 1030),
        ])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(result["reasons"], ["INTRABAR_EXTREME_ORDER_UNKNOWN"])
        self.assertEqual(result["intrabar_extreme_order"], "UNKNOWN")
        self.assertIsNone(result["observed_entry_price"])
        self.assertFalse(result["estimated_fill"])
        self.assertIsNone(result["verified_net_pnl_yen"])

    def test_07_missing_data_blocks(self):
        result = evaluate([
            quote("gap", at(9, 1), 999, 998, 999.5, kind="MISSING", quality="MISSING"),
        ])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("DATA_MISSING", result["reasons"])
        self.assertIsNone(result["observed_entry_price"])
        self.assertIsNone(result["verified_net_pnl_yen"])

    def test_08_suspected_gap_blocks(self):
        result = evaluate([
            quote("g", at(9, 1), 999, 998, 999.5, suspected_gap=True),
        ])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("SUSPECTED_GAP", result["reasons"])
        self.assertIsNone(result["observed_entry_price"])

    def test_09_stale_observation_blocks(self):
        result = evaluate([
            quote("s", at(9, 1), 999, 998, 999.5, data_freshness="STALE"),
        ])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("STALE", result["reasons"])
        self.assertFalse(result["estimated_fill"])

    def test_10_future_observation_is_not_used(self):
        future = quote("later", at(10, 5), 1021, 1020, 1022)
        result = evaluate([
            quote("entry", at(9, 1), 999, 998, 999.5),
            future,
        ])
        self.assertEqual(result["state"], "ENTRY_OBSERVED")
        self.assertIsNone(result["exit_reason"])
        self.assertEqual(result["lookahead_excluded_event_ids"], ["later"])
        self.assertNotEqual(result["state"], "CLOSED")

    def test_11_duplicate_event_blocks(self):
        first = quote("same", at(9, 1), 999, 998, 999.5)
        second = quote("same", at(9, 2), 1021, 1020, 1022)
        result = evaluate([first, second])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("DUPLICATE_EVENT", result["reasons"])
        self.assertIsNone(result["verified_net_pnl_yen"])

    def test_12_timestamp_inconsistency_blocks(self):
        broken = quote("bad", at(9, 5), 999, 998, 999.5, available_at=at(9, 4))
        result = evaluate([broken])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("TIMESTAMP_INCONSISTENT", result["reasons"])
        tied = evaluate([
            quote("a", at(9, 1), 999, 998, 999.5),
            quote("b", at(9, 1), 1021, 1020, 1022),
        ])
        self.assertEqual(tied["state"], "BLOCKED")
        self.assertIn("TIMESTAMP_TIE_ORDER_UNKNOWN", tied["reasons"])

    def test_13_abnormal_price_and_volume_block(self):
        price = evaluate([
            bar("bad-price", at(9, 1), 110, 90),
        ])
        self.assertEqual(price["state"], "BLOCKED")
        self.assertIn("ABNORMAL_PRICE", price["reasons"])
        volume = evaluate([
            quote("bad-volume", at(9, 1), 999, 998, 999.5, ask_qty=-5),
        ])
        self.assertEqual(volume["state"], "BLOCKED")
        self.assertIn("ABNORMAL_VOLUME", volume["reasons"])

    def test_14_unverified_zero_cost_is_not_a_verified_close(self):
        path = [
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e3", at(9, 3), 1021, 1020, 1022),
        ]
        unverified = evaluate(path, cost={"fees_yen": 0, "slippage_yen": 0})
        self.assertEqual(unverified["state"], "EXIT_OBSERVED")
        self.assertEqual(unverified["reasons"], ["COST_UNVERIFIED"])
        self.assertEqual(unverified["cost_status"], "UNVERIFIED")
        self.assertIsNone(unverified["fees_yen"])
        self.assertIsNone(unverified["slippage_yen"])
        self.assertIsNone(unverified["verified_net_pnl_yen"])
        self.assertIsNone(unverified["model_net_pnl_yen"])
        modeled = evaluate(path, cost={
            "status": "MODEL",
            "fees_yen": 55,
            "slippage_yen": 10,
            "model_version": "cost-model-test-0",
            "assumptions": "flat schedule, not a broker invoice",
            "evidence_ref": "model-card-test-0",
        })
        self.assertEqual(modeled["state"], "EXIT_OBSERVED")
        self.assertEqual(modeled["reasons"], ["COST_MODEL_NOT_VERIFIED_NET"])
        self.assertEqual(modeled["model_net_pnl_yen"], 1935)
        self.assertIsNone(modeled["verified_net_pnl_yen"])
        self.assertEqual(modeled["cost_model_version"], "cost-model-test-0")

    def test_15_long_and_short_are_separate_results(self):
        long_result = evaluate([
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e3", at(9, 3), 1021, 1020, 1022),
        ])
        short_signal = signal(
            strategy_id="day_short_mvp",
            side="SHORT",
            entry=1000,
            stop=1010,
            target=980,
            sample_role="TEST",
            provenance="synthetic-short",
        )
        short_result = evaluate(
            [
                quote("s1", at(9, 1), 1001, 1000, 1002),
                quote("s2", at(9, 3), 979, 978, 980),
            ],
            signal=short_signal,
        )
        self.assertEqual(long_result["side"], "LONG")
        self.assertEqual(long_result["state"], "CLOSED")
        self.assertEqual(long_result["verified_net_pnl_yen"], 1935)
        self.assertEqual(short_result["side"], "SHORT")
        self.assertEqual(short_result["state"], "CLOSED")
        self.assertEqual(short_result["observed_entry_price"], 1000)
        self.assertEqual(short_result["observed_exit_price"], 980)
        self.assertEqual(short_result["exit_reason"], "TARGET")
        self.assertEqual(short_result["verified_net_pnl_yen"], 1935)
        mixed = summarize_cohort([long_result, short_result])
        self.assertTrue(mixed["mixed_cohort"])
        self.assertIsNone(mixed["profit_factor"])
        self.assertIsNone(mixed["expectancy_yen"])

    def test_16_train_test_shadow_are_not_blended(self):
        path = [
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e3", at(9, 3), 1021, 1020, 1022),
        ]
        rows = [
            evaluate(path, signal=signal(sample_role=role, provenance=role))
            for role in ("TRAIN", "TEST", "SHADOW")
        ]
        self.assertEqual([row["state"] for row in rows], ["CLOSED", "CLOSED", "CLOSED"])
        summary = summarize_cohort(rows)
        self.assertTrue(summary["mixed_cohort"])
        self.assertIn("MIXED_COHORT", summary["reasons"])
        self.assertIsNone(summary["profit_factor"])
        self.assertIsNone(summary["expectancy_yen"])
        self.assertIsNone(summary["max_drawdown_yen"])
        self.assertEqual(summary["observed_eligible_n"], 0)
        self.assertEqual(summary["synthetic_n"], 3)
        self.assertFalse(summary["statistical_edge_confirmed"])

    def test_17_real_lane_is_not_accepted_as_virtual_close(self):
        real_role = evaluate(
            [quote("e1", at(9, 1), 999, 998, 999.5)],
            signal=signal(sample_role="REAL"),
        )
        self.assertEqual(real_role["state"], "BLOCKED")
        self.assertIn("REAL_LANE_NOT_VIRTUAL_AUDIT", real_role["reasons"])
        broker = evaluate([
            quote("broker", at(9, 1), 999, 998, 999.5, source="BROKER_EXECUTION_EXPORT"),
        ])
        self.assertEqual(broker["state"], "BLOCKED")
        self.assertIn("REAL_SOURCE_NOT_ACCEPTED_IN_VIRTUAL_AUDIT", broker["reasons"])
        self.assertFalse(broker["real_fill"])
        daily = evaluate([
            {
                "event_id": "day",
                "source": "DAILY_OHLC",
                "symbol": "285A",
                "kind": "DAILY_RANGE",
                "event_time": at(9, 0),
                "available_at": at(15, 0),
                "high": 1030,
                "low": 970,
                "close": 1010,
                "data_freshness": "OK",
                "suspected_gap": False,
                "session": "OPENING_09",
            },
        ], as_of=at(15, 30))
        self.assertEqual(daily["state"], "BLOCKED")
        self.assertEqual(daily["reasons"], ["DAILY_RANGE_CANNOT_PROVE_SEQUENCE"])
        self.assertIsNone(daily["observed_entry_price"])
        self.assertIsNone(daily["mfe_per_share"])

    def test_18_same_inputs_repeat_the_same_result(self):
        observations = [
            quote("e3", at(9, 3), 1021, 1020, 1022),
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e2", at(9, 2), 1010, 1009, 1011),
        ]
        first = evaluate(observations)
        second = evaluate(list(reversed(observations)))
        self.assertEqual(first, second)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_19_existing_263_history_bytes_stay_unchanged(self):
        path = ROOT / "paper_trade_history.json"
        before = path.read_bytes()
        self.assertEqual(len(json.loads(before.decode("utf-8"))), 263)
        evaluate([
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e3", at(9, 3), 1021, 1020, 1022),
        ])
        scan = scan_public_evidence(ROOT)
        after = path.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(hashlib.sha256(after).hexdigest(), scan["paper_history_sha256"])
        self.assertEqual(scan["paper_history_n"], 263)
        self.assertEqual(scan["paper_history_admissible_n"], 0)
        self.assertEqual(scan["observed_eligible_n"], 0)
        self.assertEqual(scan["tick_log_files"], [])
        self.assertEqual(scan["bar_15s_files"], [])
        self.assertFalse(scan["recorded_producer_supports_closed_virtual_fill"])
        self.assertEqual(scan["five_minute_block_reason"], "YFINANCE_5M_NOT_A_PRICE_PATH")
        reasons = {row["producer_id"]: row["block_reason"] for row in scan["producers"]}
        self.assertEqual(reasons["morning_review.audit_one"], "DAILY_RANGE_CANNOT_PROVE_SEQUENCE")
        self.assertEqual(reasons["ms2_live/Resample_Kioxia_Ticks_15s.ps1"], "BAR_15S_INTRABAR_ORDER_UNKNOWN")
        self.assertIsNone(reasons["shadow_fill_model.evaluate_limit_fill"])

    def test_20_real_submit_request_stays_refused(self):
        result = evaluate(
            [quote("e1", at(9, 1), 999, 998, 999.5), quote("e3", at(9, 3), 1021, 1020, 1022)],
            signal=signal(real_submit_allowed=True, promotion_eligible=True, statistical_edge_confirmed=True),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("REAL_SUBMIT_REQUEST_REJECTED", result["reasons"])
        self.assertFalse(result["real_submit_allowed"])
        self.assertFalse(result["promotion_eligible"])
        self.assertFalse(result["statistical_edge_confirmed"])
        source = (ROOT / "scripts" / "timeseries_fill_audit.py").read_text(encoding="utf-8")
        self.assertNotIn("RssOrder", source)
        self.assertNotIn("real_submit_allowed = True", source)

    def test_data_gap_between_declared_bars_blocks(self):
        result = evaluate(
            [
                bar("b1", at(9, 0, 0), 999, 1001),
                bar("b2", at(9, 0, 30), 998, 1002),
            ],
            expected_bar_seconds=15,
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reasons"], ["DATA_GAP"])

    def test_touch_without_trade_through_is_eligible_not_filled(self):
        result = evaluate([
            quote("touch", at(9, 1), 1000, 999, 1000),
        ])
        self.assertEqual(result["state"], "ENTRY_ELIGIBLE")
        self.assertEqual(result["reasons"], ["TOUCH_ONLY"])
        self.assertFalse(result["estimated_fill"])
        self.assertIsNone(result["observed_entry_price"])

    def test_print_without_book_cannot_become_observed_fill(self):
        result = evaluate([
            {
                "event_id": "print",
                "source": "SYNTHETIC_PRINT",
                "symbol": "285A",
                "kind": "ORDERED_PRINT",
                "event_time": at(9, 1),
                "available_at": at(9, 1),
                "price": 999,
                "volume": 100,
                "data_freshness": "OK",
                "suspected_gap": False,
                "session": "OPENING_09",
            },
        ])
        self.assertEqual(result["state"], "ENTRY_ELIGIBLE")
        self.assertEqual(result["reasons"], ["FILL_MODEL_INPUT_INCOMPLETE"])
        self.assertFalse(result["estimated_fill"])
        self.assertFalse(result["real_fill"])

    def test_synthetic_cohort_is_not_counted_as_observed(self):
        row = evaluate([
            quote("e1", at(9, 1), 999, 998, 999.5),
            quote("e3", at(9, 3), 1021, 1020, 1022),
        ])
        summary = summarize_cohort([row])
        self.assertFalse(summary["mixed_cohort"])
        self.assertEqual(summary["observed_eligible_n"], 0)
        self.assertEqual(summary["synthetic_n"], 1)
        self.assertEqual(summary["expectancy_yen"], 1935)
        self.assertIsNone(summary["profit_factor"])
        self.assertEqual(summary["max_drawdown_yen"], 0)
        self.assertFalse(summary["statistical_edge_confirmed"])
        self.assertFalse(summary["promotion_eligible"])
        self.assertFalse(summary["real_submit_allowed"])

    def test_basis_available_after_the_signal_is_rejected(self):
        late = quote("basis", at(9, 30), 1000, 999, 1001)
        result = evaluate(
            [late],
            signal=signal(basis_event_ids=["basis"], signal_known_at=at(9, 0)),
        )
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reasons"], ["SIGNAL_BASIS_NOT_KNOWN_AT_SIGNAL"])


if __name__ == "__main__":
    unittest.main()
