import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from scripts.semiconductor_gu_continuation import (
    FIXED_UNIVERSE,
    build_panel,
    classify_gap,
    evaluate_no_pullback_lane,
    evaluate_symbol,
    evaluate_universe,
    load_universe,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 24, 9, 20, 0, tzinfo=JST)


def fresh(**overrides):
    rec = {
        "updated_at": NOW.isoformat(),
        "price": 1050.0,
        "open": 1030.0,
        "prev_close": 1000.0,
        "vwap": 1040.0,
        "ema9": 1045.0,
        "ema20": 1030.0,
        "or5_high": 1045.0,
        "or5_low": 1032.0,
        "volume_burst": 2.0,
        "flow_bias": 12.0,
    }
    rec.update(overrides)
    return rec


class GapClassificationTests(unittest.TestCase):
    def test_gap_up_buckets(self):
        from scripts.semiconductor_gu_continuation import DEFAULT_CONFIG
        self.assertEqual(classify_gap(1005, 1000, DEFAULT_CONFIG)["bucket"], "GU_SMALL")
        self.assertEqual(classify_gap(1020, 1000, DEFAULT_CONFIG)["bucket"], "GU_MEDIUM")
        self.assertEqual(classify_gap(1040, 1000, DEFAULT_CONFIG)["bucket"], "GU_LARGE")

    def test_gap_down_and_flat_and_missing(self):
        from scripts.semiconductor_gu_continuation import DEFAULT_CONFIG
        self.assertEqual(classify_gap(990, 1000, DEFAULT_CONFIG)["bucket"], "GD")
        self.assertEqual(classify_gap(1000, 1000, DEFAULT_CONFIG)["bucket"], "FLAT")
        self.assertIsNone(classify_gap(None, 1000, DEFAULT_CONFIG)["bucket"])


