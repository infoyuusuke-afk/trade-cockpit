"""OWNER 2026-11-16 「FOCUSのカードの高さをそろえて」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class FocusCardsShareOneHeight(unittest.TestCase):
    def test_every_metric_is_shown_on_both_focus_cards(self):
        # the pinned cards and the analyst cards show the same 7 metrics ("—" when missing), so no card loses a row
        self.assertIn('window.renderScalpCard({...row,_stale:false,_allMetrics:true,foot:"OWNER固定｜MS2出所・鮮度検証済｜実注文禁止"}', HTML)
        self.assertIn('window.renderScalpCard({...row,_stale:false,_allMetrics:true,foot},{label:x.side==="買い"?"BUY":"SHORT"', HTML)
        self.assertIn('const mv=v=>v==null&&x&&x._allMetrics===true?"—":v;', HTML)

    def test_cards_of_a_grid_stretch_to_one_height(self):
        self.assertIn("#focus-owner-panel .cc-grid{grid-auto-rows:1fr;align-items:stretch}"
                      "#focus-owner-panel .focus-pin>.cc-card{flex:1 1 auto}"
                      "#focus-owner-panel .cc-card>.cc-foot{margin-top:auto}", HTML)


if __name__ == "__main__":
    unittest.main()
