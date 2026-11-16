"""OWNER 2026-11-16 「週の注意日も追加、エヌビディア決算など影響がありそうな事柄が抜けている」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class VolatileDaysWeekAndOverseas(unittest.TestCase):
    def test_this_week_also_medium_and_the_us_results(self):
        block = HTML.split("「価格が大きく変動しそうな日をしっかりピックアップして表示」", 1)[1].split("})();", 1)[0]
        self.assertIn('{date:"2026-11-18",when:"6:20ごろ",what:"NVIDIAの決算（米11/17引け後・説明会7:00）"}', block)
        self.assertIn('{date:"2026-12-10",when:"朝",what:"Broadcomの決算（米12/9引け後）"}', block)
        self.assertNotIn("Micron", block.replace("(Micron: not announced yet on 2026-11-16)", ""))   # no estimated date
        self.assertIn("const week=add(today,7);", block)
        self.assertIn('(e.impact==="高"||(e.impact==="中"&&e.date<=week))&&e.date>=today&&e.date<=end', block)
        self.assertIn("OVERSEAS.forEach(o=>{if(o.date>=today&&o.date<=end)at(o.date).push({when:o.when,what:o.what});});", block)
        self.assertIn("今週は影響「中」も、海外の大型決算（会社が発表した日だけ）", HTML)
        for banned in ("cockpitSpeak", "RssOrder"):
            self.assertNotIn(banned, block)


if __name__ == "__main__":
    unittest.main()
