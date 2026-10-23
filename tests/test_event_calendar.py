import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('ecal', Path(__file__).parents[1] / 'scripts/event_calendar.py')
ecal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecal)


class TimeCertaintyTests(unittest.TestCase):
    def test_exact_hhmm_converts_to_correct_utc(self):
        # JSTはUTC+9固定（夏時間なし）。21:30 JST = 12:30 UTC
        certainty, scheduled = ecal.time_certainty_and_utc('2026-09-11', '21:30')
        self.assertEqual(certainty, 'exact')
        self.assertEqual(scheduled, '2026-09-11T12:30:00+00:00')

    def test_all_day_is_date_only_not_invented_time(self):
        certainty, scheduled = ecal.time_certainty_and_utc('2026-09-07', '終日')
        self.assertEqual(certainty, 'date_only')
        self.assertIsNone(scheduled)

    def test_after_meeting_is_window_not_invented_noon(self):
        # ロードマップ第5節: 時刻不明の日銀政策公表を架空の正午に設定しない
        certainty, scheduled = ecal.time_certainty_and_utc('2026-09-18', '会合終了後')
        self.assertEqual(certainty, 'window')
        self.assertIsNone(scheduled)

    def test_open_and_close_are_window(self):
        self.assertEqual(ecal.time_certainty_and_utc('2026-09-18', '寄り付き'), ('window', None))
        self.assertEqual(ecal.time_certainty_and_utc('2026-09-18', '大引け'), ('window', None))

    def test_unknown_date_has_no_certainty(self):
        certainty, scheduled = ecal.time_certainty_and_utc(None, '21:30')
        self.assertIsNone(certainty)
        self.assertIsNone(scheduled)


class NotificationScheduleTests(unittest.TestCase):
    def test_tier_a_has_three_checkpoints(self):
        sched = ecal.notification_schedule('2026-09-11T12:30:00+00:00', 'A')
        self.assertEqual([s['stage'] for s in sched], ['T-30分', 'T-5分', 'T時点'])

    def test_tier_b_has_two_checkpoints_no_t30(self):
        sched = ecal.notification_schedule('2026-09-11T12:30:00+00:00', 'B')
        self.assertEqual([s['stage'] for s in sched], ['T-5分', 'T時点'])

    def test_checkpoint_offsets_are_correct(self):
        sched = ecal.notification_schedule('2026-09-11T12:30:00+00:00', 'A')
        t30 = next(s for s in sched if s['stage'] == 'T-30分')
        self.assertEqual(t30['at_utc'], '2026-09-11T12:00:00+00:00')

    def test_no_scheduled_time_yields_no_checkpoints(self):
        # 架空の時刻を基準に通知を作らない（不定時イベントは別扱い）
        self.assertEqual(ecal.notification_schedule(None, 'A'), [])


class EventBuilderTests(unittest.TestCase):
    def test_event_defaults_to_tier_a(self):
        e = ecal.event('x-1', 'テストイベント', '2026-09-11', '米経済', 'cpi', time_jst='21:30')
        self.assertEqual(e['tier'], 'A')
        self.assertEqual(e['time_certainty'], 'exact')
        self.assertEqual(len(e['notification_schedule']), 3)

    def test_all_day_event_has_no_notification_schedule(self):
        e = ecal.event('x-2', 'テスト休場', '2026-09-07', '米国休場', 'nyse')
        self.assertEqual(e['notification_schedule'], [])

    def test_build_output_has_fetched_at_on_every_event(self):
        out = ecal.build()
        self.assertTrue(out['events'])
        for item in out['events']:
            self.assertTrue(item['fetched_at'])


class IndexReviewDates20261024(unittest.TestCase):
    """OWNER 2026-10-24 「カレンダーのデータ修正」: TOPIX (JPX 2026-10-07) and MSCI November review dates."""

    def by_id(self):
        return {x["id"]: x for x in ecal.build()["events"]}

    def test_topix_first_periodic_review_on_october_30_close(self):
        x = self.by_id()["topix-2026-10"]
        self.assertEqual((x["date"], x["time_jst"], x["announcement_date"], x["flow_date"]),
                         ("2026-10-30", "大引け", "2026-10-07", "2026-10-30"))
        self.assertFalse(x["trade_block"])

    def test_msci_november_review_announcement_and_close(self):
        ev = self.by_id()
        self.assertEqual(ev["msci-2026-11-announce"]["date"], "2026-11-12")
        x = ev["msci-2026-11"]
        self.assertEqual((x["date"], x["time_jst"], x["effective_date"]), ("2026-11-30", "大引け", "2026-12-01"))
        self.assertIn("変更あり得る", x["status"])


if __name__ == '__main__':
    unittest.main()
