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

    def test_value_view_and_cards(self):
        # OWNER 2026-11-04 「バリューも」
        row = {"code": "1111", "name": "テスト（1111）", "score": 90, "close": 100, "supply_phase": "需給未確認", "chart": [{"o": 1}]}
        v = feed.value_view({"updated_at": "2026-11-04 15:38:01 JST", "monthly_weekly_hammers": [row] * 7, "long_term_ma_rebounds": [],
                             "long_term_ma_rebounds_unverified": [row]})
        self.assertEqual(len(v["monthly_weekly_hammers"]), 5)
        self.assertNotIn("chart", v["long_term_ma_rebounds_unverified"][0])
        self.assertEqual(v["long_term_ma_rebounds_unverified"][0]["supply_phase"], "需給未確認")
        self.assertEqual((v["real_submit_allowed"], v["trade_instruction"]), (False, False))
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertEqual(gw.count("'value_watch.json'"), 2)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('"value_watch.json": "value-cards"', html)
        self.assertIn('fetch("value_watch.json?t="+Date.now()', html)
        self.assertIn('.tab-pane[data-pane="value"]', html)
        self.assertIn("50週線／200日線反発（需給未確認）", html)

    def test_volatile_days(self):
        # OWNER 2026-11-04 「価格が大きく変動しそうな日をしっかりピックアップして表示」
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        block = html.split("「価格が大きく変動しそうな日をしっかりピックアップして表示」", 1)[1].split("})();", 1)[0]
        self.assertIn('e.impact==="高"', block)
        self.assertIn("end=add(today,30)", block)
        self.assertIn('"285A","6857","8035","9984"', block)
        self.assertIn('top=items.length>=2', block)                         # 特に注意 = two or more on one day
        self.assertIn('get("event_calendar.json"),get("earnings_calendar.json")', block)
        for banned in ("cockpitSpeak", "RssOrder", "renderAttention"):
            self.assertNotIn(banned, block)

    def test_bnf_cards(self):
        # OWNER 2026-11-04 「BNF銘柄もカードタイプで」
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if ($path -eq '/bnf_candidates.json') {", gw)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-bnf-candidates-v1'", gw)
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        block = html.split("「BNF銘柄もカードタイプで」: the daily BNF list", 1)[1].split("})();", 1)[0]
        self.assertIn('fetch("/bnf_candidates.json?t="+Date.now()', block)
        self.assertIn("d.real_submit_allowed!==false", block)
        self.assertIn('.tab-pane[data-pane="wick"]', block)
        self.assertIn("esc(d.note)", block)                                  # the 2026 result stays on the screen
        for banned in ("cockpitSpeak", "RssOrder", "renderAttention"):
            self.assertNotIn(banned, block)

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
