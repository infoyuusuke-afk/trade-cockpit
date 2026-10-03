"""Read-only Office Alerts check must not touch the registry or Excel.

The classification checks run inside -SelfTest. That path does not open
processes, files, or event logs. The live path does not open the cache,
the registry, the workbook, or the dialog.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALERT = ROOT / "downloads" / "DIAGNOSE_CANONICAL_ALERT_LOG_V9.ps1"
CONTROLLER = ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1"
RUN = ROOT / "downloads" / "RUN_AI_COCKPIT_V9.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "v9-ui-voice-acceptance.yml"


def _pwsh():
    found = shutil.which("pwsh")
    if found:
        return found
    candidate = "/tmp/pwsh/pwsh"
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


class AlertLogTests(unittest.TestCase):
    def test_script_is_ascii_and_read_only(self):
        raw = ALERT.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(all(byte < 128 for byte in raw))
        self.assertTrue(raw.endswith(b"\n"))
        text = raw.decode("ascii")
        self.assertNotRegex(text, r"(?m)^\s*exit\b")
        for banned in (
            "Stop-Process",
            "Start-Process",
            "SendKeys",
            "Remove-Item",
            "reg.exe",
            "DeleteValue",
            "SetValue",
            "CreateSubKey",
            "DeleteSubKey",
            "OpenSubKey",
            "GetValue",
            "GetFileName",
            "SetForegroundWindow",
            "BM_CLICK",
            "WriteAllText",
            "WriteAllBytes",
            "Set-Content",
            "Add-Content",
            "Out-File",
            "New-Item",
            "InvokePattern",
            "EnumerateFiles",
            "EnumerateDirectories",
            "real_submit_allowed = $true",
        ):
            self.assertNotIn(banned, text)
        for match in re.finditer(r"\[StringComparison\]::\w+", text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            line = text[line_start:line_end if line_end >= 0 else None]
            self.assertRegex(
                line,
                r"^\s*\$[A-Za-z_][A-Za-z0-9_:]*\s*=\s*\[StringComparison\]::",
                "StringComparison is passed into a call: " + line,
            )
        self.assertNotRegex(text, r"Write-Output\([^\n]*[Mm]essage")
        self.assertIn("DIAGNOSE_CANONICAL_ALERT_LOG_READONLY", text)
        self.assertIn("CACHE_REREAD=0", text)
        self.assertIn("RULES_REREAD=0", text)
        self.assertIn("PACKAGE_REREAD=0", text)
        self.assertIn("REGISTRY_REREAD=0", text)
        self.assertIn("DIALOG_QUERIED=0", text)
        self.assertIn("QUERY_BEGIN log=oalerts", text)
        self.assertIn("QUERY_BEGIN log=application provider=", text)
        self.assertIn("no_launch_alert", text)
        self.assertIn("launch_dialog_logged", text)
        self.assertIn("oalerts_absent", text)
        self.assertIn("OAlerts", text)
        self.assertIn("Microsoft Office 16 Alerts", text)
        self.assertIn("2026-10-03T02:22:51Z", text)
        self.assertNotIn("KEY_SET_VALUE", text)
        self.assertNotIn("RegSetValue", text)
        self.assertNotIn("OfficeFileCache", text)
        self.assertIn("if ($SelfTest) {\n    Invoke-AlertLogSelfTest\n    return\n}", text)
        start = text.index("function Invoke-AlertLogSelfTest")
        end = text.index("function Write-Refused", start)
        body = text[start:end]
        for banned_live in (
            "Get-Process",
            "Get-CimInstance",
            "Add-Type",
            "Get-WinEvent",
            "EnumerateFiles",
            "EnumerateDirectories",
        ):
            self.assertNotIn(banned_live, body)
        self.assertIn("Get-WinEvent", text)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_ALERT_LOG", controller)
        run = RUN.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_ALERT_LOG", run)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertNotIn("shell: pwsh", step)
        self.assertIn("downloads/DIAGNOSE_CANONICAL_ALERT_LOG_V9.ps1", step)
        self.assertIn("WINDOWS POWERSHELL 5.1 PARSE PASS", step)
        self.assertIn("- name: Canonical alert log selftest", workflow)
        alert_step = workflow.split("- name: Canonical alert log selftest", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", alert_step)
        self.assertIn("PROOF judgment=no_launch_alert", alert_step)
        self.assertIn("PROOF judgment=launch_dialog_logged", alert_step)
        self.assertIn("PROOF judgment=oalerts_absent", alert_step)
        self.assertIn("PROOF phrase=serious", alert_step)

    def test_selftest_classifies_without_touching_state(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed; Windows PowerShell 5.1 runs this selftest in CI")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(ALERT), "-SelfTest"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for needle in (
            "SELFTEST PASS",
            "NOTHING_TOUCHED=1",
            "CACHE_REREAD=0",
            "RULES_REREAD=0",
            "PACKAGE_REREAD=0",
            "REGISTRY_REREAD=0",
            "DIALOG_QUERIED=0",
            "PROOF judgment=no_launch_alert",
            "PROOF judgment=launch_dialog_logged",
            "PROOF judgment=oalerts_absent",
            "PROOF phrase=serious",
        ):
            self.assertIn(needle, proc.stdout)
        count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
        self.assertIsNotNone(count, proc.stdout)
        self.assertGreaterEqual(int(count.group(1)), 30)
        self.assertNotIn("JUDGMENT_ALERT=", proc.stdout)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(ALERT)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REASON=confirm_token_missing", proc.stdout)
        self.assertIn("NOTHING_TOUCHED=1", proc.stdout)
        self.assertNotIn("SELFTEST PASS", proc.stdout)
        self.assertNotIn("JUDGMENT_ALERT=", proc.stdout)

    def test_confirmed_live_path_does_not_throw_without_windows(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(ALERT),
                "-Confirm",
                "DIAGNOSE_CANONICAL_ALERT_LOG_READONLY",
                "-LaunchedPid",
                "43904",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for needle in (
            "READ_ONLY=1",
            "CACHE_REREAD=0",
            "RULES_REREAD=0",
            "DIALOG_QUERIED=0",
            "QUERY_BEGIN log=oalerts",
            "WINDOW_SOURCE=pinned",
            "WINDOW_BEGIN_UTC=2026-10-03T02:20:51Z",
            "WINDOW_END_UTC=2026-10-03T02:37:51Z",
            "JUDGMENT_ALERT=",
            "NOTHING_TOUCHED=1",
            "EXCEL_STOP_REQUESTED=0",
        ):
            self.assertIn(needle, proc.stdout)
        self.assertNotIn("SELFTEST PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
