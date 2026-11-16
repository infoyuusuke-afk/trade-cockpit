"""OWNER 2026-11-17 「文字の配置バランスが変だから、もっと丁寧に修正」: the state band is two fixed rows (title and switches on
row 1, the lamps under a thin line on row 2, each dot beside its label, a red lamp's explanation under its own label)."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class StateBandLayout(unittest.TestCase):
    def setUp(self):
        i = HTML.index("「文字の配置バランスが変だから、もっと丁寧に修正」")
        self.css = HTML[i:HTML.index("#tl-history.tl-empty", i)]

    def test_two_fixed_rows(self):
        self.assertIn('grid-template-areas:"lamp title ctl time" "st st st st"', self.css)
        self.assertIn("#unified-mode>.unified-mode-controls{grid-area:ctl;margin-left:0!important}", self.css)
        self.assertIn("#unified-mode>.tl-status-lamps{grid-area:st;", self.css)
        self.assertIn("border-top:1px solid #26282d!important", self.css)

    def test_dot_beside_the_label_and_type_line_on_its_own_line(self):
        self.assertIn("#unified-mode .tl-status-lamps .brain-lamp{align-items:flex-start!important}", self.css)
        self.assertIn("#unified-mode #trade-type-line{flex:1 1 100%!important}", self.css)
        self.assertIn("#unified-mode #trade-type-line:empty{display:none}", self.css)

    def test_owner_points_1_to_4(self):
        # ① the 「LIVE売買禁止」 label has the switches' height (30px) on the same centre line
        self.assertIn("#unified-mode>#unified-mode-time{grid-area:time;white-space:nowrap;display:inline-flex;align-items:center;box-sizing:border-box;height:30px;", self.css)
        # ③ the red lamp's list starts at the left edge of its label (no indent of its own)
        self.assertIn("#unified-mode .tl-status-lamps .brain-lamp.red small{margin:4px 0 0!important;display:block!important}", self.css)
        # ④ two sizes only: 15px for the state and the three lamp names, 12px for everything else
        self.assertIn("#unified-mode #unified-mode-title,#unified-mode .tl-status-lamps .brain-lamp b{font-size:15px!important}", self.css)
        self.assertIn("#unified-mode small,#unified-mode #unified-mode-note,#unified-mode .type-line{font-size:12px!important}", self.css)

    def test_layout_only(self):
        for word in ("<script", "fetch(", "renderCockpitCard", "cockpitSpeak", "/control"):
            self.assertNotIn(word, self.css)


if __name__ == "__main__":
    unittest.main()
