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

    def test_layout_only(self):
        for word in ("<script", "fetch(", "renderCockpitCard", "cockpitSpeak", "/control"):
            self.assertNotIn(word, self.css)


if __name__ == "__main__":
    unittest.main()
