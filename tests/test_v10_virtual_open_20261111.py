"""OWNER 2026-11-11 「メルの成績はずっと見れるようにして開いてる状態がデフォルト、おすと閉じる」. Display only; no orders."""
import unittest
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


class VirtualResultsOpen(unittest.TestCase):
    def test_fold_opens_on_load_and_a_press_closes_it(self):
        self.assertIn('if(!fold.dataset.tlInit){fold.dataset.tlInit="1";fold.open=true;', HTML)
        self.assertIn('h.textContent=fold.open?"押すと閉じる":"押すと開く"', HTML)

    def test_capital_block_open_by_default_and_not_remembered_closed(self):
        self.assertIn("let capOpen=true;", HTML)
        self.assertNotIn('localStorage.getItem("cockpitCapOpenV1")', HTML)
        self.assertNotIn('localStorage.setItem("cockpitCapOpenV1"', HTML)


if __name__ == "__main__":
    unittest.main()
