"""OWNER 2026-11-14 「アナリストの欄に、Claudeのアナリスト（テクニカル・ファンダ・決算・FOCUS）のカードも足して、役目・動く時刻・
最後の答えの時刻・今日の答え 届いた／まだ を出す版にして。答えの中身は変えない」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


class ClaudeAnalystCards(unittest.TestCase):
    def test_gateway_serves_only_safe_times(self):
        i = GW.index("function Get-ClaudeAnalystsView([string]$RuntimeDir) {")
        fn = GW[i:GW.index("\n}\n", i)]
        self.assertIn("Join-Path $RuntimeDir 'claude_analysts_v1.json'", fn)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-claude-analysts-v1' -or $view.real_submit_allowed -ne $false", fn)
        self.assertIn("$view.trade_instruction -ne $false", fn)
        self.assertIn("ReparsePoint", fn)
        self.assertIn("if ($path -eq '/claude_analysts.json') {", GW)

    def test_four_cards_with_role_time_last_and_today(self):
        self.assertIn('get("/analyst_instructions.json"),get("/claude_analysts.json")]);', HTML)
        i = HTML.index("const C_CARDS=[")
        block = HTML[HTML.rindex("const caOk=", 0, i):HTML.index("    box.innerHTML=cards.map(", i)]
        self.assertIn('.join("")+caHtml;', HTML[i:])   # the Claude cards come after the GPT / Grok ones
        for name in ("Claude テクニカル（地合い）", "Claude ファンダメンタルズ", "Claude 決算", "Claude FOCUS"):
            self.assertIn(name, block)
        # only today's file from the PC counts; anything else is 確認できません, never 届いた
        self.assertIn('ca.real_submit_allowed===false&&ca.trade_instruction===false&&Array.isArray(ca.items)&&String(ca.day||"")===today', block)
        self.assertIn("x.today===true?'<span class=\"an-st ok\">今日の答え 届いた</span>':'<span class=\"an-st wait\">今日の答え まだ</span>'", block)
        self.assertIn("!known?'<span class=\"an-st unk\">確認できません</span>'", block)
        self.assertIn("<b>役目</b>", block)
        self.assertIn("<b>動く時刻</b>", block)
        self.assertIn("<b>最後の答え</b>", block)
        self.assertIn("esc(c.name)", block)
        self.assertIn("esc(r.at)", block)
        # display only: no copy box, no order, no voice
        self.assertNotIn("textarea", block)
        self.assertNotIn("cockpitSpeak", block)
        self.assertNotIn("fetch(", block)


if __name__ == "__main__":
    unittest.main()
