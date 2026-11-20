"""OWNER 2026-11-16 「新しいタブ『決算ギャップ』を作って … 合格するまでは『検証中』と書いて、売買の合図・声・注文カードは付けない」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


def _block():
    i = HTML.index('if(!nav||!main||document.querySelector(\'.cockpit-tab[data-tab="earnings-gap"]\'))return;')
    return HTML[HTML.rindex("<script>", 0, i):HTML.index("</script>", i)]


class EarningsGapTab(unittest.TestCase):
    def test_gateway_serves_it_only_with_safe_flags(self):
        self.assertIn("function Get-EarningsGapView([string]$RuntimeDir) {", GW)
        self.assertIn("$file = Join-Path $RuntimeDir 'earnings_gap_v1.json'", GW)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-earnings-gap-v1' -or $view.real_submit_allowed -ne $false", GW)
        self.assertIn("if ($path -eq '/earnings_gap.json') {", GW)
        i = GW.index("function Get-EarningsGapView")
        self.assertTrue(all(ord(ch) < 128 for ch in GW[i:GW.index("\n}\n", i)]))

    def test_tab_lists_the_rows_and_both_sides_results(self):
        b = _block()
        self.assertIn('b.textContent="決算ギャップ"', b)
        self.assertIn('fetch("/earnings_gap.json?t="+Date.now(),{cache:"no-store"})', b)
        self.assertIn('if(!j||j.real_submit_allowed!==false||j.trade_instruction!==false)', b)
        self.assertIn("（0件とは扱いません）", b)
        for head in ("<th>上下</th>", "<th>銘柄</th>", "<th>発表</th>", "<th>寄りの飛び幅</th>", "<th>何日目</th>",
                     "<th>寄りから（費用0.1%引き）</th>", "<th>TOPIXとの差</th>"):
            self.assertIn(head, b)
        for head in ("<th>件数</th>", "<th>平均</th>", "<th>勝率</th>", "<th>PF</th>", "<th>前半</th>", "<th>後半</th>",
                     "<th>でたらめに選んだ場合</th>", "<th>判定</th>"):
            self.assertIn(head, b)
        self.assertIn('statRow("上（寄りで買い）",st.up)+statRow("下（寄りで空売り）",st.down)', b)

    def test_same_colours_as_the_other_tabs_across_the_width(self):
        # OWNER 2026-11-16 「色がちがうんじゃないか」
        self.assertIn("#earnings-gap-pane .eg-wrap{grid-column:1/-1;padding:16px 18px;border:1px solid #303033;"
                      "border-radius:14px;background:#111113;color:#f5f5f7}", HTML)
        self.assertIn('pane.innerHTML=\'<div class="eg-wrap"><div class="eg-body">読込中...</div></div>\';', _block())
        self.assertNotIn("#131722", HTML[HTML.index("#earnings-gap-pane .eg-wrap"):HTML.index("#earnings-gap-pane .eg-wrap") + 2000])

    def test_it_says_kenshochu_until_passed_and_is_not_a_signal(self):
        b = _block()
        self.assertIn('(s.passed===true?"合格":"検証中")', b)
        self.assertIn('status=st.up&&st.up.passed===true&&st.down&&st.down.passed===true?"合格":"検証中"', b)
        self.assertIn("売買の合図ではありません。声と注文カードはありません。", b)
        code = "\n".join(line for line in b.splitlines() if not line.lstrip().startswith("//"))
        for word in ("cockpitSpeak", "speechSynthesis", "renderCockpitCard", "renderScalpCard", "order",
                     "#35e2ae", "#ff5a5f", "#f23645"):
            self.assertNotIn(word, code)
        self.assertIn("esc(r.name)", b)


if __name__ == "__main__":
    unittest.main()
