import unittest
from datetime import datetime, timezone, timedelta

from scripts.world_market import market_session_state, narration_availability


JST = timezone(timedelta(hours=9))


class MarketSessionStateTest(unittest.TestCase):
    def test_us_cash_previous_session_is_known_at_1500_jst(self):
        now = datetime(2026, 9, 24, 15, 0, tzinfo=JST)
        self.assertEqual(market_session_state("us_close", now), "CLOSED_KNOWN")
        row = {"verified": False, "session_state": "CLOSED_KNOWN"}
        self.assertEqual(narration_availability(row), "EXPECTED_INACTIVE")

    def test_tse_lunch_break_is_expected_inactive_not_invalid(self):
        now = datetime(2026, 9, 24, 12, 0, tzinfo=JST)
        self.assertEqual(market_session_state("japan", now), "BREAK")
        row = {"verified": False, "session_state": "BREAK"}
        self.assertEqual(narration_availability(row), "EXPECTED_INACTIVE")

    def test_missing_open_feed_is_invalid(self):
        row = {"verified": False, "session_state": "OPEN"}
        self.assertEqual(narration_availability(row), "DATA_INVALID")


if __name__ == "__main__":
    unittest.main()
