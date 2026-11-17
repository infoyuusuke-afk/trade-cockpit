"""OWNER 2026-11-17 「トレード結果の振り返りは平日毎日実施して報告するように」「結果はAIトレード日記タブで内容が確認できる形にする」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


class AirReview(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「結果はAIトレード日記タブで内容が確認できる形にする」:")
        self.b = HTML[i:HTML.index("</script>", i)]

    def test_gateway_serves_only_a_safe_file(self):
        i = GW.index("function Get-AirReviewView")
        fn = GW[i:GW.index("\n}", i)]
        self.assertTrue(all(ord(c) < 128 for c in fn))
        self.assertIn("'air_trade_review_v1.json'", fn)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-air-review-v1' -or $view.real_submit_allowed -ne $false", fn)
        self.assertIn("$view.trade_instruction -ne $false", fn)
        self.assertIn("if ($path -eq '/air_trade_review.json') {", GW)

    def test_tab_shows_the_review_as_text(self):
        self.assertIn('fetch("/air_trade_review.json?t="+Date.now(),{cache:"no-store"})', self.b)
        self.assertIn("if(!j||j.real_submit_allowed!==false||j.trade_instruction!==false", self.b)
        self.assertIn("const pane=document.querySelector('.tab-pane[data-pane=\"ai-journal\"]')", self.b)
        self.assertIn("const tint=s=>esc(s).replace(", self.b)
        # 「AIトレード日記タブの一番上に『今日の振り返り』として出す」
        self.assertIn("'<h2>'+(cur===days[0]?'今日の振り返り':", self.b)
        self.assertIn('if(intro)intro.after(sec);else pane.prepend(sec);', self.b)
        code = "\n".join(l for l in self.b.splitlines() if not l.lstrip().startswith("//"))
        for word in ("cockpitSpeak", "renderCockpitCard", "/control", "RssOrder"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
