"""OWNER 2026-11-19 「手法の説明文表示（クリックするとでよい）」: in 手法の成績（メル・仮想）, the name of each method opens its rule in
words. Display only: no voice, no order card, no order."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v10_signal_ev_table as ev  # noqa: E402

HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def block():
    a = HTML.index("const MDESC={")
    b = HTML.index("function renderSplit(")
    return HTML[a:b]


class MethodWords(unittest.TestCase):
    def test_every_method_has_words(self):
        keys = re.findall(r'\["(R1|R2|R4|R5|BRAIN|ON_LONG|ON_SHORT)","', HTML[HTML.index("const METHODS=["):HTML.index("const MDESC={")])
        self.assertEqual(keys, ["R1", "R2", "R4", "R5", "BRAIN", "ON_LONG", "ON_SHORT"])
        words = block()[:block().index("};")]
        for k in keys:
            self.assertRegex(words, r"\b%s:\"[^\"]{20,}\"" % k)

    def test_words_follow_the_rules(self):
        w = block()
        self.assertEqual((ev.RULES["R1"]["target_mult"], ev.RULES["R1"]["stop_mult"]), (2.0, 2.0))
        self.assertEqual((ev.RULES["R2"]["target_mult"], ev.RULES["R2"]["stop_mult"], ev.RULES["R2"]["max_hold_minutes"]), (3.0, 2.0, 60))
        self.assertEqual(ev.RULES["R2"]["market"], "弱い")
        self.assertEqual(ev.RULES["R4"]["min_move_pct"], 0.5)
        self.assertEqual((ev.RULES["R5"]["target_mult"], ev.RULES["R5"]["max_hold_minutes"]), (3.0, 60))
        self.assertIn("地合いが「弱い」日", w)
        self.assertIn("+0.5%以上", w)
        self.assertIn("窓を1%以上下に開けた日", w)
        self.assertIn("次の日の14:00で手じまい", w)
        self.assertIn("30分", w)

    def test_click_opens_and_closes(self):
        w = block()
        self.assertIn("button[data-mdesc]", HTML)
        self.assertIn("if(mDescOpen[k])delete mDescOpen[k];else mDescOpen[k]=1;", HTML)
        self.assertIn('data-mdesc="\'+esc(m[0])+\'"', w)
        self.assertIn("aria-expanded", w)
        self.assertEqual(w.count("+descRow(m)"), 2)   # rows with and without results
        self.assertIn("esc(MDESC[m[0]])", w)
        self.assertIn("手法（名前を押すと説明）", w)

    def test_cost_words_follow_the_code(self):
        """OWNER 2026-11-19 「説明の費用の文を、持ち越しは金利だけ・線は費用なしと正しく直して」"""
        import v10_positions_live as pos
        common = HTML[HTML.index("const MDESC_COMMON="):HTML.index("let mDescOpen")]
        self.assertIn("持ち越しは金利だけ", common)
        self.assertIn("手法A〜D・ブレインが費用込み", common)
        self.assertNotIn("100株換算・費用込み", common)
        cap = HTML[HTML.index('<div class="mc-sub">手法ごとの通算損益'):HTML.index("</div>'+lineChart(series)")]
        self.assertIn("持ち越しの線は費用なし（金利も引いていない）", cap)
        self.assertNotIn("100株換算・費用込み", cap)
        # the code the words describe: the overnight rows lose one day of interest only; the overnight line is the raw move
        self.assertEqual(set(pos.ON_RATE_DAY), {"ON_LONG", "ON_SHORT"})
        src = (ROOT / "scripts" / "v10_positions_live.py").read_text(encoding="utf-8")
        md = src[src.index("def method_days("):src.index("FOCUS_ANALYST_FILE =")]
        self.assertIn('float(r.get("return_close_pct")) / 100 * float(r.get("reference_price_1525")) * 100', md)
        self.assertNotIn("ON_RATE_DAY", md)
        self.assertIn('"return_pct": gross - strict_cost_pct(', (ROOT / "scripts" / "v10_signal_ev_table.py").read_text(encoding="utf-8"))

    def test_display_only(self):
        w = block()
        for bad in ("speak", "speechSynthesis", "order_card", "submitOrder", "fetch(", "localStorage.setItem(\"cockpitMethodDesc"):
            self.assertNotIn(bad, w[:w.index("function lineChart(")])


if __name__ == "__main__":
    unittest.main()
