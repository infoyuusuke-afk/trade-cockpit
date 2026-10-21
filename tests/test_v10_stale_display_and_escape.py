"""FIX-02 / FIX-03 static contracts for the V10 screen (2026-10-21).

FIX-02: the 2026-09-25 Yahoo ranking, TradingView screener and USD/JPY values
are not shown as if current. The header/footer keep their explicit
"past analysis" labels (they are hidden by the lamp-bar CSS, never relabelled
as today). FIX-03: the KIOXIA renderer escapes external JSON fields and only
links http(s) URLs; the behaviour is executed in v10_kioxia_render_escape.test.mjs.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")


def section(sid):
    start = HTML.index('<section id="' + sid + '"')
    return HTML[start:HTML.index("</section>", start)]


class StaticSnapshotRemoved(unittest.TestCase):
    """OWNER 2026-10-21: the 2026-09-25 snapshot sections are never updated in V10,
    so they are removed (地合いサマリー, 資金流入テーマTOP5, 国策, rankings, 市場警報 ...).
    Tabs that only held them are hidden; MS2 LIVE and runtime-filled sections stay."""

    def test_snapshot_sections_and_numbers_are_gone(self):
        for text in ("① 地合いサマリー", "② 当日資金流入テーマ TOP5", "<h2>国策テーマ・実戦優先順位", "🚨 市場警報",
                     "外部ランキング発掘", "<h2>円高恩恵銘柄 TOP5", "フルヤ金属", "Birdman", "USD/JPY 158.7",
                     "snapshot-past", 'id="sector-rotation"', 'id="investor-regime"', 'id="us-smr-watch"'):
            with self.subTest(text=text):
                self.assertNotIn(text, HTML)

    def test_only_header_and_footer_still_name_0925_and_say_past(self):
        lines = [l for l in HTML.splitlines() if "2026-09-25" in l and not l.lstrip().startswith("//")]
        self.assertEqual(len(lines), 2)
        self.assertIn("静的分析作成：2026-09-25 10:41:50 JST（本日のLIVE市場情報ではありません）", HTML)
        self.assertIn("静的HTML作成：2026-09-25 10:41:50 JST／LIVE未認証", HTML)

    def test_snapshot_only_tabs_are_hidden_and_live_sections_stay(self):
        self.assertIn('const SNAPSHOT_ONLY_TABS=["strong-yen","us-smr","investor-regime","expansion","policy",...policyTabs];', HTML)
        for sid in ("ms2-live-top5", "overnight-top5", "watchlist-100", "premarket-gap-ranking", "focus-owner-panel",
                    "kioxia-5m-calendar", "weekly-review", "event-calendar", "correlation-monitor", "world-market-live"):
            with self.subTest(section=sid):
                self.assertIn('id="' + sid + '"', HTML)


class KioxiaRendererEscapes(unittest.TestCase):
    def test_no_raw_external_fields_in_catalyst_markup(self):
        start = HTML.index('document.getElementById("kio-catalyst-list").innerHTML=')
        line = HTML[start:HTML.index("\n", start)]
        for field in ("date", "kind", "stage", "title", "fact", "expectation", "risk", "next_checkpoint", "impact"):
            self.assertNotIn('"+x.' + field + '+"', line)
        self.assertIn("kioSafeUrl(x.source_url)", line)
        self.assertIn("const url=kioSafeUrl(x.url);", HTML)

    @unittest.skipUnless(shutil.which("node"), "node not installed; the CI job runs it")
    def test_hostile_values_render_as_text(self):
        p = subprocess.run(["node", "--test", str(ROOT / "tests" / "v10_kioxia_render_escape.test.mjs")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout[-6000:] + "\n" + p.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
