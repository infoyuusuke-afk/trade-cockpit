"""OWNER 2026-11-17 「保有中が一目でわかる形」: the swing / long virtual holds as one table line each (best first), with 含み損益,
the distance to the stop and the target, and a STOP-TARGET bar; the cards stay below, folded. Display only."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class HoldTable(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「保有中が一目でわかる形」")
        self.js = HTML[i:HTML.index("const LKEY=", i)]

    def test_one_line_per_hold_best_first(self):
        self.assertIn(".sort((a,b)=>(b.v.pct??-1e9)-(a.v.pct??-1e9))", self.js)
        for head in ("<th>銘柄</th><th>今の値</th><th>含み損益</th><th>100株</th><th>損切りまで</th><th>利確まで</th><th>損切り〜利確の位置</th><th>日数</th><th>入った日時</th>",):
            self.assertIn(head, self.js)
        self.assertIn("const rows=open.map(o=>({o,v:valued(o)}))", self.js)   # the same numbers as the cards

    def test_cards_stay_folded_and_keep_their_state(self):
        self.assertIn("holdTable(open)+'<details class=\"ht8-cards\" data-k=\"'+k+'\"'+(cardsOpen[k]?' open':'')+'><summary>カードで見る（前の形）</summary>", HTML)
        self.assertIn('if(d&&d.classList&&d.classList.contains("ht8-cards"))cardsOpen[d.dataset.k]=d.open;', self.js)

    def test_display_only(self):
        code = "\n".join(l for l in self.js.splitlines() if not l.lstrip().startswith("//"))
        for word in ("fetch(", "cockpitSpeak", "/control", "order"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
