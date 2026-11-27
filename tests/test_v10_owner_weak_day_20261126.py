"""OWNER 2026-11-26 「朝の地合い予想の欄に『今日は苦手な日か』を1行足す版を作って。8:50に分かるものだけ使う…当てはまる項目を並べて
『苦手な日／ふつう／得意な日』を出す。水曜は入れない。表示だけで、音声・注文・メルは変えない。自分の収支はPCの中だけで読み、GitHubには入れない」.

The PC's today_scenario_v1.json carries owner_weak_day (words only, made on the PC). The 今日の予測シナリオ box shows it for today only,
escaped, with no amount, no stock, no voice and no order. Nothing in the repo reads the owner's account or trade record for this.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
MARK = "OWNER 2026-11-26 「朝の地合い予想の欄に『今日は苦手な日か』を1行足す版を作って"


class OwnerWeakDay(unittest.TestCase):
    def block(self):
        i = HTML.index(MARK)
        return HTML[i:HTML.index("document.addEventListener(\"DOMContentLoaded\",()=>{setTimeout(paint,1200)", i)]

    def code(self):
        b = self.block()
        return b[b.index("const wd="):b.index("const items=")]   # the code only (the comment says "no order" in words)

    def test_shown_for_today_only_and_escaped(self):
        c = self.code()
        self.assertIn('String(j.owner_weak_day.day||"")===today', c)
        self.assertIn("esc(wd.level)", c)
        self.assertIn("esc(h&&h.side)+'：'+esc(h&&h.what)", c)
        self.assertIn("wl(wd.unknown).slice(0,4).map(esc)", c)
        self.assertIn("研究のみ・売買の合図ではありません", c)

    def test_three_levels(self):
        c = self.code()
        self.assertIn('wd.level==="苦手な日"?" bad":wd.level==="得意な日"?" good":""', c)
        self.assertIn("当てはまる項目なし", c)
        self.assertNotIn("水曜", c)

    def test_in_both_branches_and_not_for_the_next_day(self):
        b = self.block()
        self.assertIn("・研究・売買の合図ではありません</small></div>'+weak;return;}", b)
        self.assertIn("(next?'':weak)+", b)

    def test_display_only(self):
        c = self.code()
        for w in ("speak", "Speak", "/voice", "order", "submit", "fetch(", "mel", "Mel"):
            self.assertNotIn(w, c)
        self.assertIn("#today-scenario .ts-weak{", HTML)
        self.assertIn("#today-scenario .ts-weak.good{", HTML)

    def test_the_old_flags_check_stays(self):
        self.assertIn("if(!j||j.real_submit_allowed!==false||j.trade_instruction!==false||!Array.isArray(j.items)){", HTML)
        self.assertLess(HTML.index("if(!j||j.real_submit_allowed!==false"), HTML.index(MARK))


if __name__ == "__main__":
    unittest.main()
