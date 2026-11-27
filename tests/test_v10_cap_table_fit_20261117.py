"""OWNER 2026-11-17 「資金別の５００万がこの画面サイズだとみれない」: the 資金別 table fits its box at 1130 px (the columns share the box,
long notes wrap in their own cell, bracket notes on a line of their own). Display only."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class CapTableFits(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「資金別の５００万がこの画面サイズだとみれない」")
        self.css = HTML[i:HTML.index("</style>", i)]

    def test_columns_share_the_box_and_wrap(self):
        self.assertIn("#cap-compare table{table-layout:fixed}", self.css)
        self.assertIn("#cap-compare th,#cap-compare td{white-space:normal;overflow-wrap:break-word;vertical-align:top}", self.css)
        self.assertIn("#cap-compare th:first-child{width:28%}", self.css)
        self.assertIn("#cap-compare td>span.g{display:block}", self.css)

    def test_owner_points_1_to_3(self):
        # ① the three sizes share one width ③ the names may wrap, the amounts never do
        self.assertIn("#cap-compare th:not(:first-child),#cap-compare td:not(:first-child){width:24%;white-space:nowrap}", self.css)
        # ② the 必要な資金 note moved from the 100株 heading to a line under the table, same words
        self.assertIn("'<th>'+esc(s.label)+(s.capital?'・信用':'')+'</th>'", HTML)
        self.assertIn("'の必要な資金　現物 '+man(s.peak_amount)+'／信用 約'+man(s.peak_amount/(cap.margin_mult||3.3))", HTML)
        self.assertIn("'</table>'+capNeed+heldBlock(S)+'", HTML)

    def test_layout_only(self):
        for word in ("<script", "fetch(", "renderCockpitCard", "cockpitSpeak", "/control"):
            self.assertNotIn(word, self.css)


if __name__ == "__main__":
    unittest.main()
