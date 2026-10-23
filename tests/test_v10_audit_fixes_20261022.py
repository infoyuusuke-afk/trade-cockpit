"""OWNER 2026-10-22 audit fixes ①-④ and safety S1-S3. Synthetic data only.

① Gateway 28581: git is asked once at start-up; a JSON file is parsed again only
  when its write time or length changed; one /health looks the processes up in
  one query. ② The screen no longer speaks (Radar WATCH/HOT, KIOXIA signal).
③ The Brain card shows ev_pct as 期待値 and score_pct as 順位スコア. ④ Shadow
  downtime and uptime do not count time after 15:30 (D-035).
S1 Safe Stop quits Excel only when no other workbook is open in it. S2 START
  refuses while another Excel runs. S3 Safe Stop stops nothing while another
  Excel runs. CI PASS approves no deployment.
"""
import importlib.util
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
STOP = ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
START = ROOT / "downloads" / "START_AI_COCKPIT_V10.ps1"
CONTROLLER = ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"
JST = timezone(timedelta(hours=9))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load("v10_shadow_supervisor_audit", "scripts/ai_shadow_supervisor.py")


def _text(path):
    return path.read_text(encoding="utf-8-sig")


def _function_text(text, name):
    match = re.search(r"^function " + re.escape(name) + r"\b", text, re.MULTILINE)
    if match is None:
        raise AssertionError("FUNCTION_MISSING " + name)
    return text[match.start():text.index("\n}\n", match.start()) + 2]


class GatewaySpeed(unittest.TestCase):
    def test_git_is_read_once_at_start(self):
        text = _text(GATEWAY)
        self.assertEqual(text.count("Get-GitInfo $RepoRoot"), 1)
        self.assertLess(text.index("$script:GitInfo = Get-GitInfo $RepoRoot"), text.index("$listener.Start()"))
        self.assertEqual(text.count("$git = $script:GitInfo"), 2)

    def test_json_reads_use_the_change_cache(self):
        text = _text(GATEWAY)
        self.assertNotRegex(text, r"= Read-JsonUtf8 \$")
        self.assertIn("$healthLive = Read-JsonUtf8Cached $liveJson", text)
        self.assertIn("Read-FileCached $Path 'snapshot'", _function_text(text, "Read-LiveSnapshot"))

    def test_one_process_query_per_health(self):
        text = _text(GATEWAY)
        for name in ("Test-HealthProcess", "Test-ControllerHealthProcess"):
            body = _function_text(text, name)
            self.assertIn("Get-HealthProcess $ProcessId", body)
            self.assertNotIn("Get-CimInstance", body)
        health = text[text.index("if ($path -eq '/health') {"):text.index("if ($path -eq '/live_ms2.json') {")]
        self.assertEqual(health.count("$script:HealthProcessMemo = $null"), 3)  # start, failure, before reply
        self.assertIn("Set-HealthProcessMemo", health)

    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell 5.1 only")
    def test_cache_rereads_only_a_changed_file(self):
        text = _text(GATEWAY)
        funcs = "\n".join(_function_text(text, n) for n in
                          ("Get-FileStamp", "Read-FileCached", "ConvertFrom-Utf8JsonBytes", "Read-JsonUtf8Cached"))
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "x.json"
            data.write_text('{"v":1}', encoding="utf-8")
            script = Path(d) / "t.ps1"
            script.write_text("$ErrorActionPreference='Stop'\n$script:FileReadCache=@{}\n" + funcs + r"""
$p = '""" + str(data) + r"""'
$a = Read-JsonUtf8Cached $p
$b = Read-JsonUtf8Cached $p
Write-Output ("SAME=" + [object]::ReferenceEquals($a, $b))
[IO.File]::WriteAllText($p, '{"v":22}')
(Get-Item -LiteralPath $p).LastWriteTimeUtc = (Get-Date).ToUniversalTime().AddSeconds(5)
$c = Read-JsonUtf8Cached $p
Write-Output ("NEW=" + $c.v)
""", encoding="utf-8-sig")
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                 capture_output=True, text=True, timeout=60)
            self.assertIn("SAME=True", out.stdout, out.stderr)
            self.assertIn("NEW=22", out.stdout, out.stderr)


