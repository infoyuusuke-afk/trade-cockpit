"""OWNER 2026-11-17 「１５時２４分にIN１５時３０大引けに売買するクロージング（名称まかせる）タブ作って」「引けの板寄せタブに『やる日』の印を足して…
日付は推測しないで、公式の発表で確かめたものだけ使う。研究のみ、声なし、注文しない」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GW = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")


class ClosingAuctionTab(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「１５時２４分にIN１５時３０大引けに売買するクロージング")
        self.b = HTML[i:HTML.index("</script>", i)]

    def test_gateway_serves_only_a_safe_file(self):
        i = GW.index("function Get-ClosingAuctionView")
        fn = GW[i:GW.index("\n}", i)]
        self.assertTrue(all(ord(c) < 128 for c in fn))
        self.assertIn("'closing_auction_v1.json'", fn)
        self.assertIn("[string]$view.schema_version -cne '100b-v10-closing-auction-v1' -or $view.real_submit_allowed -ne $false", fn)
        self.assertIn("$view.trade_instruction -ne $false", fn)
        self.assertIn("$item.Length -gt 262144", fn)
        self.assertIn("if ($path -eq '/closing_auction.json') {", GW)

    def test_tab_reads_and_checks_the_flags(self):
        self.assertIn('fetch("/closing_auction.json?t="+Date.now(),{cache:"no-store"})', self.b)
        self.assertIn("if(!j||j.real_submit_allowed!==false||j.trade_instruction!==false)", self.b)
        self.assertIn('b.textContent="引けの板寄せ";', self.b)
        self.assertIn("研究・記録中（前の検証は不合格）", self.b)
        self.assertEqual(self.b.count("<table data-keep-table>"), 3)

    def test_marks_and_display_only(self):
        self.assertIn("やる日とやらない日の成績", self.b)
        self.assertIn("指数の入れ替え（公式の発表で確かめた日だけ）", self.b)
        code = "\n".join(l for l in self.b.splitlines() if not l.lstrip().startswith("//"))
        for word in ("cockpitSpeak", "renderCockpitCard", "/control", "RssOrder"):
            self.assertNotIn(word, code)

    def test_screen_opens_the_tab_at_1523_on_trading_days(self):
        # OWNER 2026-11-17 「１５時２３分にギャンブルタブに切り替え、２５分すぎたらオーバーナイトに切り替える」
        self.assertIn('if(wd<1||wd>5||hol.includes(day)||hms<"15:23:00"||hms>="15:25:00")return;', self.b)
        self.assertIn('if(!m.ca)go("closing-auction","ca");', self.b)
        self.assertIn("window.cockpitHolidays=HOLIDAYS;", HTML)
        # 15:25 is the switch of 2026-11-05 (OVERNIGHT 5), unchanged
        self.assertIn('if(wd===0||wd===6||hm<"15:25:10"||hm>"15:26:30")return;', HTML)
        self.assertIn('const KEY="cockpitOvernightSwitchV1";', HTML)


if __name__ == "__main__":
    unittest.main()
