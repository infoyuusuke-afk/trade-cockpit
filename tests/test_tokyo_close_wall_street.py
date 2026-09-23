import unittest
from scripts.tokyo_close_wall_street import build_package

class TokyoCloseWallStreetTest(unittest.TestCase):
    def test_builds_from_observed_facts_only(self):
        out = build_package(
            "2026-09-23",
            [{"label": "Nikkei 225", "value": "+1.2%", "observed": True, "source_ts": "2026-09-23T15:30:00+09:00"}],
            ["vwap_reclaim"],
        )
        self.assertEqual(out["series"], "TOKYO CLOSE -> WALL STREET")
        self.assertEqual(out["market_events_en"], ["VWAP Reclaim"])
        self.assertFalse(out["publish_ready"])
        self.assertTrue(out["guardrails"]["publication_requires_owner_approval"])

    def test_rejects_unverified_fact(self):
        with self.assertRaises(ValueError):
            build_package("2026-09-23", [{"label": "KIOXIA", "value": "+5%", "observed": False}])

    def test_four_original_working_roles_present(self):
        out = build_package("2026-09-23", [])
        self.assertEqual(set(out["characters"]), {"mugi", "meru", "kuu", "ham"})

if __name__ == "__main__":
    unittest.main()
