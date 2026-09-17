import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from next_theme_radar import parse_time, run  # noqa: E402


class NextThemeRadarTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config/next_theme_radar.json").read_text(encoding="utf-8"))
        self.fixture = json.loads((ROOT / "tests/fixtures/jpyc_theme_replay.json").read_text(encoding="utf-8"))
        self.now = parse_time(self.fixture["now"])

    def report(self, fixture):
        return run(self.now, self.config, fixture["events"], fixture.get("observations", {}),
                   fixture.get("screener", {}), {})["themes"][0]

    def test_simulated_jpyc_chain_confirms_with_evidence(self):
        item = self.report(self.fixture)
        self.assertEqual(item["status"], "CONFIRMED")
        self.assertEqual(item["score"], 95)
        self.assertEqual(item["first_seen"], self.fixture["now"])
        self.assertEqual(item["handoff_codes"], ["3853", "4072", "4382"])
        self.assertFalse(item["real_submit_allowed"])

    def test_missing_money_flow_fails_closed(self):
        fixture = {**self.fixture, "observations": {}}
        item = self.report(fixture)
        self.assertEqual(item["status"], "WATCH")
        self.assertEqual(item["score_breakdown"]["money_flow"], 0)

    def test_stale_screener_fails_closed(self):
        fixture = {**self.fixture, "screener": {**self.fixture["screener"],
                                                "updated_at": "2026-09-17 08:05:00 JST"}}
        item = self.report(fixture)
        self.assertEqual(item["status"], "WATCH")
        self.assertEqual(item["reacting_stock_count"], 0)

    def test_unrelated_news_does_not_create_theme(self):
        fixture = {**self.fixture, "events": {"jpy-stablecoin": [
            {"title": "Unrelated news", "published_at": self.fixture["now"]}]}}
        item = self.report(fixture)
        self.assertEqual(item["status"], "NO_EVENT")
        self.assertEqual(item["handoff_codes"], [])


if __name__ == "__main__":
    unittest.main()
