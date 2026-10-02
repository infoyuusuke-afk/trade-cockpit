import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "ec",
    Path(__file__).parents[1] / "scripts" / "event_candidates.py",
)
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)


class EventCandidateContractTests(unittest.TestCase):
    def test_pts_candidate_gets_pts_source(self):
        item = ec.build_candidate(
            ticker="1234.T",
            pts={"price": 1200, "gap_pct": 8.2, "turnover_yen": 500000000},
        )
        self.assertIn("PTS", item["event_sources"])
        self.assertEqual(item["pts"]["price"], 1200.0)

    def test_previous_limit_up_and_down_sources(self):
        up = ec.build_candidate(
            ticker="1111.T",
            previous_limit_state="LIMIT_UP",
        )
        down = ec.build_candidate(
            ticker="2222.T",
            previous_limit_state="LIMIT_DOWN",
        )
        self.assertIn("PREV_LIMIT_UP", up["event_sources"])
        self.assertIn("PREV_LIMIT_DOWN", down["event_sources"])

    def test_multiple_sources_add_multi_source_badge(self):
        item = ec.build_candidate(
            ticker="1234.T",
            pts={"gap_pct": 7.0},
            disclosure={"type": "UPWARD_REVISION"},
            next_theme={"theme": "AI"},
        )
        self.assertIn("PTS", item["event_sources"])
        self.assertIn("IR", item["event_sources"])
        self.assertIn("NEXT_THEME", item["event_sources"])
        self.assertIn("MULTI_SOURCE", item["event_sources"])

    def test_next_theme_does_not_handoff_without_explicit_qualification(self):
        item = ec.build_candidate(
            ticker="1234.T",
            next_theme={"theme": "AI", "score": 85, "status": "CONFIRMED"},
            qualified_for_event5=False,
        )
        self.assertFalse(item["qualified_for_event5"])
        self.assertIsNone(item["handoff_target"])

    def test_qualified_candidate_handoffs_to_event5(self):
        item = ec.build_candidate(
            ticker="1234.T",
            pts={"gap_pct": 6.5},
            qualified_for_event5=True,
        )
        self.assertTrue(item["qualified_for_event5"])
        self.assertEqual(item["handoff_target"], "event-hot")

    def test_stale_candidate_suppresses_pts_price_and_blocks_handoff(self):
        item = ec.build_candidate(
            ticker="1234.T",
            pts={"price": 1200, "gap_pct": 8.0},
            qualified_for_event5=True,
            stale=True,
        )
        self.assertIsNone(item["pts"]["price"])
        self.assertIsNone(item["pts"]["gap_pct"])
        self.assertFalse(item["qualified_for_event5"])
        self.assertTrue(item["fail_closed"])

    def test_blocked_live_confirmation_blocks_handoff(self):
        item = ec.build_candidate(
            ticker="1234.T",
            qualified_for_event5=True,
            live_confirmation="BLOCKED",
        )
        self.assertFalse(item["qualified_for_event5"])
        self.assertTrue(item["fail_closed"])

    def test_score_is_not_invented_when_missing(self):
        item = ec.build_candidate(ticker="1234.T")
        self.assertIsNone(item["expectation_score"])
        self.assertEqual(item["expectation_score_status"], "INSUFFICIENT_EVIDENCE")

    def test_invalid_score_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_candidate(ticker="1234.T", expectation_score=140)

    def test_invalid_limit_state_rejected(self):
        with self.assertRaises(ValueError):
            ec.build_candidate(ticker="1234.T", previous_limit_state="MAYBE_UP")


if __name__ == "__main__":
    unittest.main()
