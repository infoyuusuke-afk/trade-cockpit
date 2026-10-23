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


if __name__ == "__main__":
    unittest.main()
