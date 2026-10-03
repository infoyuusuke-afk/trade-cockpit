import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "kc",
    Path(__file__).parents[1] / "scripts" / "kioxia_forecast_calibration.py",
)
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)


class KioxiaForecastCalibrationTests(unittest.TestCase):
    def test_wilson_interval_matches_small_sample_uncertainty(self):
        low, high = kc.wilson_interval(10, 11)
        self.assertAlmostEqual(low, 62.26, places=1)
        self.assertAlmostEqual(high, 98.38, places=1)

    def test_missing_outcomes_are_not_counted_as_misses(self):
        records = [
            {"direction_hit": True, "actual_close_ret": 1.2, "absolute_error": 0.2},
            {"direction_hit": None, "actual_close_ret": None},
        ]
        summary = kc.summarize_history(records, min_sample=2)
        self.assertEqual(summary["sample_n"], 1)
        self.assertEqual(summary["direction_hits"], 1)
        self.assertEqual(summary["confidence_status"], "INSUFFICIENT_SAMPLE")

    def test_small_sample_hides_today_confidence(self):
        records = [
            {"direction_hit": True, "actual_close_ret": 1.0}
            for _ in range(10)
        ] + [
            {"direction_hit": False, "actual_close_ret": -1.0}
        ]
        summary = kc.summarize_history(records, min_sample=20)
        result = kc.display_confidence(
            selected_scenario_probability_pct=72.0,
            history_summary=summary,
        )
        self.assertIsNone(result["confidence_pct"])
        self.assertEqual(result["confidence_status"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(result["sample_n"], 11)

    def test_ready_sample_uses_model_probability_not_historical_hit_rate(self):
        records = [
            {"direction_hit": True, "actual_close_ret": 1.0}
            for _ in range(16)
        ] + [
            {"direction_hit": False, "actual_close_ret": -1.0}
            for _ in range(4)
        ]
        summary = kc.summarize_history(records, min_sample=20)
        self.assertEqual(summary["direction_hit_rate_pct"], 80.0)
        result = kc.display_confidence(
            selected_scenario_probability_pct=63.0,
            history_summary=summary,
        )
        self.assertEqual(result["confidence_pct"], 63.0)
        self.assertEqual(result["historical_hit_rate_pct"], 80.0)
        self.assertEqual(result["confidence_status"], "CALIBRATED")

    def test_scenario_probabilities_validate(self):
        result = kc.validate_scenario_probabilities([
            {"scenario": "YORITEN", "probability_pct": 62},
            {"scenario": "GU_CONTINUATION", "probability_pct": 24},
            {"scenario": "RANGE", "probability_pct": 14},
        ])
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["sum_pct"], 100.0)

    def test_probability_sum_is_not_silently_normalized(self):
        result = kc.validate_scenario_probabilities([
            {"scenario": "YORITEN", "probability_pct": 62},
            {"scenario": "RANGE", "probability_pct": 20},
        ])
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "SUM_NOT_100")
        self.assertAlmostEqual(result["sum_pct"], 82.0)

    def test_duplicate_scenario_is_rejected(self):
        result = kc.validate_scenario_probabilities([
            {"scenario": "RANGE", "probability_pct": 50},
            {"scenario": "RANGE", "probability_pct": 50},
        ])
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "DUPLICATE_SCENARIO")

    def test_unknown_scenario_is_rejected(self):
        result = kc.validate_scenario_probabilities([
            {"scenario": "MAGIC_UP", "probability_pct": 100},
        ])
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "UNKNOWN_SCENARIO")

    def test_invalid_model_output_is_not_displayed(self):
        summary = {
            "confidence_status": "CALIBRATION_READY",
            "sample_n": 30,
            "direction_hit_rate_pct": 60.0,
            "wilson_95_low_pct": 42.0,
            "wilson_95_high_pct": 75.0,
        }
        result = kc.display_confidence(
            selected_scenario_probability_pct=140,
            history_summary=summary,
        )
        self.assertIsNone(result["confidence_pct"])
        self.assertEqual(result["confidence_status"], "INVALID_MODEL_OUTPUT")


if __name__ == "__main__":
    unittest.main()
