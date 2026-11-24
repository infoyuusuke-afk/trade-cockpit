"""OWNER 2026-11-24 「起動したの音声がまずでない」「起動の声のやり直しは、待つ時間を3秒ほどに短くして、値段の取り込みを止めない形にして」:
the startup voice is handed to a background job that retries; the loop only looks at the job's state and never waits."""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"


def _src():
    return COLLECTOR.read_text(encoding="utf-8-sig").replace("\r\n", "\n")


class StartupVoice(unittest.TestCase):
    def test_handed_to_a_background_job_with_retries(self):
        t = _src()
        a = t.index('$script:startupVoiceText = "キオクシアを含む、100銘柄の音声監視を開始しました。"')
        b = t.index("function Test-StartupVoiceJob {", a)
        job = t[a:b]
        self.assertIn('Start-Job -Name ("MS2_STARTUP_VOICE_" + $PID)', job)
        self.assertIn("$until = (Get-Date).AddMinutes(4)", job)
        self.assertIn("Start-Sleep -Seconds 10", job)
        self.assertIn("http://127.0.0.1:28583/announce?level=WATCH&text=", job)
        # audit 92a5979: wait for /health sbv2_ready first, send once with a long wait, never ask again after a time-out
        self.assertLess(job.index('"http://127.0.0.1:28583/health"'), job.index("/announce?level=WATCH"))
        self.assertIn("-TimeoutSec 150", job)
        self.assertIn('if ($st -eq [System.Net.WebExceptionStatus]::Timeout) { return ("TIMEOUT_NO_RETRY', job)
        self.assertIn("if ($r.StatusCode -eq 200) { $i++; continue }", job)   # a chunk that played is not sent again
        self.assertNotIn("-TimeoutSec 40", job)
        self.assertEqual(t.count('"キオクシアを含む、100銘柄の音声監視を開始しました。"'), 1)
        self.assertNotIn("Invoke-SerializedSpeak $speaker $script:startupVoiceText", t)

    def test_the_loop_only_looks_at_the_state(self):
        t = _src()
        a = t.index("function Test-StartupVoiceJob {")
        b = t.index("\n}\n", a)
        fn = t[a:b]
        self.assertIn("$j.State -eq 'Running'", fn)
        for w in ("Wait-Job", "Start-Sleep", "Invoke-WebRequest", "Invoke-SerializedSpeak"):
            self.assertNotIn(w, fn)
        loop = t[t.index("    while ($true) {\n        # RssMarket"):t.index("} finally {\n    if ($null -ne $bridgeJob)")]
        self.assertEqual(loop.count("Test-StartupVoiceJob"), 1)
        self.assertLess(loop.index("Test-StartupVoiceJob"), loop.index("        Add-LoopMark 'voice_tail'\n"))
        self.assertIn("if ($null -ne $script:startupVoiceJob) { Stop-Job $script:startupVoiceJob", t)

    @unittest.skipUnless(shutil.which("powershell.exe"), "Windows PowerShell 5.1 required")
    def test_check_returns_at_once_while_the_job_runs(self):
        t = _src()
        a = t.index("function Test-StartupVoiceJob {")
        fn = t[a:t.index("\n}\n", a) + 3]
        script = fn + r'''
$script:startupVoiceJob = Start-Job -ScriptBlock { Start-Sleep -Seconds 20; "OK try=1" }
$sw = [Diagnostics.Stopwatch]::StartNew()
Test-StartupVoiceJob
$ms = $sw.ElapsedMilliseconds
Write-Output ("RUNNING_MS=" + $ms + " STILL=" + ($null -ne $script:startupVoiceJob))
Stop-Job $script:startupVoiceJob; Remove-Job $script:startupVoiceJob -Force
$script:startupVoiceJob = Start-Job -ScriptBlock { "OK try=2" }
Wait-Job $script:startupVoiceJob | Out-Null
Test-StartupVoiceJob
Write-Output ("DONE_CLEARED=" + ($null -eq $script:startupVoiceJob))
'''
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.ps1"
            p.write_text(script, encoding="utf-8-sig")
            out = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(p)],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120).stdout
        m = re.search(r"RUNNING_MS=(\d+) STILL=True", out)
        self.assertIsNotNone(m, out)
        self.assertLess(int(m.group(1)), 3000)      # the loop never waits on the voice
        self.assertIn("DONE_CLEARED=True", out)


if __name__ == "__main__":
    unittest.main()
