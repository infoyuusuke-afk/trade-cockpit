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


class StaleSnapshotNotShownAsCurrent(unittest.TestCase):
    def test_external_rankings_have_no_0925_tables(self):
        for sid in ("market-ranking-watch", "tradingview-screener-watch"):
            with self.subTest(section=sid):
                body = section(sid)
                self.assertNotIn("<table>", body)
                self.assertIn("当日のランキングは未取得です", body)
                self.assertIn("過去資料・当日値ではありません", body)
        self.assertNotIn("フルヤ金属", HTML)
        self.assertNotIn("Birdman", HTML)

    def test_usd_jpy_0925_value_is_not_displayed(self):
        body = section("strong-yen-top5")
        self.assertNotIn("USD/JPY 158.7", body)
        self.assertIn("USD/JPY：当日値は未取得", body)
        self.assertIn("2026-09-25 時点の過去資料", body)

    def test_header_and_footer_stay_labelled_as_past(self):
        self.assertIn("静的分析作成：2026-09-25 10:41:50 JST（本日のLIVE市場情報ではありません）", HTML)
        self.assertIn("静的HTML作成：2026-09-25 10:41:50 JST／LIVE未認証", HTML)

    def test_remaining_0925_mentions_are_all_marked_past(self):
        for line in HTML.splitlines():
            if "2026-09-25" in line:
                with self.subTest(line=line.strip()[:60]):
                    self.assertTrue(any(k in line for k in ("過去", "本日のLIVE市場情報ではありません", "LIVE未認証")), line[:120])


class StaticSnapshotSectionsLabelled(unittest.TestCase):
    """OWNER 2026-10-21: every section whose numbers are baked into the page
    (the 2026-09-25 snapshot, e.g. 地合いサマリー on 検証・除外, 資金流入テーマ
    TOP5 on 国策) says it is 9/25 past data. Runtime-filled sections are not."""

    def sections(self):
        import re
        main = HTML[HTML.index("<main"):HTML.index("</main>")]
        for m in re.finditer(r'<section([^>]*)>(.*?)</section>', main, re.S):
            yield m.group(1), m.group(2)

    def test_named_owner_sections_are_labelled(self):
        for title in ("① 地合いサマリー", "② 当日資金流入テーマ TOP5", "国策テーマ・実戦優先順位"):
            with self.subTest(section=title):
                body = [b for _, b in self.sections() if title in b][0]
                self.assertIn("9/25時点の過去データ", body)

    def test_every_static_table_section_is_labelled_or_already_marked_past(self):
        import re
        for attrs, body in self.sections():
            ids = set(re.findall(r'id="([^"]+)"', body))
            dynamic = any(('getElementById("' + i + '")') in HTML for i in ids)
            if dynamic or "<tr" not in body:
                continue
            with self.subTest(section=(re.findall(r"<h2[^>]*>(.*?)</h2>", body) or [attrs])[0][:30]):
                self.assertTrue("9/25時点の過去データ" in body or "過去資料" in body)

    def test_live_sections_are_not_labelled_past(self):
        for sid in ("ms2-live-top5", "overnight-top5", "watchlist-100", "premarket-gap-ranking", "focus-owner-panel"):
            with self.subTest(section=sid):
                self.assertNotIn("9/25時点の過去データ", section(sid))


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
