"""OWNER 2026-11-17 「勝ったか、負けたか一目でわかる形」: the overnight comparison (OVERNIGHT 5) is a kept table with a 結果 mark
(勝ち / 負け / 入れず) first, the line's edge in the same colour and the day's count and total above. Display only."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class OvernightWinLose(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「勝ったか、負けたか一目でわかる形」")
        self.b = HTML[i:HTML.index("</script>", i)]

    def test_result_mark_and_kept_table(self):
        self.assertIn('return !(Number(v.shares)>0)?"none":Number(v.yen)>0?"win":Number(v.yen)<0?"lose":"even";', self.b)
        self.assertIn('t.setAttribute("data-keep-table","");', self.b)
        # OWNER 2026-11-18: the 0-share mark is the sizing's own words (枠が足りず0株 …), not 入れず
        self.assertIn('{win:"勝ち",lose:"負け",even:"引き分け",none:((r["通常"]||{}).zero||{}).words||"0株"}[k]', self.b)
        self.assertIn('txt(head,"b","勝ち "+cnt("win"),"up");txt(head,"b","負け "+cnt("lose"),"dn");', self.b)

    def test_colours(self):
        self.assertIn("#on-compare tr.oc-win td:first-child{border-left-color:#5cddb0}#on-compare tr.oc-lose td:first-child{border-left-color:#f0616c}", HTML)

    def test_display_only(self):
        code = "\n".join(l for l in self.b.splitlines() if not l.lstrip().startswith("//"))
        for word in ("innerHTML", "cockpitSpeak", "RssOrder", "/control"):
            self.assertNotIn(word, code)


if __name__ == "__main__":
    unittest.main()
