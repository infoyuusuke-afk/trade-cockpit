import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 6, 9, 20, tzinfo=JST)


def _load():
    spec = importlib.util.spec_from_file_location("decision_input_value", ROOT / "scripts" / "decision_input_value.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = _load()


def _row(**overrides):
    row = {
        "ticker": "285A.T",
        "signal": "買いサイン",
        "strategy": "OR15追随",
        "price": 19120.0,
        "entry_price": 19120.0,
        "stop_price": 19000.0,
        "data": "LIVE",
        "credit_buy": 1000.0,
        "credit_sell": 200.0,
        "credit_ratio": 5.0,
        "credit_ratio_observed_at": NOW,
    }
    row.update(overrides)
    return row


class AuditTests(unittest.TestCase):
    def test_live_rule_grades_match_the_code_path(self):
        self.assertEqual(audit.grade_of("or15"), "A")
        self.assertEqual(audit.grade_of("vwap"), "A")
        self.assertEqual(audit.grade_of("ema9_20"), "A")
        self.assertEqual(audit.grade_of("volume_acceleration"), "A")
        self.assertEqual(audit.grade_of("tape"), "A")
        self.assertEqual(audit.grade_of("over_under"), "A")
        self.assertEqual(audit.grade_of("time_band"), "A")
        self.assertEqual(audit.grade_of("market_breadth"), "A")
        self.assertEqual(audit.grade_of("investor_futures_flow"), "A")
        self.assertEqual(audit.grade_of("credit_ratio"), "B")
        self.assertEqual(audit.grade_of("margin_buy_balance"), "B")
        self.assertEqual(audit.grade_of("margin_sell_balance"), "B")
        self.assertEqual(audit.grade_of("tdnet_material"), "B")
        self.assertEqual(audit.grade_of("usdjpy"), "C")
        self.assertEqual(audit.grade_of("us_index_sox"), "C")
        self.assertEqual(audit.grade_of("earnings_estimates"), "C")
        self.assertEqual(audit.grade_of("sq_calendar"), "C")
        self.assertEqual(audit.grade_of("bollinger"), "D")
        self.assertEqual(audit.grade_of("or10"), "D")
        self.assertEqual(audit.grade_of("credit_evaluation_loss"), "D")
        self.assertEqual(audit.grade_of("short_sale_ratio"), "D")
        self.assertEqual(audit.grade_of("put_call"), "D")
        self.assertEqual(audit.grade_of("implied_vol"), "D")
        self.assertEqual(audit.grade_of("silver"), "D")
        self.assertEqual(audit.grade_of("korea_equity"), "D")
        self.assertEqual(audit.grade_of("shikiho_midplan"), "D")

    def test_engine_is_a_fixed_rule(self):
        verdict = audit.engine_verdict()
        self.assertEqual(verdict["engine"], "FIXED_RULE")
        self.assertFalse(verdict["statistical_expectancy"])
        self.assertFalse(verdict["strategy_competition"])
        self.assertFalse(verdict["real_submit_allowed"])

    def test_credit_on_the_row_does_not_change_the_live_side(self):
        rich = _row(credit_ratio=8.0)
        bare = _row()
        del bare["credit_buy"]
        del bare["credit_sell"]
        del bare["credit_ratio"]
        del bare["credit_ratio_observed_at"]
        self.assertEqual(audit.live_side(rich), "LONG")
        self.assertEqual(audit.live_side(bare), "LONG")
        self.assertEqual(audit.live_side(_row(signal="市場時間外")), "NO_TRADE")

    def test_unstamped_or_future_credit_is_not_a_measurement(self):
        unstamped = audit.information_value_record(_row(credit_ratio_observed_at=None), realized_pnl_per_share=40.0, decided_at=NOW)
        self.assertEqual(unstamped["measurement_status"], "UNSTAMPED")
        self.assertEqual(unstamped["credit_ratio_bin"], "")
        self.assertIsNone(unstamped["ev_if_credit_used"])
        future = audit.information_value_record(
            _row(credit_ratio_observed_at=NOW + timedelta(minutes=5)),
            realized_pnl_per_share=40.0,
            decided_at=NOW,
        )
        self.assertEqual(future["measurement_status"], "LOOKAHEAD_EXCLUDED")
        self.assertFalse(future["real_submit_allowed"])

    def test_stamped_credit_records_the_bin_and_leaves_the_rule_unchanged(self):
        record = audit.information_value_record(_row(), realized_pnl_per_share=40.0, decided_at=NOW)
        self.assertEqual(record["live_side"], "LONG")
        self.assertEqual(record["baseline_ev_yen_per_share"], 40.0)
        self.assertEqual(record["ev_if_credit_removed"], 40.0)
        self.assertIsNone(record["ev_if_credit_used"])
        self.assertEqual(record["credit_ratio_bin"], "HIGH")
        self.assertEqual(record["measurement_status"], "UNMEASURED_NOT_IN_LIVE_RULE")
        self.assertEqual(record["acceptance_class"], "input_value_observation")
        low = audit.information_value_record(_row(credit_ratio=2.0), realized_pnl_per_share=-10.0, decided_at=NOW)
        self.assertEqual(low["credit_ratio_bin"], "LOW")

    def test_small_sample_does_not_invent_an_expectancy_edge(self):
        records = [
            audit.information_value_record(_row(credit_ratio=5.0), realized_pnl_per_share=40.0, decided_at=NOW),
            audit.information_value_record(_row(credit_ratio=1.0), realized_pnl_per_share=-10.0, decided_at=NOW),
        ]
        summary = audit.summarize_credit_ratio(records)
        self.assertEqual(summary["measurement_status"], "INSUFFICIENT_SAMPLE")
        self.assertIsNone(summary["delta_ev_yen_per_share"])
        self.assertEqual(summary["live_roundtrip"], "NOT_RUN/INPUT_VALUE_OBSERVATION")
        self.assertNotIn("PASS", summary["live_roundtrip"])

    def test_eight_trades_per_bin_report_an_observational_difference_only(self):
        records = []
        for _ in range(8):
            records.append(audit.information_value_record(_row(credit_ratio=5.0), realized_pnl_per_share=40.0, decided_at=NOW))
            records.append(audit.information_value_record(_row(credit_ratio=1.0), realized_pnl_per_share=10.0, decided_at=NOW))
        summary = audit.summarize_credit_ratio(records)
        self.assertEqual(summary["measurement_status"], "OBSERVATIONAL_ASSOCIATION")
        self.assertEqual(summary["delta_ev_yen_per_share"], 30.0)
        self.assertEqual(summary["live_roundtrip"], "NOT_RUN/INPUT_VALUE_OBSERVATION")
        self.assertFalse(summary["real_submit_allowed"])

    def test_roadmap_puts_measurement_before_new_feeds(self):
        order = audit.roadmap()
        self.assertEqual(order[0], "marginal_ev_ledger")
        self.assertLess(order.index("credit_already_on_the_live_row"), order.index("prior_close_us_semiconductor"))
        self.assertLess(order.index("earnings_event_veto"), order.index("options_cross_asset_fundamentals"))

    def test_module_does_not_submit_or_loosen_the_live_rule(self):
        text = (ROOT / "scripts" / "decision_input_value.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("shadow_execution", text)
        self.assertNotIn("real_submit_allowed = True", text)
        self.assertNotIn('real_submit_allowed"] = True', text)
