import json
import unittest
from pathlib import Path

from scripts import ai_brain_research as brain
from scripts.cockpit_parallel_lanes import (
    earnings_lanes,
    event_lane_display,
    is_weekly_snapshot,
    kioxia_score_display,
    performance_source,
    position_block,
    powershell_non_ascii_lines,
    research_block_reason,
    research_sample_n,
    volume_surge_display,
)

ROOT = Path(__file__).resolve().parents[1]


class ParallelLaneTests(unittest.TestCase):
    def test_weekly_snapshot_stays_out_of_research(self):
        review = json.loads((ROOT / "weekly_review.json").read_text(encoding="utf-8"))
        self.assertTrue(is_weekly_snapshot(review))
        self.assertEqual(performance_source(review), "SNAPSHOT")
        self.assertEqual(research_block_reason(review), "WEEKLY_SNAPSHOT_NOT_LIVE_SHADOW")
        forged = dict(review, source_stage="LIVE_SHADOW")
        self.assertEqual(performance_source(forged), "SNAPSHOT")
        self.assertEqual(research_sample_n([review, forged]), 0)

    def test_sources_stay_visually_separate(self):
        self.assertEqual(performance_source({"source_stage": "SYNTHETIC/REPLAY"}), "SYNTHETIC/REPLAY")
        self.assertEqual(research_block_reason({"source_stage": "SYNTHETIC/REPLAY"}), "SYNTHETIC_NOT_LIVE_SAMPLE")
        self.assertEqual(research_block_reason({"source_stage": "LIVE_SHADOW"}), "LEDGER_ADMISSION_ONLY")
        self.assertEqual(performance_source({}), "NOT_AVAILABLE")
        lanes = event_lane_display([
            {"lane": "pts_overnight", "fresh": True, "source_stage": "SYNTHETIC/REPLAY", "symbol": "285A.T"},
            {"lane": "previous_limit", "fresh": False, "source_stage": "LIVE", "symbol": "285A.T"},
            {"lane": "same_day_pickup", "fresh": True, "source_stage": "LIVE", "symbol": "285A.T"},
        ])
        self.assertEqual(lanes["pts_overnight"]["status"], "NOT_AVAILABLE")
        self.assertEqual(lanes["previous_limit"]["status"], "NOT_AVAILABLE")
        self.assertEqual(lanes["same_day_pickup"]["status"], "OBSERVED")
        self.assertEqual(lanes["same_day_pickup"]["rows"][0]["symbol"], "285A.T")

    def test_missing_volume_and_zero_sample_do_not_invent_numbers(self):
        blank = volume_surge_display(None, True)
        stale = volume_surge_display(2.5, False)
        self.assertEqual(blank["status"], "NOT_AVAILABLE")
        self.assertEqual(blank["text"], "—")
        self.assertFalse(blank["lit"])
        self.assertEqual(stale["status"], "NOT_AVAILABLE")
        observed = volume_surge_display(1.4, True)
        self.assertEqual(observed["status"], "OBSERVED")
        self.assertTrue(observed["lit"])
        self.assertEqual(observed["text"], "1.40倍")
        score = kioxia_score_display(offered_probability=80, clean_n=0)
        self.assertEqual(score["probability"], "NOT_AVAILABLE")
        self.assertEqual(score["expectancy"], "NOT_AVAILABLE")
        self.assertEqual(score["confidence"], "NOT_AVAILABLE")
        self.assertFalse(score["generated"])
        self.assertTrue(score["discarded_offer"])

    def test_position_block_is_not_cleared_by_an_order(self):
        block = position_block()
        self.assertEqual(block["reason"], "BROKER_POSITION_RSS_UNIMPLEMENTED")
        self.assertFalse(block["unblock_by_live_order"])
        self.assertFalse(block["private_holdings_published"])
        self.assertFalse(block["real_submit_allowed"])

    def test_earnings_lanes_stay_off_the_live_signal(self):
        lanes = earnings_lanes()
        self.assertTrue(all(item.get("live_signal") is False for item in lanes.values() if isinstance(item, dict)))
        self.assertEqual(lanes["this_forecast"]["probability"], "NOT_AVAILABLE")
        self.assertEqual(lanes["swing_prep"]["status"], "NOT_AVAILABLE")
        self.assertFalse(lanes["real_submit_allowed"])

    def test_collector_japanese_is_not_comment_only(self):
        audit = powershell_non_ascii_lines("ms2_live/MS2_RSS_100_Collector.ps1")
        self.assertTrue(audit["execution_lines"])
        self.assertFalse(audit["safe_to_strip_comments_only"])

    def test_research_survey_records_sources_without_fetching_or_adopting(self):
        lane = brain.research_data_lane()
        self.assertEqual(len(lane), 17)
        for item in lane:
            if item["id"] in {"short_sale_ratio", "investor_futures_flow"}:
                self.assertEqual(item["fetch_status"], "FETCHED")
            else:
                self.assertEqual(item["fetch_status"], "NOT_FETCHED")
            self.assertFalse(item["trading_adoption"])
            self.assertFalse(item["real_submit_allowed"])
            self.assertTrue(item["source_candidate"])
            self.assertTrue(item["available_at"])
            self.assertEqual(item["surveyed_on"], "2026-10-05")
            self.assertIn(item["history_fetchable"], {True, False, None})
            if item["source_url"] is not None:
                self.assertTrue(item["source_url"].startswith("https://"))
        investor = next(item for item in lane if item["id"] == "investor_futures_flow")
        self.assertIn("jpx.co.jp/markets/statistics-equities/investor-type", investor["source_url"])
        self.assertTrue(investor["history_fetchable"])
        shikiho = next(item for item in lane if item["id"] == "shikiho_fundamentals")
        self.assertIsNone(shikiho["source_url"])
        self.assertFalse(shikiho["history_fetchable"])

    def test_pages_keep_the_unavailable_labels(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        control = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("出来高急増 NOT AVAILABLE", page)
        self.assertIn("夜間PTS急騰", page)
        self.assertIn("前日S高/S安", page)
        self.assertIn("当日ピックアップ", page)
        self.assertIn('id="kio-shadow-ev">NOT AVAILABLE', page)
        self.assertIn('id="kio-forecast-confidence">NOT AVAILABLE', page)
        self.assertIn("過去類似日の一致", page)
        self.assertIn("BROKER_POSITION_RSS_UNIMPLEMENTED", control)
        self.assertIn("promotion には入れません", control)
        supervisor = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertIn("LONG_ENTRY_SIGNALS = frozenset", supervisor)
