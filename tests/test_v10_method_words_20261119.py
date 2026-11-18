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

    def test_display_only(self):
        w = block()
        for bad in ("speak", "speechSynthesis", "order_card", "submitOrder", "fetch(", "localStorage.setItem(\"cockpitMethodDesc"):
            self.assertNotIn(bad, w[:w.index("function lineChart(")])


if __name__ == "__main__":
    unittest.main()
