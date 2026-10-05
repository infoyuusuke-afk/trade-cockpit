import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import jpx_business_calendar as calendar
import research_lane_investor_flow as flow


class InvestorFlowTests(unittest.TestCase):
    def test_calendar_keeps_the_official_closures(self):
        holidays = calendar.load_holidays()["closed"]
        self.assertEqual(holidays["2026-09-21"], "敬老の日")
        self.assertIn("2026-09-22", holidays)
        self.assertEqual(holidays["2026-09-23"], "秋分の日")
        self.assertEqual(holidays["2026-05-06"], "振替休日")
        self.assertEqual(holidays["2026-12-31"], "休業日")
        self.assertIs(calendar.is_business_day(datetime(2026, 10, 5).date()), True)
        self.assertIs(calendar.is_business_day(datetime(2026, 10, 3).date()), False)
        saved = json.loads(calendar.HOLIDAYS.read_text(encoding="utf-8"))
        self.assertIsNone(saved["published_at"])
        self.assertEqual(saved["source"], calendar.PAGE)

    def test_weekly_file_survives_a_long_closure(self):
        seen = datetime(2026, 5, 7, 12, tzinfo=flow.JST)
        detail = calendar.weekly_freshness("2026-04-24", seen)
        self.assertGreater(detail["calendar_age_days"], 4)
        self.assertEqual(detail["freshness"], "FRESH")
        self.assertEqual(detail["next_publication_due_on"], "2026-05-12")
        due = calendar.weekly_freshness("2026-04-24", datetime(2026, 5, 12, 9, tzinfo=flow.JST))
        self.assertEqual(due["freshness"], "STALE")

    def test_parser_rejects_a_duplicate_product(self):
        header = "帳票種別 Product,投資部門コード Type,数量金額区分 Volume,売 Sales,買 Purchases,報告年月日（自）From,報告年月日（至）To"
        row = "301,60,2,10,12,20260924,20260925"
        blob = (header + "\n" + row + "\n" + row + "\n").encode("utf-8")
        self.assertRaises(ValueError, flow.parse_investor_csv, blob)

    def test_stored_week_is_fetched_and_not_adopted(self):
        record = json.loads(flow.LATEST.read_text(encoding="utf-8"))
        self.assertEqual(record["session_date"], "2026-09-25")
        self.assertEqual(record["period_start"], "2026-09-24")
        self.assertEqual(record["foreign_nikkei225_futures_net_yen"], 186407123040)
        self.assertEqual(record["buy_yen"] - record["sell_yen"], record["foreign_nikkei225_futures_net_yen"])
        self.assertEqual(record["published_at"], "2026-10-01T15:30:29+09:00")
        self.assertEqual(record["published_at_basis"], "http_last_modified")
        self.assertEqual(record["first_seen_at"], record["available_at"])
        self.assertNotIn("T00:00:00", record["published_at"])
        self.assertFalse(record["trading_adoption"])
        self.assertFalse(record["real_submit_allowed"])
        self.assertFalse(record["counts_as_live_sample"])
        self.assertEqual(record["source_stage"], "OFFICIAL_PUBLIC")
        self.assertEqual(record["freshness"], "FRESH")
        self.assertGreater(record["calendar_age_days"], 4)
        self.assertEqual(record["foreign_nikkei225_futures_net_yen_for_research"], 186407123040)
        loaded = flow.load_latest(now=datetime.fromisoformat(record["first_seen_at"]))
        self.assertEqual(loaded["fetch_status"], "FETCHED")
        self.assertEqual(loaded["reason"], "FRESH")
        aged = flow.load_latest(now=datetime(2026, 10, 8, 9, tzinfo=flow.JST))
        self.assertEqual(aged["fetch_status"], "FETCHED")
        self.assertEqual(aged["freshness"], "STALE")
        self.assertIsNone(aged["foreign_nikkei225_futures_net_yen_for_research"])
        sessions = [json.loads(line) for line in flow.HISTORY.read_text(encoding="utf-8").splitlines()]
        april = sessions[0]
        self.assertEqual(april["session_date"], "2026-04-17")
        self.assertIsNone(april["published_at"])
        self.assertEqual(april["freshness"], "STALE")
        self.assertIsNone(april["foreign_nikkei225_futures_net_yen_for_research"])

    def test_module_does_not_submit_or_build_the_regime_file(self):
        text = (ROOT / "scripts" / "research_lane_investor_flow.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("build_output", text)
        self.assertNotIn("investor_regime.json", text)
        self.assertNotIn("real_submit_allowed = True", text)


if __name__ == "__main__":
    unittest.main()
