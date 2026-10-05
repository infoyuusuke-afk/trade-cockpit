"""Timezone / DST tests for the baseline publish waves.

JST has no DST, so a fixed JST slot moves by one hour in audience-local time
when London / New York switch clocks. These tests pin that behaviour around the
2026 transitions (US: Mar 8 / Nov 1; EU: Mar 29 / Oct 25).
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from auto_publish.app.config import load_config
from auto_publish.app.errors import SchedulingError
from auto_publish.app.scheduler.slots import compute_slot, wave_window

CFG = load_config()
JST = ZoneInfo("Asia/Tokyo")


def slot(platform, session, now_jst="15:50", taken=frozenset(), day=None):
    d = datetime.fromisoformat(f"{day or session}T{now_jst}:00").replace(tzinfo=JST)
    return compute_slot(platform=platform, platform_cfg=CFG["platforms"][platform], waves_cfg=CFG["waves"],
                        session_date=session, now=d, taken_utc=set(taken), interval_minutes=30, min_lead_minutes=10)


class TestWaves(unittest.TestCase):
    def test_europe_wave_window_including_2400(self):
        start, end = wave_window("2026-09-24", CFG["waves"]["europe"])
        self.assertEqual(start.isoformat(), "2026-09-24T22:00:00+09:00")
        self.assertEqual(end.isoformat(), "2026-09-25T00:00:00+09:00")

    def test_north_america_waves_are_next_day_jst(self):
        s1, e1 = wave_window("2026-09-24", CFG["waves"]["na_tiktok"])
        s2, e2 = wave_window("2026-09-24", CFG["waves"]["na_shorts"])
        self.assertEqual((s1.isoformat(), e1.isoformat()), ("2026-09-25T05:00:00+09:00", "2026-09-25T07:00:00+09:00"))
        self.assertEqual((s2.isoformat(), e2.isoformat()), ("2026-09-25T08:00:00+09:00", "2026-09-25T10:00:00+09:00"))

    def test_all_slots_are_timezone_aware(self):
        s = slot("x", "2026-09-24")
        self.assertIsNotNone(s.publish_at.tzinfo)
        self.assertEqual(s.publish_at_utc, "2026-09-24T13:00:00Z")


class TestDST(unittest.TestCase):
    def test_london_summer_vs_winter(self):
        self.assertTrue(slot("x", "2026-07-15").audience_local.startswith("2026-07-15T14:00:00+01:00 (BST)"))
        self.assertTrue(slot("x", "2026-12-15").audience_local.startswith("2026-12-15T13:00:00+00:00 (GMT)"))

    def test_eu_dst_end_2026_10_25(self):
        # Friday before the switch: still BST. Monday after: GMT.
        self.assertIn("(BST)", slot("x", "2026-10-23").audience_local)
        self.assertTrue(slot("x", "2026-10-23").audience_local.startswith("2026-10-23T14:00:00+01:00"))
        self.assertTrue(slot("x", "2026-10-26").audience_local.startswith("2026-10-26T13:00:00+00:00 (GMT)"))

    def test_eu_dst_start_2026_03_29(self):
        self.assertIn("(GMT)", slot("x", "2026-03-27").audience_local)
        self.assertTrue(slot("x", "2026-03-30").audience_local.startswith("2026-03-30T14:00:00+01:00 (BST)"))

    def test_us_dst_start_2026_03_08(self):
        # 08:00 JST next day = 23:00 UTC the session day.
        fri = slot("youtube_shorts", "2026-03-06")
        mon = slot("youtube_shorts", "2026-03-09")
        self.assertEqual(fri.publish_at_utc, "2026-03-06T23:00:00Z")
        self.assertTrue(fri.audience_local.startswith("2026-03-06T18:00:00-05:00 (EST)"))
        self.assertTrue(mon.audience_local.startswith("2026-03-09T19:00:00-04:00 (EDT)"))

    def test_us_dst_end_2026_11_01(self):
        fri = slot("youtube_shorts", "2026-10-30")
        mon = slot("youtube_shorts", "2026-11-02")
        self.assertTrue(fri.audience_local.startswith("2026-10-30T19:00:00-04:00 (EDT)"))
        self.assertTrue(mon.audience_local.startswith("2026-11-02T18:00:00-05:00 (EST)"))

    def test_jst_slot_is_constant_across_dst(self):
        for d in ("2026-03-06", "2026-03-09", "2026-10-23", "2026-10-26"):
            self.assertTrue(slot("youtube_shorts", d).publish_at_jst.endswith("T08:00:00+09:00"))


class TestSlotSelection(unittest.TestCase):
    def test_collision_moves_to_next_slot(self):
        s = slot("x", "2026-09-24", taken={"2026-09-24T13:00:00Z"})
        self.assertEqual(s.publish_at_jst, "2026-09-24T22:30:00+09:00")

    def test_min_lead_time_respected_inside_window(self):
        s = slot("x", "2026-09-24", now_jst="22:15")  # earliest 22:25 -> 22:30
        self.assertEqual(s.publish_at_jst, "2026-09-24T22:30:00+09:00")
        s = slot("x", "2026-09-24", now_jst="22:21")  # earliest 22:31 -> 23:00
        self.assertEqual(s.publish_at_jst, "2026-09-24T23:00:00+09:00")

    def test_tiktok_falls_back_to_na_wave_after_europe_window(self):
        s = slot("tiktok", "2026-09-24", now_jst="23:55")
        self.assertEqual((s.wave, s.publish_at_jst), ("na_tiktok", "2026-09-25T05:00:00+09:00"))

    def test_missed_window_fails_closed(self):
        with self.assertRaises(SchedulingError) as cm:
            slot("x", "2026-09-24", now_jst="23:55")
        self.assertEqual(cm.exception.code, "SCHEDULE_WINDOW_MISSED")

    def test_full_window_fails_closed(self):
        taken = {f"2026-09-24T{h:02d}:{m:02d}:00Z" for h in (13, 14) for m in (0, 30)}
        with self.assertRaises(SchedulingError):
            slot("x", "2026-09-24", taken=taken)


if __name__ == "__main__":
    unittest.main()
