import json
import unittest
from pathlib import Path

from scripts.weekly_tabs import SNAPSHOT_NOTE, theme_label, weekly_html

ROOT = Path(__file__).resolve().parents[1]
STORED = [
    "['フィジカルAI・ロボット', 12.14, 1, [['THK（6481）', 12.14, 4.55]]]",
    "['蓄電池・電力', 11.6, 1, [['パワーエックス（485A）', 11.6, 13.56]]]",
    "['電子部品・EV', 11.01, 1, [['ニデック（6594）', 11.01, 4.85]]]",
]


class WeeklyThemeLabelTests(unittest.TestCase):
    def test_stored_python_list_becomes_the_theme_name(self):
        self.assertEqual(
            [theme_label(item) for item in STORED],
            ["フィジカルAI・ロボット", "蓄電池・電力", "電子部品・EV"],
        )
        self.assertEqual(theme_label(("フィジカルAI・ロボット", 12.14, 1)), "フィジカルAI・ロボット")
        self.assertEqual(theme_label("電子部品・EV"), "電子部品・EV")
        self.assertEqual(theme_label({"theme": "蓄電池・電力", "score": 11.6}), "蓄電池・電力")

    def test_weekly_html_keeps_the_snapshot_numbers_and_names_the_themes(self):
        review = json.loads((ROOT / "weekly_review.json").read_text(encoding="utf-8"))
        page = weekly_html(review)
        self.assertIn("15件", page)
        self.assertIn("93.3%", page)
        self.assertIn("14.32", page)
        self.assertIn("+109,200円", page)
        self.assertIn("フィジカルAI・ロボット・蓄電池・電力・電子部品・EV", page)
        self.assertNotIn("['フィジカルAI", page)
        self.assertIn(SNAPSHOT_NOTE, page)
        self.assertIn("2026-09-19 20:17 JST", page)
        self.assertIn("実発注はロックされたままです。", page)

    def test_checked_in_page_matches_the_snapshot_label(self):
        page = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("フィジカルAI・ロボット・蓄電池・電力・電子部品・EV", page)
        self.assertNotIn("&#x27;フィジカルAI", page)
        self.assertIn("15件", page)
        self.assertIn("93.3%", page)
        self.assertIn("14.32", page)
        self.assertIn("+109,200円", page)
        script = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("function themeLabel", script)
        self.assertIn('.map(themeLabel).filter(Boolean).join("・")', script)
        self.assertNotIn("esc(themeLabel", script)
        self.assertIn("保存スナップショットです。", script)
