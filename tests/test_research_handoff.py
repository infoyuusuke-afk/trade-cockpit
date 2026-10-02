import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "rh",
    Path(__file__).parents[1] / "scripts" / "research_handoff.py",
)
rh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rh)


class ResearchHandoffTests(unittest.TestCase):
    def test_research_only_has_no_target(self):
        item = rh.build_observation(
            research_id="r1",
            domain="NEXT_THEME",
            detected_at="2026-09-26T05:00:00+09:00",
            title="theme",
        )
        self.assertEqual(item["handoff_status"], "RESEARCH_ONLY")
        self.assertIsNone(item["handoff_target"])
        self.assertFalse(item["real_submit_allowed"])

    def test_missing_conditions_prevent_handoff(self):
        item = rh.build_observation(
            research_id="r2",
            domain="NEXT_THEME",
            detected_at="t",
            title="theme",
            candidate_strategy="event-hot",
            escalation_conditions=["fresh_catalyst", "market_reaction", "local_confirmation"],
            met_conditions=["fresh_catalyst"],
        )
        self.assertEqual(item["handoff_status"], "WAITING_CONDITIONS")
        self.assertEqual(
            item["missing_conditions"],
            ["market_reaction", "local_confirmation"],
        )
        self.assertIsNone(item["handoff_target"])

    def test_all_conditions_qualify_handoff(self):
        item = rh.build_observation(
            research_id="r3",
            domain="NEXT_THEME",
            detected_at="t",
            title="theme",
            candidate_strategy="event-hot",
            escalation_conditions=["fresh_catalyst", "market_reaction"],
            met_conditions=["fresh_catalyst", "market_reaction"],
        )
        self.assertEqual(item["handoff_status"], "QUALIFIED")
        self.assertEqual(item["handoff_target"], "event-hot")

    def test_stale_always_blocks_handoff(self):
        item = rh.build_observation(
            research_id="r4",
            domain="PTS_CONTEXT",
            detected_at="t",
            title="pts",
            candidate_strategy="event-hot",
            escalation_conditions=[],
            met_conditions=[],
            stale=True,
        )
        self.assertEqual(item["handoff_status"], "STALE")
        self.assertIsNone(item["handoff_target"])
        self.assertTrue(item["fail_closed"])

    def test_fail_closed_blocks_even_when_conditions_met(self):
        item = rh.build_observation(
            research_id="r5",
            domain="NEWS_IR",
            detected_at="t",
            title="ir",
            candidate_strategy="event-hot",
            escalation_conditions=["official_source"],
            met_conditions=["official_source"],
            fail_closed=True,
        )
        self.assertEqual(item["handoff_status"], "BLOCKED")
        self.assertIsNone(item["handoff_target"])

    def test_invalid_target_rejected(self):
        with self.assertRaises(ValueError):
            rh.build_observation(
                research_id="r6",
                domain="NEXT_THEME",
                detected_at="t",
                title="theme",
                candidate_strategy="real-order-now",
            )


if __name__ == "__main__":
    unittest.main()
