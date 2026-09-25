import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('ss', Path(__file__).parents[1] / 'scripts/strategy_schema.py')
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)


class ClassifyLiquidityBucketTests(unittest.TestCase):
    def test_none_is_unknown(self):
        self.assertEqual(ss.classify_liquidity_bucket(None), "UNKNOWN")

    def test_thresholds(self):
        self.assertEqual(ss.classify_liquidity_bucket(10_000_000_000), "ULTRA_LIQUID")
        self.assertEqual(ss.classify_liquidity_bucket(9_999_999_999), "HIGH_LIQUID")
        self.assertEqual(ss.classify_liquidity_bucket(3_000_000_000), "HIGH_LIQUID")
        self.assertEqual(ss.classify_liquidity_bucket(2_999_999_999), "MID_LIQUID")
        self.assertEqual(ss.classify_liquidity_bucket(500_000_000), "MID_LIQUID")
        self.assertEqual(ss.classify_liquidity_bucket(499_999_999), "LOW_LIQUID")
        self.assertEqual(ss.classify_liquidity_bucket(0), "LOW_LIQUID")


class ClassifySymbolClassTests(unittest.TestCase):
    def test_high_vol_high_turnover(self):
        self.assertEqual(
            ss.classify_symbol_class(turnover=3_000_000_000, atr_pct=3.0),
            "HIGH_VOL_HIGH_TURNOVER",
        )

    def test_below_threshold_is_unclassified(self):
        self.assertEqual(ss.classify_symbol_class(turnover=1_000_000_000, atr_pct=5.0), "UNCLASSIFIED")
        self.assertEqual(ss.classify_symbol_class(turnover=5_000_000_000, atr_pct=1.0), "UNCLASSIFIED")

    def test_missing_data_is_unclassified_not_guessed(self):
        self.assertEqual(ss.classify_symbol_class(turnover=None, atr_pct=None), "UNCLASSIFIED")
        self.assertEqual(ss.classify_symbol_class(turnover=5_000_000_000, atr_pct=None), "UNCLASSIFIED")


class CurrentRegimeTests(unittest.TestCase):
    def test_missing_file_returns_all_none_not_guessed(self):
        result = ss.current_regime(Path("/nonexistent/market_regime.json"))
        self.assertEqual(result, {
            "regime": None, "regime_updated_at": None, "high_vol": None,
            "rate_shock": None, "policy_event": None,
        })

    def test_reads_confirmed_regime_and_flags(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "market_regime.json"
            path.write_text(json.dumps({
                "confirmed_regime": "UP",
                "confirmed_at": "2026-09-17 10:00:00 JST",
                "flags": {"high_vol": True, "rate_shock": False, "policy_event": False},
            }), encoding="utf-8")
            result = ss.current_regime(path)
        self.assertEqual(result["regime"], "UP")
        self.assertEqual(result["regime_updated_at"], "2026-09-17 10:00:00 JST")
        self.assertTrue(result["high_vol"])
        self.assertFalse(result["rate_shock"])


class ExitReasonCodeTests(unittest.TestCase):
    def test_known_results_map_to_codes(self):
        self.assertEqual(ss.exit_reason_code("未発動（見送り）"), "NOT_TRIGGERED")
        self.assertEqual(ss.exit_reason_code("IFO損切り"), "STOP")
        self.assertEqual(ss.exit_reason_code("IFO利確1"), "TARGET1")
        self.assertEqual(ss.exit_reason_code("時点評価・未決済"), "OPEN_MARK")
        self.assertEqual(ss.exit_reason_code("順序不明（成績除外）"), "AMBIGUOUS_EXCLUDED")

    def test_unknown_result_is_unknown_code(self):
        self.assertEqual(ss.exit_reason_code("想定外の文字列"), "UNKNOWN")


class TagRecordTests(unittest.TestCase):
    def test_adds_fields_without_removing_existing(self):
        record = {"name": "テスト", "side": "LONG"}
        tagged = ss.tag_record(
            record, strategy_id="day_ifo_long", signal_time="2026-09-17 08:55:00 JST",
            turnover=5_000_000_000, atr_pct=4.0,
            regime_snapshot={"regime": "UP", "regime_updated_at": "t", "high_vol": False,
                              "rate_shock": False, "policy_event": False},
            source="test",
        )
        self.assertEqual(tagged["name"], "テスト")
        self.assertEqual(tagged["side"], "LONG")
        self.assertEqual(tagged["strategy_id"], "day_ifo_long")
        self.assertEqual(tagged["strategy_version"], "1.0")
        self.assertEqual(tagged["horizon"], "day")
        self.assertEqual(tagged["cockpit_tab"], "ms2-live")
        self.assertEqual(tagged["liquidity_bucket"], "HIGH_LIQUID")
        self.assertEqual(tagged["symbol_class"], "HIGH_VOL_HIGH_TURNOVER")
        self.assertEqual(tagged["regime"], "UP")
        self.assertEqual(tagged["source"], "test")

    def test_does_not_mutate_input_record(self):
        record = {"name": "テスト"}
        ss.tag_record(record, strategy_id="day_ifo_long", signal_time="t")
        self.assertNotIn("strategy_id", record)

    def test_unknown_strategy_id_does_not_silently_pick_a_real_one(self):
        tagged = ss.tag_record({}, strategy_id="not_registered", signal_time="t")
        self.assertEqual(tagged["strategy_version"], "unknown")
        self.assertEqual(tagged["horizon"], "unknown")
        self.assertIsNone(tagged["cockpit_tab"])


if __name__ == "__main__":
    unittest.main()
