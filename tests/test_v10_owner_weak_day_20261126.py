"""OWNER 2026-11-26 「朝の地合予想に、おれが苦手な日かどうかをAIコクピットに追加して」.

The PC's today_scenario_v1.json carries owner_weak_day (from the owner's own record; words only). The 今日の予測シナリオ box shows it
for today only, escaped, with no amount, no stock, no voice and no order.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class OwnerWeakDay(unittest.TestCase):
    def block(self):
        i = HTML.index("OWNER 2026-11-26 「朝の地合予想に、おれが苦手な日かどうかを追加して」")
        return HTML[i:HTML.index("document.addEventListener(\"DOMContentLoaded\",()=>{setTimeout(paint,1200)", i)]

    def test_shown_for_today_only_and_escaped(self):
        b = self.block()
        self.assertIn('String(j.owner_weak_day.day||"")===today', b)
        self.assertIn("esc(wd.level)", b)
        self.assertIn("esc(h&&h.what)", b)
        self.assertIn("wl(wd.unknown).slice(0,3).map(esc)", b)
        self.assertIn("wl(wd.watch).slice(0,3).map(esc)", b)
        self.assertIn("研究のみ・売買の合図ではありません", b)

    def test_in_both_branches_and_not_for_the_next_day(self):
        b = self.block()
        self.assertIn("・研究・売買の合図ではありません</small></div>'+weak;return;}", b)
        self.assertIn("(next?'':weak)+", b)

    def test_display_only(self):
        b = self.block()
        b = b[b.index("const wd="):b.index("const items=")]   # the code only (the comment says "no order" in words)
        for w in ("speak", "Speak", "/voice", "order", "submit", "fetch(\"/api"):
            self.assertNotIn(w, b)
        self.assertIn("#today-scenario .ts-weak{", HTML)

    def test_the_old_flags_check_stays(self):
        self.assertIn("if(!j||j.real_submit_allowed!==false||j.trade_instruction!==false||!Array.isArray(j.items)){", HTML)


if __name__ == "__main__":
    unittest.main()
