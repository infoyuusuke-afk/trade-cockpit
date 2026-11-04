"""SWING 5 cards from the public signals (OWNER 2026-11-04 「オーバーナイト銘柄カードでだして」「スイングも一緒」). Synthetic rows only."""
from pathlib import Path
import unittest

from scripts import v10_public_feed_sync as feed

ROOT = Path(__file__).resolve().parents[1]


class SwingCards(unittest.TestCase):
    def test_view_keeps_only_the_listed_fields_and_five_rows(self):
        row = {"code": "1111", "ticker": "1111.T", "name": "テスト（1111）", "score": 90, "close": 100, "trigger": 101, "stop": 95,
               "target1": 110, "target2": 120, "chart": [{"o": 1}], "extra": "x"}
        v = feed.swing_view({"updated_at": "2026-11-04 15:38:01 JST", "prepared": [row] * 9, "entered": [], "overnight_long": [row],
                             "overnight_short": ["bad", row]})
        self.assertEqual(len(v["prepared"]), 5)
        self.assertEqual(v["entered"], [])
        self.assertEqual(len(v["overnight_short"]), 1)                   # a bad row is left out
        self.assertNotIn("chart", v["overnight_long"][0])
        self.assertNotIn("extra", v["overnight_long"][0])
        self.assertEqual((v["real_submit_allowed"], v["trade_instruction"]), (False, False))

    def test_wiring(self):
        import scripts.ai_brain_observer as obs
        name, pin = obs.PUBLIC_FEED_MODULE
        self.assertEqual(obs.git_blob_sha1((ROOT / "scripts" / (name + ".py")).read_bytes()), pin)
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertEqual(gw.count("'swing_watch.json'"), 2)                # allowed and served from the feed
        self.assertNotIn("'signals.json', 'swing_watch.json'", gw)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('"swing_watch.json": "swing-cards"', html)           # the 古い banner
        block = html.split("「オーバーナイト銘柄カードでだして」「スイングも一緒」", 1)[1].split("})();", 1)[0]
        self.assertIn('fetch("swing_watch.json?t="+Date.now()', block)
        self.assertIn("d.real_submit_allowed!==false", block)
        self.assertIn('.tab-pane[data-pane="swing"]', block)
        for banned in ("cockpitSpeak", "speechSynthesis", "RssOrder", "renderAttention"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