class ScreenVoice(unittest.TestCase):
    def test_radar_and_kioxia_do_not_speak(self):
        self.assertNotIn("cockpitSpeak", (ROOT / "opportunity_radar.js").read_text(encoding="utf-8"))
        self.assertNotIn("speechText", (ROOT / "opportunity_radar.js").read_text(encoding="utf-8"))
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("cockpitSpeak?.(", html)
        self.assertNotIn("kioVoiceSignalState", html)


class BrainCardLabels(unittest.TestCase):
    def test_ev_and_ranking_score_are_separate(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("'<strong>期待値 '+evPct(p.ev_pct)", html)
        self.assertIn("'<small>順位スコア '+evPct(p.score_pct)", html)
        self.assertNotIn("期待値 '+evPct(p.score_pct)", html)

    def test_brain_exclusion_reason_says_ranking_score(self):
        text = (ROOT / "scripts" / "v10_brain_core.py").read_text(encoding="utf-8")
        self.assertIn('"順位スコア%+.3f%%（基準%.2f%%未満）"', text)
        self.assertNotIn('"期待値%+.3f%%', text)


class ScreenStaysPut(unittest.TestCase):
    """OWNER 2026-10-23 「場中に画面がころころ変わる」: no forced tab jumps on refresh."""

    def test_no_meta_refresh_and_launch_tab_only_once(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('http-equiv="refresh"', html)
        self.assertIn('const requested=!firstOpen?null:(qs.get("brain")==="1"?"brain":(qs.get("live")==="1"?"scalp":null));', html)
        self.assertIn("if(Date.now()-lastTouch<120000){setTimeout(quietReload,60000);return;}", html)
        self.assertIn('sessionStorage.setItem("cockpitScrollY",String(Math.round(window.scrollY)))', html)

    def test_stale_checkout_signal_lists_are_not_shown(self):
        # OWNER 2026-10-23 「ここの表示って古くないのか」: ⑧⑨ from a signals.json older than 24 h
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("if (!(Date.now() - sigAt < 864e5)) {", html)
        self.assertIn("古いデータのため表示しません（更新 ", html)

    def test_compact_headings_and_one_line_attention_box(self):
        # OWNER 2026-10-23 「無駄な情報はコンパクトにしろ」
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(".pane-intro>span{display:none}", html)
        self.assertIn(".focus-empty{padding:10px 12px!important;font-size:13px!important}", html)
        self.assertIn("#attention-rows:empty{display:none}", html)
        # OWNER 2026-10-23: a gap under the tab bar; status bar and 注目 share one corner radius
        self.assertIn(".unified-mode-wrap:not(.attention-wrap){padding-top:12px!important}", html)
        self.assertIn("border-radius:14px!important}", html)
        self.assertIn(".attention-box{margin:0 0 8px;padding:8px 16px;border:1px solid #303033;border-radius:14px;", html)
        # OWNER 2026-10-23: room around the heading line; the 注目 frame copies the status bar's frame
        self.assertIn(".pane-intro{padding:18px 4px 14px!important;", html)
        # OWNER 2026-10-23 「保有：青 HOT：緑（ロング）hot：赤（ショート）」, otherwise the card frame
        self.assertNotIn("syncAttentionFrame", html)
        for rule in (".attention-box.att-held{border-color:#4ea1ff}", ".attention-row.att-held{border-color:#4ea1ff}",
                     ".attention-row.att-hot-long{border-color:#35e2ae}", ".attention-row.att-hot-short{border-color:#ff5a5f}"):
            self.assertIn(rule, html)
        self.assertIn('cls=p&&p.status==="OPEN"?"att-held":hotOf(r)?"att-"+hotOf(r):""', html)
        # OWNER 2026-10-23: a grabbable tab-bar scrollbar; the wheel over the tab bar scrolls it sideways
        self.assertIn(".cockpit-tabs{scrollbar-width:auto!important;", html)
        self.assertIn('t.addEventListener("wheel",e=>{if(Math.abs(e.deltaY)>Math.abs(e.deltaX)&&t.scrollWidth>t.clientWidth){t.scrollLeft+=e.deltaY;e.preventDefault();}},{passive:false});', html)
        self.assertLess(html.index('href="theme.css'), html.index(".pane-intro{padding:18px 4px 14px!important"))   # overrides theme.css


class DowntimeNotAfter1530(unittest.TestCase):
    def at(self, hm, day=22):
        h, m = map(int, hm.split(":"))
        return datetime(2026, 10, day, h, m, tzinfo=JST)

    def test_counted_seconds(self):
        self.assertEqual(sup.counted_seconds(self.at("15:00"), self.at("16:00")), 1800)
        self.assertEqual(sup.counted_seconds(self.at("15:31"), self.at("23:00")), 0)
        self.assertEqual(sup.counted_seconds(self.at("11:00"), self.at("13:00")), 7200)  # lunch still counts
        self.assertEqual(sup.counted_seconds(self.at("08:00"), self.at("09:10")), 600)  # OWNER 2026-10-23: not before 9:00
        self.assertEqual(sup.counted_seconds(self.at("05:00"), self.at("08:59")), 0)
        self.assertEqual(sup.counted_seconds(self.at("15:00", 22), self.at("10:00", 23)), 1800 + 3600)

    def test_open_incident_after_close_adds_no_downtime(self):
        incident = {"occurrence_at": self.at("15:32").isoformat(), "recovery_at": None}
        self.assertEqual(sup._clip_duration(incident, self.at("09:00"), self.at("16:30")), 0)
        incident = {"occurrence_at": self.at("15:20").isoformat(), "recovery_at": None}
        self.assertEqual(sup._clip_duration(incident, self.at("09:00"), self.at("16:30")), 600)

    def test_uptime_stops_counting_at_1530(self):
        engine = {"state": {"engine_started_at": self.at("08:00").isoformat()}, "ledger": [],
                  "incidents": [{"occurrence_at": self.at("15:00").isoformat(), "recovery_at": None,
                                 "error_code": "STALE_OR_MISSING_TIMESTAMP"}]}
        daily = sup.summarize_operations(engine, now=self.at("18:00"))["daily"]
        self.assertEqual(daily["total_downtime_seconds"], 1800)
        self.assertAlmostEqual(daily["shadow_uptime_ratio"], 1 - 1800 / (6.5 * 3600))  # 09:00-15:30 counted


class ExcelSafety(unittest.TestCase):
    def test_files_stay_ascii_without_bom(self):
        for path in (STOP, START):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertTrue(all(b < 128 for b in raw), path.name)  # PowerShell 5.1 reads a BOM-less file as ANSI

    def test_s1_quit_only_when_no_other_workbook(self):
        text = STOP.read_text(encoding="utf-8").replace("\r\n", "\n")
        start = text.index("function Close-VerifiedManagedExcelNoSave")
        body = text[start:text.index("# OWNER 2026-10-22 S3", start)]  # its Add-Type here-string has a bare }
        close = body.index("$targetBook.Close($false)")
        count = body.index("$app.Workbooks.Count")
        quit_ = body.index("$app.Quit()")
        self.assertLess(close, count)
        self.assertLess(count, quit_)
        self.assertIn("if ($otherBooks -ne 0) {", body[count:quit_])

    def test_s3_stop_refuses_before_stopping_anything(self):
        text = STOP.read_text(encoding="utf-8").replace("\r\n", "\n")
        guard = text.index("SAFE_STOP_PREFLIGHT=BLOCKED_OTHER_EXCEL")
        self.assertLess(guard, text.index("Stop-Process -Id $controllerPid"))
        self.assertLess(guard, text.index("Stop-OwnedJobBridge 28580"))
        self.assertIn("[int]$_.Id -ne $v10ExcelPid", text)

    def test_s2_controller_refuses_before_anything_starts(self):
        text = CONTROLLER.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertTrue(all(b < 128 for b in CONTROLLER.read_bytes()))
        guard = text.index("V10_START_BLOCKED_OTHER_EXCEL")
        for later in ('Write-Status "Resolving repo checkout', "Stopping this controller's previously managed",
                      'Write-Status "Starting Gateway first', 'Write-Status "Opening MS2 RSS workbook'):
            self.assertLess(guard, text.index(later), later)
        self.assertLess(text.index("$otherExcelAtControllerStart = @(Get-ForeignExcelProcesses)"), guard)

    def test_s2_start_refuses_before_the_runner(self):
        text = START.read_text(encoding="utf-8").replace("\r\n", "\n")
        guard = text.index('throw "V10_START_BLOCKED_OTHER_EXCEL"')
        self.assertLess(text.index("Get-Process -Name EXCEL"), guard)
        self.assertLess(guard, text.index("$runtimeInvoked = $true"))


if __name__ == "__main__":
    unittest.main()
