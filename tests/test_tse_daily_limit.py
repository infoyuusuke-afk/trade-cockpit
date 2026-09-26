import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "dl",
    Path(__file__).parents[1] / "scripts" / "tse_daily_limit.py",
)
dl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dl)


class TSEDailyLimitTests(unittest.TestCase):
    def test_normal_width_boundaries(self):
        self.assertEqual(dl.normal_limit_width(99), 30)
        self.assertEqual(dl.normal_limit_width(100), 50)
        self.assertEqual(dl.normal_limit_width(199), 50)
        self.assertEqual(dl.normal_limit_width(200), 80)
        self.assertEqual(dl.normal_limit_width(499), 80)
        self.assertEqual(dl.normal_limit_width(500), 100)
        self.assertEqual(dl.normal_limit_width(999), 150)
        self.assertEqual(dl.normal_limit_width(1000), 300)
        self.assertEqual(dl.normal_limit_width(50_000_000), 10_000_000)

    def test_normal_limit_prices(self):
        limits = dl.daily_limit_prices(735)
        self.assertEqual(limits["upper_limit"], 885)
        self.assertEqual(limits["lower_limit"], 585)
        self.assertFalse(limits["expanded_upper"])
        self.assertFalse(limits["expanded_lower"])

    def test_lower_limit_floors_at_one_yen(self):
        limits = dl.daily_limit_prices(15)
        self.assertEqual(limits["lower_limit"], 1)

    def test_normal_table_hit_requires_expansion_check_when_unverified(self):
        result = dl.detect_limit_event(
            base_price=735,
            high=885,
            low=700,
            close=885,
            official_override_checked=False,
        )
        self.assertEqual(result["event_state"], "POTENTIAL_LIMIT_UP")
        self.assertEqual(result["verification_status"], "EXPANSION_CHECK_REQUIRED")

    def test_confirmed_normal_limit_up(self):
        result = dl.detect_limit_event(
            base_price=735,
            high=885,
            low=700,
            close=885,
            official_override_checked=True,
        )
        self.assertEqual(result["event_state"], "LIMIT_UP")
        self.assertEqual(result["verification_status"], "NORMAL_LIMIT_CONFIRMED")

    def test_expanded_upper_override(self):
        # Example shape: base 735 with officially broadened upper width 600.
        result = dl.detect_limit_event(
            base_price=735,
            high=1335,
            low=735,
            close=1335,
            upper_width_override=600,
            official_override_checked=True,
        )
        self.assertTrue(result["expanded_upper"])
        self.assertEqual(result["upper_limit"], 1335)
        self.assertEqual(result["lower_limit"], 585)
        self.assertEqual(result["event_state"], "LIMIT_UP")
        self.assertEqual(result["verification_status"], "OFFICIAL_OVERRIDE_APPLIED")

    def test_expanded_lower_override(self):
        result = dl.detect_limit_event(
            base_price=239,
            high=250,
            low=1,
            close=1,
            lower_width_override=320,
            official_override_checked=True,
        )
        self.assertTrue(result["expanded_lower"])
        self.assertEqual(result["lower_limit"], 1)
        self.assertEqual(result["event_state"], "LIMIT_DOWN")

    def test_intraday_touch_is_distinct_from_close_at_limit(self):
        result = dl.detect_limit_event(
            base_price=1000,
            high=1300,
            low=1000,
            close=1200,
            official_override_checked=True,
        )
        self.assertEqual(result["event_state"], "LIMIT_UP_TOUCH")
        self.assertTrue(result["touched_upper"])
        self.assertFalse(result["closed_upper"])

    def test_no_limit_event(self):
        result = dl.detect_limit_event(
            base_price=1000,
            high=1200,
            low=900,
            close=1100,
            official_override_checked=True,
        )
        self.assertEqual(result["event_state"], "NONE")
        self.assertEqual(result["verification_status"], "NO_LIMIT_EVENT")

    def test_invalid_base_rejected(self):
        with self.assertRaises(ValueError):
            dl.normal_limit_width(0)


if __name__ == "__main__":
    unittest.main()
