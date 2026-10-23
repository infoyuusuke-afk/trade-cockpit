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
        # drawn from the kept list; read again at most once a minute and only where fetch exists
        self.assertIn('if(typeof fetch==="function"&&!(Date.now()-(window.__overnightHoldsAt||0)<60000))', html)
        self.assertIn("現在値はMS2が止まっているため表示しません。", html)

    def test_focus_layout(self):
        html = _html()
        self.assertIn("#focus-owner-panel .ec-controls{display:flex;align-items:center;gap:10px;", html)
        self.assertIn("#focus-owner-panel select{min-width:240px;height:34px;", html)


class KioxiaTab(unittest.TestCase):
    def test_only_the_live_blocks_and_stale_forecast_really_hidden(self):
        html = _html()
        # [hidden] loses to grid / flex display rules, so the forecast blocks get display:none
        self.assertIn('["kio-decision-panel", "kio-decision-reason", "kio-live-monitor", "kio-best-analog"].forEach(id => { const el = document.getElementById(id); if (el) el.style.display = "none"; });', html)
        self.assertIn("#kioxia-5m-calendar .kio-detail-grid{display:none!important}", html)
        self.assertIn("キオクシアHD（285A）板・歩み値・サイン ", html)
        for keep in ('id="kio-ms2-orderflow"', 'id="kio-watcher-signal"', 'id="kio-watcher-board"', 'id="kioxia-supply"'):
            self.assertIn(keep, html)


class Calendars(unittest.TestCase):
    def test_refined_calendar_styles(self):
        # OWNER 2026-10-24 「安っぽい、もっと洗練された作りこみ」
        html = _html()
        self.assertIn(".event-months{gap:14px!important;grid-template-columns:1fr!important}", html)
        self.assertIn(".event-chip.high{background:#22171a!important;border-left-color:#ff5a5f!important;", html)
        # earnings-calendar.js stays the pinned source; the look is set from index.html
        self.assertIn("const heat=count>=400?4:count>=150?3:count>=50?2:count>0?1:0;", html)
        self.assertIn("html body #earnings-calendar-panel .ec-day.ec-weekend{", html)
        self.assertNotIn("ec-weekend", (ROOT / "earnings-calendar.js").read_text(encoding="utf-8"))


class WorldAndCorrelationOff(unittest.TestCase):
    def test_hidden(self):
        # OWNER 2026-10-24 「あやしいからいらない」「これもいらないが、相関性を検査・分析する仕組みがあやしい」
        self.assertIn("#world-market-live,#correlation-monitor{display:none!important}", _html())


class WickFeed(unittest.TestCase):
    def test_fed_list_with_date(self):
        # OWNER 2026-10-24 「最重要、特に昨日のザラバがセリクラとなり反転となるか」
        from scripts import v10_public_feed_sync as feed
        sig = {"updated_at": "2026-10-23 21:00:37 JST", "daily_capitulation_reversals": [
            {"name": "データセクション（3905）", "score": 100, "close": 1530.0, "signal_date": "2026-10-23", "extra": 1}]}
        v = feed.wick_view(sig)
        self.assertEqual(v["daily_capitulation_reversals"][0]["name"], "データセクション（3905）")
        self.assertNotIn("extra", v["daily_capitulation_reversals"][0])
        self.assertEqual((v["real_submit_allowed"], v["trade_instruction"]), (False, False))
        html = _html()
        self.assertIn('fetch("wick_watch.json?t=" + Date.now())', html)
        self.assertIn('"wick_watch.json": "lower-wick-reversal"', html)
        self.assertIn("判定日 ", html)
        gw = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertEqual(gw.count("'wick_watch.json'"), 2)


class AccumulationEvent5Gpt(unittest.TestCase):
    def test_accumulation_fed(self):
        # OWNER 2026-10-24 「本当に買い集めなのか…継続監視銘柄で大口が定期的に吸収してるのか」
        from scripts import v10_public_feed_sync as feed
        v = feed.accumulation_view({"updated_at": "2026-10-23 21:00:37 JST", "large_lot_accumulation": [{"name": "A（1111）"}],
                                    "large_lot_accumulation_note": "n", "credit_supply_updated_at": "c"})
        self.assertEqual((len(v["large_lot_accumulation"]), v["real_submit_allowed"]), (1, False))
        html = _html()
        self.assertIn('fetch("accumulation_watch.json?t=" + Date.now())', html)
        self.assertIn("window.renderAccumulation(window.accFedData || d);", html)
        self.assertIn('"accumulation_watch.json": "large-lot-accumulation"', html)
        self.assertEqual((ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig").count("'accumulation_watch.json'"), 2)

    def test_event5_dated_daily_cards(self):
        # OWNER 2026-10-24 「古くないか」 (EVENT 5)
        html = _html()
        start = html.index("window.renderEvent5 = rows => {")
        fn = html[start:html.index('document.getElementById("speculative-theme-watch").innerHTML =', start)]
        self.assertIn("<span>終値（' + e(date) + '）<b>", fn)
        self.assertIn("日足（ライブの値段ではありません）", fn)
        self.assertNotIn("_staticCurrent", fn)

    def test_gpt_panel_shows_the_tasks(self):
        # OWNER 2026-10-24 「アナリストは自動になったはず」
        html = _html()
        self.assertIn("<h3>GPTタスクの答え（自動・ChatGPTアプリ）</h3>", html)
        self.assertIn("GPTタスクの答えは、まだ届いていません", html)


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
