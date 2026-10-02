import importlib.util
import unittest
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ei",
    Path(__file__).parents[1] / "scripts" / "earnings_intelligence.py",
)
ei = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ei)


class EarningsIntelligenceTests(unittest.TestCase):
    def test_stage_boundaries(self):
        self.assertEqual(ei.stage_for_days(30), "T30")
        self.assertEqual(ei.stage_for_days(14), "T14")
        self.assertEqual(ei.stage_for_days(7), "T7")
        self.assertEqual(ei.stage_for_days(1), "T1")
        self.assertEqual(ei.stage_for_days(0), "T1")
        self.assertEqual(ei.stage_for_days(31), "FUTURE")
        self.assertEqual(ei.stage_for_days(-1), "PAST_DUE")
        self.assertEqual(ei.stage_for_days(None), "UNKNOWN")
        self.assertEqual(ei.stage_for_days(-5, result_available=True), "RESULT")

    def test_days_to_event(self):
        self.assertEqual(
            ei.days_to_event("2026-10-06", asof=date(2026, 9, 26)),
            10,
        )

    def test_missing_scores_are_not_invented(self):
        item = ei.build_watch_item(
            {
                "code": "5243",
                "name": "note",
                "date": "2026-10-06",
                "watched": True,
            },
            asof=date(2026, 9, 26),
        )
        self.assertIsNone(item["surprise_score"])
        self.assertIsNone(item["priced_in_score"])
        self.assertEqual(item["score_status"], "INSUFFICIENT_EVIDENCE")

    def test_surprise_and_priced_in_are_separate(self):
        item = ei.build_watch_item(
            {"code": "1234", "name": "X", "date": "2026-10-01"},
            asof=date(2026, 9, 26),
            company_features={
                "surprise_score": 82,
                "priced_in_score": 71,
                "runup_20d_pct": 14.2,
            },
        )
        self.assertEqual(item["surprise_score"], 82.0)
        self.assertEqual(item["priced_in_score"], 71.0)
        self.assertEqual(item["pre_event_price"]["runup_20d_pct"], 14.2)

    def test_historical_reaction_summary(self):
        summary = ei.summarize_post_earnings_reactions([
            {"gap_pct": 5, "ret_1d_pct": 3, "ret_5d_pct": 6, "ret_20d_pct": 10},
            {"gap_pct": -2, "ret_1d_pct": -1, "ret_5d_pct": 1, "ret_20d_pct": 4},
            {"gap_pct": 1, "ret_1d_pct": 2, "ret_5d_pct": None, "ret_20d_pct": 8},
        ])
        self.assertEqual(summary["sample_n"], 3)
        self.assertAlmostEqual(summary["gap_avg_pct"], 4 / 3)
        self.assertAlmostEqual(summary["positive_1d_rate_pct"], 200 / 3)

    def test_t30_watchlist_includes_active_window(self):
        events = [
            {"code": "A", "name": "A", "date": "2026-10-20", "watched": False},
            {"code": "B", "name": "B", "date": "2026-11-10", "watched": False},
        ]
        out = ei.build_watchlist(events, asof=date(2026, 9, 26), max_days=30)
        self.assertEqual([x["code"] for x in out["items"]], ["A"])
        self.assertEqual(out["items"][0]["stage"], "T30")

    def test_far_watched_name_stays_visible_as_tracked(self):
        events = [
            {"code": "B", "name": "B", "date": "2026-11-10", "watched": True},
        ]
        out = ei.build_watchlist(events, asof=date(2026, 9, 26), max_days=30)
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["stage"], "FUTURE")
        self.assertTrue(out["items"][0]["watched"])

    def test_result_item_can_remain_after_event(self):
        events = [
            {"code": "A", "name": "A", "date": "2026-09-20", "watched": False},
        ]
        out = ei.build_watchlist(
            events,
            asof=date(2026, 9, 26),
            company_features_by_code={"A": {"result_available": True}},
        )
        self.assertEqual(len(out["items"]), 1)
        self.assertEqual(out["items"][0]["stage"], "RESULT")


if __name__ == "__main__":
    unittest.main()