class SymbolStateMachineTests(unittest.TestCase):
    # 1. fresh strong-GU continuation path
    def test_fresh_strong_gu_continuation(self):
        r = evaluate_symbol("285A", fresh(), NOW)
        self.assertEqual(r["state"], "GU_CONTINUATION_CANDIDATE")
        self.assertFalse(r["fail_closed"])
        self.assertEqual(r["gap_bucket"], "GU_LARGE")

    # 2. GU then VWAP/open loss => warning/invalidation
    def test_gu_then_vwap_and_open_loss_is_warning(self):
        r = evaluate_symbol("6857", fresh(price=1025, vwap=1040, open=1030,
                                            or5_high=1045, or5_low=1020), NOW)
        self.assertEqual(r["state"], "GU_EXHAUSTION_WARNING")
        self.assertIn("lost_vwap", r["evidence"])
        self.assertIn("lost_open", r["evidence"])

    def test_gu_then_full_structural_break_is_invalidated(self):
        r = evaluate_symbol("6857", fresh(price=1020, vwap=1040, open=1030,
                                            or5_high=1045, or5_low=1032), NOW)
        self.assertEqual(r["state"], "LONG_INVALIDATED")
        self.assertIn("broke_or5_low", r["evidence"])

    # 3. OR5 incomplete => no OR5-breakout claim
    def test_or5_incomplete_makes_no_breakout_claim(self):
        r = evaluate_symbol("8035", fresh(or5_high=None, or5_low=None), NOW)
        self.assertEqual(r["or5"]["state"], "FORMING")
        self.assertIsNone(r["or5"]["price_vs_high"])
        self.assertEqual(r["state"], "OR5_FORMING")
        self.assertNotIn("or15_breakout", " ".join(r["evidence"]))

    # 4. OR15 incomplete => no OR15-confirmation claim
    def test_or15_incomplete_makes_no_confirmation_claim(self):
        r = evaluate_symbol("6146", fresh(or15_high=None, or15_low=None), NOW)
        self.assertEqual(r["or15"]["state"], "FORMING")
        self.assertNotEqual(r["state"], "OR15_CONFIRMATION")

    def test_or15_complete_yields_confirmation_state(self):
        r = evaluate_symbol("6146", fresh(or15_high=1048, or15_low=1035, price=1050), NOW)
        self.assertEqual(r["state"], "OR15_CONFIRMATION")
        self.assertEqual(r["or15"]["breakout"], "ABOVE")

    # 5. stale data => WAIT_DATA
    def test_stale_data_fails_closed_to_wait_data(self):
        old = NOW - timedelta(seconds=300)
        r = evaluate_symbol("6920", fresh(updated_at=old.isoformat()), NOW)
        self.assertEqual(r["state"], "WAIT_DATA")
        self.assertTrue(r["fail_closed"])
        self.assertEqual(r["fail_reason"], "STALE_DATA")

    def test_explicit_stale_flag_fails_closed(self):
        r = evaluate_symbol("6920", fresh(stale=True), NOW)
        self.assertEqual(r["state"], "WAIT_DATA")
        self.assertTrue(r["fail_closed"])

    # 6. missing flow/board field => no inferred flow
    def test_missing_flow_field_is_not_inferred(self):
        r = evaluate_symbol("285A", fresh(flow_bias=None), NOW)
        self.assertIsNone(r["flow_state"])
        self.assertEqual(r["state"], "GU_CONTINUATION_CANDIDATE")

    # 9. same input => same output (determinism)
    def test_deterministic_same_input_same_output(self):
        rec = fresh()
        r1 = evaluate_symbol("285A", copy.deepcopy(rec), NOW)
        r2 = evaluate_symbol("285A", copy.deepcopy(rec), NOW)
        self.assertEqual(json.dumps(r1, sort_keys=True), json.dumps(r2, sort_keys=True))

    # 10. future timestamp / lookahead input => fail closed
    def test_future_timestamp_fails_closed(self):
        future = NOW + timedelta(seconds=120)
        r = evaluate_symbol("285A", fresh(updated_at=future.isoformat()), NOW)
        self.assertTrue(r["fail_closed"])
        self.assertEqual(r["fail_reason"], "FUTURE_TIMESTAMP")
        self.assertNotIn(r["state"], ("GU_CONTINUATION_CANDIDATE", "OR15_CONFIRMATION", "PULLBACK_RECLAIM_CANDIDATE"))

    def test_missing_timestamp_fails_closed(self):
        r = evaluate_symbol("285A", fresh(updated_at=None), NOW)
        self.assertTrue(r["fail_closed"])
        self.assertEqual(r["fail_reason"], "MISSING_TIMESTAMP")

    def test_no_gap_up_is_unknown_not_a_candidate(self):
        r = evaluate_symbol("285A", fresh(open=995, prev_close=1000), NOW)
        self.assertEqual(r["state"], "UNKNOWN")
        self.assertEqual(r["fail_reason"], "NOT_A_GAP_UP")

    def test_preopen_indicative_quote_only(self):
        r = evaluate_symbol("285A", fresh(price=None, or5_high=None, or5_low=None), NOW)
        self.assertEqual(r["state"], "PREOPEN_GU_WATCH")

    def test_pullback_reclaim_candidate(self):
        r = evaluate_symbol("285A", fresh(price=1036, vwap=1034, open=1030,
                                            or5_high=1045, or5_low=1032), NOW)
        self.assertEqual(r["state"], "PULLBACK_RECLAIM_CANDIDATE")


class BreadthAndSummaryTests(unittest.TestCase):
    # 7. mixed semiconductor breadth => MIXED
    def test_mixed_breadth_yields_mixed_summary(self):
        records = {
            "285A": fresh(),
            "6857": fresh(),
            "8035": fresh(price=1025, vwap=1040, open=1030, or5_high=1045, or5_low=1020),
            "6146": fresh(price=1036, vwap=1034, open=1030, or5_high=1045, or5_low=1032),
            "6920": fresh(price=1036, vwap=1034, open=1030, or5_high=1045, or5_low=1032),
        }
        panel = build_panel(records, NOW)
        self.assertEqual(panel["summary"], "MIXED")

    # 8. all/most names stale => WAIT_DATA
    def test_all_stale_yields_wait_data_summary(self):
        old = (NOW - timedelta(seconds=300)).isoformat()
        records = {code: fresh(updated_at=old) for code in FIXED_UNIVERSE}
        panel = build_panel(records, NOW)
        self.assertEqual(panel["summary"], "WAIT_DATA")
        self.assertEqual(panel["breadth"]["stale_n"], 5)

    def test_strong_continuation_breadth_bias(self):
        records = {code: fresh() for code in FIXED_UNIVERSE}
        panel = build_panel(records, NOW)
        self.assertEqual(panel["summary"], "CONTINUATION_BIAS")
        self.assertEqual(panel["breadth"]["above_open_n"], 5)

    def test_missing_symbol_record_is_wait_data_not_crash(self):
        records = {"285A": fresh()}
        panel = build_panel(records, NOW)
        codes = {s["code"]: s for s in panel["symbols"]}
        self.assertEqual(codes["6920"]["state"], "WAIT_DATA")


