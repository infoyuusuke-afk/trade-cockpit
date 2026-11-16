"""OWNER 2026-11-16 「world_market.pyの日本指数の鮮度を1営業日以内に変える…本当に古い値は止めたまま」."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import world_market as wm  # noqa: E402

JST = timezone(timedelta(hours=9))


def at(y, m, d, hh=8, mm=45):
    return datetime(y, m, d, hh, mm, tzinfo=JST)


class JapanIndexOneTradingDay(unittest.TestCase):
    def test_friday_close_on_monday_morning(self):
        self.assertTrue(wm.freshness("11/13", "japan", at(2026, 11, 16))[0])      # Mon 08:45, Fri close

    def test_last_close_after_a_holiday(self):
        self.assertTrue(wm.freshness("11/02", "japan", at(2026, 11, 4))[0])       # Wed after the 11/03 holiday
        self.assertTrue(wm.freshness("11/20", "japan", at(2026, 11, 24))[0])      # Tue after Mon 11/23

    def test_today_and_yesterday_on_an_ordinary_day(self):
        self.assertTrue(wm.freshness("11/17", "japan", at(2026, 11, 18))[0])
        self.assertTrue(wm.freshness("11/18", "japan", at(2026, 11, 18, 15, 40))[0])

    def test_really_old_values_stay_stopped(self):
        self.assertFalse(wm.freshness("11/12", "japan", at(2026, 11, 16))[0])     # Thursday's close on Monday
        self.assertFalse(wm.freshness("11/16", "japan", at(2026, 11, 18))[0])     # two trading days old
        self.assertFalse(wm.freshness("11/02", "japan", at(2026, 11, 5))[0])      # two trading days old across a holiday
        self.assertFalse(wm.freshness("11/19", "japan", at(2026, 11, 18))[0])     # a future date

    def test_other_kinds_unchanged(self):
        self.assertTrue(wm.freshness("11/13", "us_close", at(2026, 11, 16))[0])   # 3 days, within the US limit of 4
        self.assertFalse(wm.freshness("11/13", "realtime", at(2026, 11, 16))[0])  # 1 calendar day as before
        self.assertTrue(wm.freshness("11/15", "realtime", at(2026, 11, 16))[0])

    def test_previous_trading_day(self):
        self.assertEqual(wm.previous_trading_day(at(2026, 11, 16).date()).isoformat(), "2026-11-13")
        self.assertEqual(wm.previous_trading_day(at(2026, 11, 24).date()).isoformat(), "2026-11-20")
        self.assertEqual(wm.previous_trading_day(at(2027, 1, 4).date()).isoformat(), "2026-12-30")


if __name__ == "__main__":
    unittest.main()
