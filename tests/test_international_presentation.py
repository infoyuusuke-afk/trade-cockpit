import unittest

from scripts.international_presentation import render_event

class InternationalPresentationTest(unittest.TestCase):
    def test_owner_mode_never_requires_english(self):
        out = render_event("vwap_reclaim", "OWNER_JA")
        self.assertEqual(out, {"mode": "OWNER_JA", "primary": "VWAP回復"})

    def test_broadcast_mode_is_english(self):
        self.assertEqual(
            render_event("rapid_adverse_move", "BROADCAST_EN")["primary"],
            "Sharp Drop Alert",
        )

    def test_bilingual_keeps_owner_japanese_primary(self):
        out = render_event("relief_exit_risk", "BILINGUAL")
        self.assertEqual(out["primary"], "安堵利確注意")
        self.assertEqual(out["secondary"], "Relief-Exit Risk")

    def test_unknown_event_fails_closed(self):
        with self.assertRaises(ValueError):
            render_event("invented_signal", "BROADCAST_EN")

if __name__ == "__main__":
    unittest.main()
