"""P0-V10 Kioxia forecast chart freshness (2026-10-21). Synthetic only.

The V10 folder is pinned to one commit, so the shipped kioxia_5m_calendar.json
never refreshes during the day, and its actual candles came from delayed
Yahoo data. index.html now prefers the GitHub main calendar, draws a forecast
only for today (JST), and takes actual 1-minute candles from verified MS2 bars.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class KioxiaChartSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_remote_calendar_is_the_public_main_copy_only(self):
        self.assertIn('const KIO_REMOTE_CALENDAR="https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/kioxia_5m_calendar.json";', self.page)
        self.assertIn('fetch("kioxia_5m_calendar.json?t="+Date.now())', self.page)

    def test_forecast_is_drawn_only_for_today(self):
        self.assertIn("if (best && kioPick && kioPick.today) {", self.page)
        self.assertIn("前日の予測を本日分として表示しません。", self.page)

    def test_ms2_candles_need_verified_board_and_row(self):
        block = self.page[self.page.index("// KIO_LIVE_BEGIN"):self.page.index("// KIO_LIVE_END")]
        self.assertIn("window.cockpitMs2ScreenReady?.(d)!==true||window.cockpitMs2RowReady?.(row)!==true", block)
        self.assertNotIn("real_submit_allowed=true", block)

    def test_layout_markers_kept(self):
        for marker in ('id="kio-best-path"', 'id="kio-one-minute-note"', "本日予測・実測1分足（大判）"):
            self.assertIn(marker, self.page)

    def test_kioxia_untrusted_html_fields_have_scoped_encoder_and_https_links(self):
        page = self.page
        start = page.index("// KIO_HTML_SAFE_BEGIN")
        end = page.index("// KIO_HTML_SAFE_END")
        self.assertLess(start, end)
        self.assertGreater(page.rfind("<script", start), page.rfind("</script>", start))
        block = page[page.index('document.getElementById("kio-us-context").innerHTML'):
                     page.index("}).catch(() => {", page.index('document.getElementById("kio-us-context").innerHTML'))]
        for needle in ("kioEsc(x.title)", "kioEsc(x.fact)", "kioEsc(x.expectation)",
                       "kioEsc(x.risk)", "kioEsc(x.next_checkpoint)", "kioEsc(x.impact)",
                       "kioEsc(x.kind)", "kioEsc(x.stage)", "kioEsc(mp.note",
                       "kioEsc(x.type)", "kioEsc(cs.phase)", "kioSafeHref(x.source_url)",
                       "kioSafeHref(x.url)", "kioEsc(usLabels[k] || k)"):
            self.assertIn(needle, block, needle)
        self.assertIn('u.protocol==="https:"', page[start:end])
        self.assertNotIn("+x.source_url+", block)
        self.assertNotIn("+x.title+", block)


    def test_node_runtime_cases(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable: Kioxia chart runtime cases skipped")
        p = subprocess.run([node, "--test", str(ROOT / "tests" / "v10_kioxia_chart_live.test.mjs")],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + "\n" + p.stderr[-3000:])


if __name__ == "__main__":
    unittest.main()
