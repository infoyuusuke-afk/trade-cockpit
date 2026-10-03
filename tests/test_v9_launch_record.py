"""Read-only launch-record check must not touch Excel or the registry.

The classification checks run inside -SelfTest. That path does not open
processes or files. The live path reads only the Controller's own
identity-probe JSON and the operations incident log.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECORD = ROOT / "downloads" / "DIAGNOSE_CANONICAL_LAUNCH_RECORD_V9.ps1"
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


class LaunchRecordTests(unittest.TestCase):
    def test_script_is_ascii_and_read_only(self):
        raw = RECORD.read_bytes()
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
            "Get-WinEvent",
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
        self.assertNotRegex(text, r"Write-Output\([^\n]*dialog_text")
        self.assertNotRegex(text, r"Write-Output\([^\n]*command_line")
        self.assertNotRegex(text, r"Write-Output\([^\n]*full_name")
        self.assertIn("DIAGNOSE_CANONICAL_LAUNCH_RECORD_READONLY", text)
        self.assertIn("CACHE_REREAD=0", text)
        self.assertIn("RULES_REREAD=0", text)
        self.assertIn("REGISTRY_REREAD=0", text)
        self.assertIn("DIALOG_QUERIED=0", text)
        self.assertIn("LOG_TEXT_REREAD=0", text)
        self.assertIn("READ_BEGIN file=result_json", text)
        self.assertIn("no_disabled_count_at_fail", text)
        self.assertIn("probe_recorded_dialog", text)
        self.assertNotIn("OfficeFileCache", text)
        self.assertIn("if ($SelfTest) {\n    Invoke-LaunchRecordSelfTest\n    return\n}", text)
        start = text.index("function Invoke-LaunchRecordSelfTest")
        end = text.index("function Write-Refused", start)
        body = text[start:end]
        for banned_live in (
            "Get-Process",
            "Get-CimInstance",
            "Add-Type",
            "Get-WinEvent",
            "Read-TextCap",
            "EnumerateFiles",
            "EnumerateDirectories",
        ):
            self.assertNotIn(banned_live, body)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_LAUNCH_RECORD", controller)
        run = RUN.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_LAUNCH_RECORD", run)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertNotIn("shell: pwsh", step)
        self.assertIn("downloads/DIAGNOSE_CANONICAL_LAUNCH_RECORD_V9.ps1", step)
        self.assertIn("WINDOWS POWERSHELL 5.1 PARSE PASS", step)
        self.assertIn("- name: Canonical launch record selftest", workflow)

    def test_controller_launch_is_isolated_x_only(self):
        text = CONTROLLER.read_text(encoding="utf-8")
        start = text.index("function Get-IsolatedExcelArguments")
        end = text.index("\nfunction ", start + 10)
        body = text[start:end]
        self.assertIn("return '/x \"' + $WorkbookPath + '\"'", body)
        self.assertNotIn("safemode", body.lower())
        self.assertNotIn("CorruptLoad", body)
        self.assertNotIn("Repair", body)

    def test_selftest_classifies_without_touching_state(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed; Windows PowerShell 5.1 runs this selftest in CI")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(RECORD), "-SelfTest"],
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
            "DIALOG_QUERIED=0",
            "LOG_TEXT_REREAD=0",
            "PROOF judgment=probe_recorded_dialog",
            "PROOF judgment=no_disabled_count_at_fail",
            "PROOF judgment=disabled_items_counted_at_fail",
            "PROOF judgment=launch_record_absent",
            "PROOF launch=/x",
        ):
            self.assertIn(needle, proc.stdout)
        count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
        self.assertIsNotNone(count, proc.stdout)
        self.assertGreaterEqual(int(count.group(1)), 20)
        self.assertNotIn("JUDGMENT_LAUNCH=", proc.stdout)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(RECORD)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REASON=confirm_token_missing", proc.stdout)
        self.assertIn("NOTHING_TOUCHED=1", proc.stdout)
        self.assertNotIn("JUDGMENT_LAUNCH=", proc.stdout)

    def test_confirmed_live_path_does_not_throw_without_windows(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(RECORD),
                "-Confirm",
                "DIAGNOSE_CANONICAL_LAUNCH_RECORD_READONLY",
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
            "READ_BEGIN file=result_json",
            "READ file=result_json state=absent",
            "READ file=open_diagnostics state=absent",
            "JUDGMENT_LAUNCH=launch_record_absent",
            "NOTHING_TOUCHED=1",
            "EXCEL_STOP_REQUESTED=0",
            "DIALOG_CLICKED=0",
        ):
            self.assertIn(needle, proc.stdout)


if __name__ == "__main__":
    unittest.main()
