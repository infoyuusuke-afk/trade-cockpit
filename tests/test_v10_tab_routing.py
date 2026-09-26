from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class V10TabRoutingTests(unittest.TestCase):
    def test_research_tab_exists_in_source_and_generated_page(self):
        for rel in ("scripts/weekly_tabs.py", "index.html"):
            text = read(rel)
            self.assertIn('data-tab="research"', text, rel)
            self.assertIn('"events","research","correlation"', text, rel)
            self.assertIn('intros.research=["RESEARCH"', text, rel)

    def test_next_theme_routes_to_research_not_realtime(self):
        for rel in ("scripts/weekly_tabs.py", "index.html"):
            text = read(rel)
            self.assertIn('else if(s.id==="next-theme-radar")k="research";', text, rel)
            self.assertNotIn(
                's.id==="data-quality-gate"||s.id==="next-theme-radar"',
                text,
                rel,
            )

    def test_visible_data_quality_gate_is_removed_from_tab_layout(self):
        for rel in ("scripts/weekly_tabs.py", "index.html"):
            text = read(rel)
            self.assertIn(
                'else if(s.id==="data-quality-gate"){s.remove();return;}',
                text,
                rel,
            )

    def test_pts_and_ir_pts_are_moved_to_event5_without_changing_live_ids(self):
        for rel in ("scripts/weekly_tabs.py", "index.html"):
            text = read(rel)
            self.assertIn('eventFeeds.id="event-overnight-feeds"', text, rel)
            self.assertIn('panes["event-hot"].appendChild(eventFeeds)', text, rel)
            self.assertIn('document.getElementById("ms2-pts-cards")', text, rel)
            self.assertIn('document.getElementById("ms2-ir-pts-cards")', text, rel)
            self.assertIn("EVENT DISCOVERY", text, rel)

    def test_pts_live_loader_ids_still_exist_in_generator(self):
        generator = read("scripts/update.py")
        for needle in (
            'id="ms2-pts-cards"',
            'id="ms2-ir-pts-meta"',
            'id="ms2-ir-pts-cards"',
            'document.getElementById("ms2-pts-cards")',
            'document.getElementById("ms2-ir-pts-cards")',
        ):
            self.assertIn(needle, generator)


if __name__ == "__main__":
    unittest.main()
