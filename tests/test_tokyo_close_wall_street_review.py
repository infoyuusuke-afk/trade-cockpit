import unittest
from scripts.tokyo_close_wall_street_review import build_review

class TokyoCloseReviewTest(unittest.TestCase):
    def setUp(self):
        self.facts = [
            {"label": "KIOXIA", "value": "+2.0%", "observed": True, "source_ts": "2026-09-23T15:30:00+09:00"},
            {"label": "USDJPY", "value": "150.00", "observed": True, "source_ts": "2026-09-23T15:30:00+09:00"},
        ]

    def test_owner_gets_japanese_review_and_approval_gate(self):
        out = build_review("2026-09-23", self.facts)
        self.assertIn("東京市場レビュー", out["owner_review_ja"]["title"])
        self.assertTrue(out["owner_approval_required"])
        self.assertFalse(out["publish_ready"])

    def test_english_copy_keeps_only_supplied_numeric_facts(self):
        out = build_review("2026-09-23", self.facts)
        text = " ".join(out["broadcast_en"]["facts"])
        self.assertIn("+2.0%", text)
        self.assertIn("150.00", text)
        self.assertNotIn("S&P", text)
        self.assertNotIn("Nasdaq", text)

    def test_character_order_is_stable(self):
        out = build_review("2026-09-23", self.facts)
        self.assertEqual([x["character"] for x in out["comic_beats"]], ["ham", "meru", "mugi", "kuu"])

    def test_unverified_fact_still_fails_closed(self):
        with self.assertRaises(ValueError):
            build_review("2026-09-23", [{"label": "Nikkei", "value": "+9%", "observed": False}])

if __name__ == "__main__":
    unittest.main()