class MacroPassthroughTests(unittest.TestCase):
    def test_missing_macro_is_unknown_not_invented(self):
        panel = build_panel({}, NOW)
        for field in ("nikkei_futures", "sox_nasdaq", "usdjpy", "us_rates", "vix"):
            self.assertEqual(panel["macro"][field]["state"], "UNKNOWN")
            self.assertIsNone(panel["macro"][field]["value"])
        self.assertEqual(panel["macro"]["role"], "regime_modifier_only")

    def test_provided_macro_value_is_passed_through_unmodified(self):
        panel = build_panel({}, NOW, macro={"vix": 18.4})
        self.assertEqual(panel["macro"]["vix"]["value"], 18.4)
        self.assertEqual(panel["macro"]["vix"]["state"], "AVAILABLE")


class NoPullbackLaneTests(unittest.TestCase):
    def test_missed_pullback_flagged_when_never_seen(self):
        h = evaluate_no_pullback_lane("GU_CONTINUATION_CANDIDATE", session_states_seen=["OR5_FORMING"])
        self.assertTrue(h["daytrade_missed_no_pullback"])
        self.assertEqual(h["overnight_state"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(h["swing_state"], "INSUFFICIENT_SAMPLE")

    def test_pullback_seen_clears_missed_flag(self):
        h = evaluate_no_pullback_lane(
            "GU_CONTINUATION_CANDIDATE",
            session_states_seen=["OR5_FORMING", "PULLBACK_RECLAIM_CANDIDATE"],
        )
        self.assertFalse(h["daytrade_missed_no_pullback"])

    def test_invalidation_blocks_overnight_and_swing(self):
        h = evaluate_no_pullback_lane("LONG_INVALIDATED")
        self.assertEqual(h["overnight_state"], "OVERNIGHT_BLOCK")
        self.assertEqual(h["swing_state"], "SWING_BLOCK")

    def test_no_ev_database_never_fabricates_continuation_candidate(self):
        for state in ("PREOPEN_GU_WATCH", "OR5_FORMING", "GU_CONTINUATION_CANDIDATE",
                       "OR15_CONFIRMATION", "WAIT_DATA", "UNKNOWN"):
            h = evaluate_no_pullback_lane(state)
            self.assertNotEqual(h["overnight_state"], "OVERNIGHT_CONTINUATION_CANDIDATE")
            self.assertNotEqual(h["swing_state"], "SWING_CONTINUATION_CANDIDATE")
            self.assertEqual(h["sample_n"], 0)


class UniverseConfigTests(unittest.TestCase):
    def test_default_universe_is_fixed_five(self):
        self.assertEqual(load_universe(None), FIXED_UNIVERSE)
        self.assertEqual(len(FIXED_UNIVERSE), 5)

    def test_missing_config_path_falls_back_to_fixed(self):
        self.assertEqual(load_universe("/nonexistent/path/universe.json"), FIXED_UNIVERSE)

    def test_malformed_config_raises_instead_of_guessing(self, tmp_path=None):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{}")
            path = f.name
        with self.assertRaises(ValueError):
            load_universe(path)

    def test_evaluate_universe_respects_custom_universe(self):
        results = evaluate_universe({"9999": fresh()}, NOW, universe=["9999"])
        self.assertEqual([r["code"] for r in results], ["9999"])


class PanelDeterminismAndSafetyTests(unittest.TestCase):
    def test_panel_is_pure_and_deterministic(self):
        records = {code: fresh() for code in FIXED_UNIVERSE}
        p1 = build_panel(copy.deepcopy(records), NOW, macro={"vix": 15.0})
        p2 = build_panel(copy.deepcopy(records), NOW, macro={"vix": 15.0})
        self.assertEqual(json.dumps(p1, sort_keys=True), json.dumps(p2, sort_keys=True))

    def test_panel_never_sets_auto_execute(self):
        records = {code: fresh() for code in FIXED_UNIVERSE}
        panel = build_panel(records, NOW)
        self.assertFalse(panel["auto_execute"])
        self.assertTrue(panel["research_only"])


if __name__ == "__main__":
    unittest.main()
