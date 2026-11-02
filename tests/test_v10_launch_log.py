"""Start window wrapper (OWNER 2026-10-23): log file, normal vs abnormal stop, alert. Synthetic."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "downloads" / "LAUNCH_AI_COCKPIT_V10.ps1"
WINDOWS = os.name == "nt" and shutil.which("powershell")
NL = chr(10)


class LaunchLog(unittest.TestCase):
    def test_ascii_and_same_start_call(self):
        raw = LAUNCH.read_bytes()
        self.assertTrue(all(b < 128 for b in raw))
        text = raw.decode("ascii")
        self.assertIn('-File $start -ApprovalFile $approval', text)
        self.assertIn('Join-Path $PSScriptRoot "V10_APPROVED_SOURCE.json"', text)
        self.assertIn('$text.Contains("V10_RUNNER_EXIT_FAILURE") -and -not $stateLeft', text)
        self.assertIn("System.Speech.Synthesis.SpeechSynthesizer", text)
        self.assertIn("$shell.Popup(", text)
        for word in ("Stop-Process", "Remove-Item", "Invoke-WebRequest"):   # changes nothing in V10
            self.assertNotIn(word, text)

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_normal_and_abnormal_stops(self):
        cases = {"zero": ('Write-Output "V10_START=OK"\nexit 0\n', False, 0, "RESULT=NORMAL_STOP"),
                 "safe_stop": ('Write-Output "V10_RUNNER_EXIT_FAILURE"\nexit 2\n', False, 0, "RESULT=NORMAL_STOP"),
                 "blocked": ('Write-Output "V10_START=BLOCKED"\nWrite-Output "V10_START_BLOCKED_OTHER_EXCEL"\nexit 2\n',
                             False, 1, "reason=V10_START=BLOCKED V10_START_BLOCKED_OTHER_EXCEL"),
                 "crash": ('Write-Output "V10_RUNNER_EXIT_FAILURE"\nexit 2\n', True, 1, "CONTROLLER_STATE_LEFT"),
                 # OWNER 2026-10-24: Safe Stop removes the state file a few seconds after the runner ends
                 "safe_stop_state_removed_later": (
                     'Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile","-Command",'
                     '"Start-Sleep 3; Remove-Item -LiteralPath \'STATE\'"\n'
                     'Write-Output "V10_RUNNER_EXIT_FAILURE"\nexit 2\n', True, 0, "RESULT=NORMAL_STOP")}
        for name, (body, state, rc, want) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                d = Path(d)
                (d / "dl").mkdir()
                shutil.copy(LAUNCH, d / "dl" / LAUNCH.name)
                (d / "dl" / "START_AI_COCKPIT_V10.ps1").write_text(body.replace("STATE", str(d / "state.json")), encoding="ascii")
                (d / "dl" / "V10_APPROVED_SOURCE.json").write_text("{}", encoding="ascii")
                if state:
                    (d / "state.json").write_text("{}", encoding="ascii")
                out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                      str(d / "dl" / LAUNCH.name), "-LogDir", str(d / "logs"),
                                      "-StateFile", str(d / "state.json"), "-StopGraceSeconds", "6", "-NoAlert"],
                                     capture_output=True, timeout=120)
                self.assertEqual(out.returncode, rc)
                logs = list((d / "logs").glob("*.log"))
                self.assertEqual(len(logs), 1)
                lines = logs[0].read_text(encoding="utf-8-sig").splitlines()
                self.assertTrue(lines[0].startswith("START "))
                self.assertIn(want, lines[-1])


class SafeStopShownAsNormal(unittest.TestCase):
    """OWNER 2026-11-02 「安全停止で止めた時は、起動の窓と記録に正常な停止と出るように直して。止め方の安全の決まりは変えないで」."""

    def test_marker_says_stopped_only_after_every_component_and_excel_stopped(self):
        # OWNER 2026-11-02 「全部の部品とExcelが止まったのを確かめた後の印がある時だけ正常と出して、途中で失敗した時は今までどおり異常」
        stop = (ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1").read_text(encoding="utf-8-sig")
        ok = stop.index('Write-SafeStopMarker "stopped_verified"')
        # after the Excel clean-up check and the worker / brain / bridge stop check
        self.assertLess(stop.index("managed Excel cleanup is incomplete."), ok)
        self.assertLess(stop.index("V10 safe stop incomplete; recorded state retained for owner review."), ok)
        self.assertEqual(stop.count('Write-SafeStopMarker "stopped_verified"'), 1)
        # every later failure marks the marker failed before it exits
        for msg in ("SAFE_STOP_VERIFY=LISTEN_PORTS_REMAIN; retained state.", "SAFE_STOP_VERIFY=PORT_AUDIT_FAILED; retained state.",
                    "SAFE_STOP_VERIFY=TRACKED_PID_STILL_PRESENT; retained state.", "V10 state removal failed; cannot report Safe Stop success."):
            i = stop.index(msg)
            self.assertLess(i, ok + 10 ** 6)
            self.assertGreater(i, ok)
            self.assertIn('Write-SafeStopMarker "failed"', stop[i:i + 200])
        self.assertGreater(stop.index('Write-SafeStopMarker "done"'), stop.index("Remove-Item -LiteralPath $StateFile -Force -ErrorAction Stop"))
        # nothing is written before the stop starts
        self.assertGreater(ok, stop.index("# Stop the supervising RUN/Controller host FIRST."))

    @unittest.skipUnless(WINDOWS, "Windows PowerShell 5.1 only")
    def test_runner_end_after_a_safe_stop_of_this_run_is_normal(self):
        runner_end = ('Write-Output "V10_START=BLOCKED"' + NL + 'Write-Output "V10_RUNNER_EXIT_FAILURE"' + NL +
                      'Write-Output "RUNTIME_STATE=UNKNOWN_AFTER_RUNNER"' + NL + "exit 2" + NL)
        mk = lambda stage: "Set-Content -LiteralPath 'MARKER' -Value '{\"stage\":\"" + stage + "\"}'" + NL
        cases = {
            # every component and the Excel were verified stopped, the clean-up after it was cut short (state file left)
            "this_run": (mk("stopped_verified") + runner_end, False, 0,
                         "RESULT=NORMAL_STOP rc=2 reason=SAFE_STOP SAFE_STOP_STATE_LEFT"),
            "done": (mk("done") + runner_end, False, 0, "RESULT=NORMAL_STOP rc=2 reason=SAFE_STOP"),
            # a Safe Stop that failed part-way stays abnormal (alert as before)
            "failed": (mk("failed") + runner_end, False, 1, "RESULT=ABNORMAL_STOP"),
            # an old marker from an earlier day does not count
            "old_marker": (runner_end, True, 1, "RESULT=ABNORMAL_STOP"),
        }
        for name, (body, old, rc, want) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as d:
                d = Path(d)
                (d / "dl").mkdir()
                shutil.copy(LAUNCH, d / "dl" / LAUNCH.name)
                marker = d / "marker.json"
                if old:
                    marker.write_text('{"stage":"done"}', encoding="ascii")
                    os.utime(marker, (1_600_000_000, 1_600_000_000))
                (d / "dl" / "START_AI_COCKPIT_V10.ps1").write_text(body.replace("MARKER", str(marker)), encoding="ascii")
                (d / "dl" / "V10_APPROVED_SOURCE.json").write_text("{}", encoding="ascii")
                (d / "state.json").write_text("{}", encoding="ascii")
                out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                      str(d / "dl" / LAUNCH.name), "-LogDir", str(d / "logs"), "-StateFile", str(d / "state.json"),
                                      "-SafeStopMarker", str(marker), "-StopGraceSeconds", "1", "-NoAlert"],
                                     capture_output=True, timeout=120)
                self.assertEqual(out.returncode, rc)
                log = list((d / "logs").glob("*.log"))[0].read_text(encoding="utf-8-sig")
                self.assertIn(want, log.splitlines()[-1])
                self.assertIn("V10_START=BLOCKED", log)                      # the log keeps the runner's own lines
                if name in ("this_run", "done"):
                    self.assertNotIn(b"V10_START=BLOCKED", out.stdout)      # the window shows the Safe Stop instead
                else:
                    self.assertIn(b"V10_START=BLOCKED", out.stdout)         # a failed or unknown stop shows as before


if __name__ == "__main__":
    unittest.main()
