import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.kioxia_breaking_radar import build_state, classify, parse_official_html

JST = ZoneInfo("Asia/Tokyo")


class KioxiaBreakingRadarTests(unittest.TestCase):
    def test_official_adr_is_high_priority(self):
        row = classify({
            "event_id": "x",
            "source": "Kioxia IR",
            "source_kind": "official_ir",
            "title": "当社普通株式を対象とした米国預託株式の米国上場準備に関するお知らせ",
            "url": "https://example.test/1",
            "published_at": "2026-09-22T00:00:00+09:00",
            "published_precision": "date",
        })
        self.assertTrue(row["adr_related"])
        self.assertEqual(row["stage"], "CONFIRMED_PREPARATION")
        self.assertGreaterEqual(row["priority"], 95)
        self.assertTrue(row["urgent"])
        self.assertFalse(row["real_submit_allowed"])

    def test_reuters_adr_is_report_not_fact(self):
        row = classify({
            "event_id": "x",
            "source": "Reuters",
            "source_kind": "media",
            "title": "Kioxia considers U.S. ADR listing, sources say",
            "url": "https://example.test/2",
            "published_at": "2026-09-22T12:00:00+09:00",
            "published_precision": "timestamp",
        })
        self.assertEqual(row["stage"], "REPORTED_TERMS")
        self.assertTrue(row["urgent"])
        self.assertLess(row["priority"], 98)

    def test_official_parser_uses_url_date_and_dedupes(self):
        payload = b"""
        <html><a href="/ja-jp/news/2026/20260915-1.html">Notice Regarding Certain Media Reports</a>
        <a href="/ja-jp/news/2026/20260915-1.html">Notice Regarding Certain Media Reports</a></html>
        """
        rows = parse_official_html(
            payload,
            "https://www.kioxia-holdings.com/ja-jp/ir/news.html",
            "Kioxia IR",
            "official_ir",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["published_at"], "2026-09-15T00:00:00+09:00")

    def test_bootstrap_does_not_alert_historical_items(self):
        now = datetime(2026, 9, 22, 18, 0, tzinfo=JST)
        event = classify({
            "event_id": "a",
            "source": "Kioxia IR",
            "source_kind": "official_ir",
            "title": "米国預託株式の上場準備",
            "url": "https://example.test/a",
            "published_at": "2026-09-22T00:00:00+09:00",
            "published_precision": "date",
        })
        state, alerts = build_state([event], {}, [{"source": "Kioxia IR", "status": "OK"}], now)
        self.assertTrue(state["bootstrap_complete"])
        self.assertEqual(alerts, [])

    def test_new_recent_urgent_alerts_after_bootstrap(self):
        now = datetime(2026, 9, 22, 18, 0, tzinfo=JST)
        previous = {"bootstrap_complete": True, "events": []}
        event = classify({
            "event_id": "b",
            "source": "SEC EDGAR",
            "source_kind": "sec",
            "title": "Kioxia Holdings F-6",
            "url": "https://sec.example.test/b",
            "published_at": "2026-09-22T17:55:00+09:00",
            "published_precision": "timestamp",
        })
        _, alerts = build_state([event], previous, [{"source": "SEC EDGAR", "status": "OK"}], now)
        self.assertEqual([x["event_id"] for x in alerts], ["b"])


if __name__ == "__main__":
    unittest.main()
