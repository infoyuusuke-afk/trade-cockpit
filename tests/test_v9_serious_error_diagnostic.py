"""Read-only serious-error diagnosis must not touch Excel or the registry.

The byte and distinction checks run inside -SelfTest. That path does not
open HKCU, processes, the workbook, or a dialog.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIAG = ROOT / "downloads" / "DIAGNOSE_CANONICAL_SERIOUS_ERROR_V9.ps1"
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


class SeriousErrorDiagnosticTests(unittest.TestCase):
    def test_script_is_ascii_and_read_only(self):
        raw = DIAG.read_bytes()
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
            "GetFileName",
            "SetForegroundWindow",
            "BM_CLICK",
            "WriteAllText",
            "WriteAllBytes",
            "Set-Content",
            "Add-Content",
            "Out-File",
            "New-Item",
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
        self.assertIn("DIAGNOSE_CANONICAL_SERIOUS_ERROR_READONLY", text)
        self.assertIn("ROT_QUERIED=0", text)
        self.assertIn("WM_GETTEXT", text)
        self.assertIn("GetClassName", text)
        self.assertIn("GetWindowText", text)
        self.assertIn("GW_OWNER", text)
        self.assertIn("Select-DialogHit", text)
        self.assertIn("crash_query_unreadable", text)
        self.assertIn("NoMatchingEventsFound", text)
        self.assertIn("[char]0x91CD", text)
        self.assertIn("[char]0x30C7", text)
        self.assertIn("MarketSpeed2_RSS_64bit.xll", text)
        self.assertIn("if ($SelfTest) {\n    Invoke-DiagnoseSelfTest\n    return\n}", text)
        start = text.index("function Invoke-DiagnoseSelfTest")
        end = text.index("function Write-Refused", start)
        body = text[start:end]
        self.assertNotIn("OpenSubKey", body)
        self.assertNotIn("Get-Process", body)
        self.assertNotIn("Get-WinEvent", body)
        self.assertNotIn("Add-Type", body)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_SERIOUS_ERROR", controller)
        run = RUN.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_SERIOUS_ERROR", run)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertNotIn("shell: pwsh", step)
        self.assertIn("downloads/DIAGNOSE_CANONICAL_SERIOUS_ERROR_V9.ps1", step)
        self.assertIn("WINDOWS POWERSHELL 5.1 PARSE PASS", step)

    def test_selftest_distinguishes_without_touching_state(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed; Windows PowerShell 5.1 runs this selftest in CI")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(DIAG), "-SelfTest"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for needle in (
            "SELFTEST PASS",
            "NOTHING_TOUCHED=1",
            "REGISTRY_CHANGED=0",
            "ROT_QUERIED=0",
            "PROOF primary=resiliency_recreated",
            "PROOF primary=resiliency_other_match",
            "PROOF primary=workbook_rewritten",
            "PROOF primary=crash_after_launch",
            "PROOF primary=multiple_signals",
            "PROOF primary=inconclusive",
            "PROOF module=ucrtbase.dll",
            "PROOF dialog_needle=1",
            "PROOF backup=returned",
            "PROOF backup=stayed_clear",
            "PROOF backup=new_record",
            "PROOF area=disabled_items",
            "PROOF verdict=pure",
            "PROOF verdict=none",
            "dialog_visible_xll_loaded_without_resiliency_crash_or_rewrite",
        ):
            self.assertIn(needle, proc.stdout)
        count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
        self.assertIsNotNone(count, proc.stdout)
        self.assertGreaterEqual(int(count.group(1)), 40)
        self.assertNotIn("SUCCESS=1", proc.stdout)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(DIAG)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REASON=confirm_token_missing", proc.stdout)
        self.assertIn("NOTHING_TOUCHED=1", proc.stdout)
        self.assertIn("REGISTRY_CHANGED=0", proc.stdout)
        self.assertNotIn("SELFTEST PASS", proc.stdout)
        self.assertNotIn("SUCCESS=1", proc.stdout)
        self.assertNotIn("PRIMARY=", proc.stdout)


if __name__ == "__main__":
    unittest.main()
