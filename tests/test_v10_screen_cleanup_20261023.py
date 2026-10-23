"""OWNER 2026-10-23 夜 「1つ目で進めて。FOCUSと占いは残す。8銘柄は今のまま」:
the 注目 frames, the JNX (PTS) code fix and taking stale / unusable sections off the screen.
Static and synthetic checks only."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
WINDOWS = os.name == "nt" and shutil.which("powershell")


def _html():
    return HTML.read_text(encoding="utf-8")


def _collector():
    return COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


class AttentionFrames(unittest.TestCase):
    def test_box_and_held_rows_use_the_plain_frame(self):
        html = _html()
        self.assertNotIn(".attention-box.att-held", html)
        self.assertNotIn(".attention-row.att-held{", html)
        self.assertIn("<i>保有</i>", html)   # the 保有 label still marks a held row
        self.assertIn(".attention-row.att-hot-long{border-color:#35e2ae}", html)
        self.assertIn(".attention-row.att-hot-short{border-color:#ff5a5f}", html)


class StaleSectionsHidden(unittest.TestCase):
    def test_signals_json_sections_go_together(self):
        html = _html()
        start = html.index('["entered-signals", "prepared-signals", "overnight-long", "overnight-short"')
        block = html[start:html.index("forEach", start)]
        for sid in ("hammer-signals", "long-term-ma-rebound", "tv-watchlist-export", "swing-howto", "selection-logic"):
            self.assertIn('"%s"' % sid, block)
        self.assertIn('<section id="swing-howto" class="card wide"><h2>⑦ AIスイングサインの使い方</h2>', html)
        self.assertIn('<section id="selection-logic" class="card"><h2>⑬ 選定ロジック</h2>', html)
        # still only while signals.json is older than 24 hours
        self.assertIn("if (!(Date.now() - sigAt < 864e5)) {", html)

    def test_focus_and_fortune_stay(self):
        html = _html()
        for keep in ("FOCUS", "本格占い"):
            self.assertIn(keep, html)
        # neither is added to the hide list
        start = html.index('["entered-signals", "prepared-signals"')
        block = html[start:html.index("forEach", start)]
        self.assertNotIn("focus", block.lower())
        self.assertNotIn("fortune", block.lower())

    def test_weekly_review_hidden(self):
        self.assertIn('<section id="weekly-review" class="panel" hidden>', _html())

    def test_kioxia_forecast_only_for_today(self):
        html = _html()
        self.assertIn("const hideStaleKioxiaForecast = date => {", html)
        self.assertIn('if (date === today) return;', html)
        self.assertIn('.catch(() => hideStaleKioxiaForecast(null));', html)
        # the Watcher panels in the same section are not hidden
        fn = html[html.index("const hideStaleKioxiaForecast"):html.index("fetch(\"kioxia_5m_calendar.json?t=\" + Date.now()).then(r => r.json()).then(d => setTimeout")]
        self.assertNotIn("kioxia-5m-calendar\").hidden", fn)
        self.assertNotIn("closest(\"section\")", fn)

    def test_past_unconfirmed_events_not_listed(self):
        html = _html()
        self.assertIn('(d.unverified || []).filter(x => !/^\\d{4}-\\d{2}-\\d{2}$/.test(String(x.effective_date || "")) || String(x.effective_date) >= eventToday)', html)


class OvernightAndFocus(unittest.TestCase):
    def test_fixed_holds_listed_while_ms2_is_not_live(self):
        html = _html()
        self.assertIn("15:25確定の持ち越し（仮想・", html)
        self.assertIn("現在値はMS2が止まっているため表示しません。", html)

    def test_focus_layout(self):
        html = _html()
        self.assertIn("#focus-owner-panel .ec-controls{display:flex;align-items:center;gap:10px;", html)
        self.assertIn("#focus-owner-panel select{min-width:240px;height:34px;", html)


class JnxCodes(unittest.TestCase):
    def test_static(self):
        text = _collector()
        self.assertNotIn("-replace '\\\\.T$'", text)   # the old literal-backslash pattern
        self.assertIn("$jnxTicker = ConvertTo-JnxTicker ([string]$stocks[$i].Ticker)", text)
        self.assertIn("if ($jnxFirstCode -cne $jnxExpectedCode) {", text)
        self.assertIn("if ($jnxRewrite) {", text)

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_conversion(self):
        text = _collector()
        start = text.index("function ConvertTo-JnxTicker")
        fn = text[start:text.index("\n}\n", start) + 2]
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "t.ps1"
            script.write_text(fn + "\nforeach ($c in '8035.T','285A.T',' 6857.T ','9984') { Write-Output (ConvertTo-JnxTicker $c) }\n",
                              encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                 capture_output=True, text=True, timeout=60).stdout.split()
        self.assertEqual(out, ["8035.JNX", "285A.JNX", "6857.JNX", "9984.JNX"])


if __name__ == "__main__":
    unittest.main()
