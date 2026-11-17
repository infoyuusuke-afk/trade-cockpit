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
        self.assertEqual(self.b.count("<table data-keep-table>"), 5)   # compare, virtual limit, the day's stocks, by day, the 15:24 lock

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

    def test_1524_lock_is_shown_as_written_and_checked_by_the_gateway(self):
        # OWNER 2026-11-17 「15:24にその日の候補…『仮想・不合格の手法』の印付きで出し、15:24の値で固めて後から変えない」
        self.assertIn('fetch("/closing_auction_lock.json?t="+Date.now(),{cache:"no-store"})', self.b)
        self.assertIn("lk.real_submit_allowed===false&&lk.trade_instruction===false&&lk.day===", self.b)
        self.assertIn("今日の候補（15:24に固定・後から変えない）", self.b)
        i = GW.index("function Get-ClosingLockView")
        fn = GW[i:GW.index("\n}", i)]
        self.assertTrue(all(ord(c) < 128 for c in fn))
        self.assertIn("'100b-v10-closing-lock-v1'", fn)
        self.assertIn("'CLOSING_LOCK_NOT_TODAY'", fn)
        self.assertIn("[string]::CompareOrdinal($lockedAt.Substring(11, 8), '15:24:00') -lt 0", fn)
        self.assertIn("'CLOSING_LOCK_CHANGED_AFTER'", fn)
        self.assertIn("if ($path -eq '/closing_auction_lock.json') {", GW)

    def test_time_shown_without_T(self):
        # OWNER 2026-11-17 「更新日時の表示『11/17T16:05:12』を直す」
        self.assertIn(r'const when=s=>{const m=/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(s||""));return m?m[2]+"/"+m[3]+" "+m[4]+":"+m[5]:"—";};', self.b)
        self.assertIn("毎日、引けの後に記録します（更新 '+esc(when(j.generated_at))+'）。", self.b)

    def test_overnight_switch_skips_holidays(self):
        self.assertIn("if(Array.isArray(window.cockpitHolidays)&&window.cockpitHolidays.includes(day))return;", HTML)

    def test_quick_view_first_details_folded(self):
        # OWNER 2026-11-17 「短時間で決めなきゃいけないからもっとわかりやすく修正」
        # OWNER 2026-11-17 「『今日はやる日』を『今日の印：〇〇』にして、色はほかの表と同じ灰色、印名だけ小さな札。印なしは『今日の印：なし』」
        self.assertIn("'<div class=\"ca-verdict\">今日の印：'+(isDo?dayMarks.map(m=>'<span class=\"ca-mark\">'+esc(m)+'</span>').join(\"\"):'なし')", self.b)
        self.assertNotIn("今日はやる日", self.b)
        self.assertIn("border:1px solid #303033;background:#1c1c1e;color:#E8EAED}", HTML)
        self.assertIn('col("w2","逆張り（上げた銘柄を空売り・下げた銘柄を買い）",rec.w2)+col("w1","順張り（高値の近くは買い・安値の近くは空売り）",rec.w1)', self.b)
        # 「候補をその形の費用込み期待値の高い順に並べ、各行に期待値。AIアナリストの総合点…を列で出して毎日記録するが、並び順には入れない」
        self.assertIn("if(ea!==eb)return eb===null?-1:ea===null?1:eb-ea;return Math.abs(b.r_open)-Math.abs(a.r_open);}).slice(0,8);", self.b)
        i = self.b.index("const col=(key,title,recS)=>")
        self.assertNotIn("ai_total", self.b[i:self.b.index(".slice(0,8);", i)])          # the AI score is not in the order
        self.assertIn("'<span>AI '+(fin(r.ai_total)?", self.b)
        # 「仮想の指値を毎日記録…指値の値段は注文の指示としては出さない」: counts and results only, no price
        self.assertIn("仮想の指値の記録（記録だけ・注文の指示ではありません）", self.b)
        # 「仮想の指値は2通り記録：今の形（買いは売り気配）に加えて、待つ形（買いは15:24の買い気配・空売りは売り気配…15:25までに約定したか…）」
        self.assertIn('[["now","すぐ約定（買いは売り気配・空売りは買い気配）"],["wait","待つ（買いは買い気配・空売りは売り気配）"]]', self.b)
        self.assertIn("<th>15:25までに約定</th>", self.b)
        # audit f3c6923: the tab's table headings in the cockpit's grey, like the other tables
        self.assertIn("#closing-auction-pane th{background:#1c1c1e;color:#b5b5ba;font-weight:600}", HTML)
        self.assertNotIn("lim_w", self.b)
        self.assertNotIn("指値 '", self.b)
        self.assertIn("quickHtml+'<details class=\"ca-more\"'+(caMoreOpen?' open':'')+'><summary>詳しい表", self.b)
        self.assertIn("仮想・不合格の手法（売買の合図ではありません）", self.b)


if __name__ == "__main__":
    unittest.main()
