"""Read-only OAlerts sibling listing must not touch Excel or the registry.

-SelfTest does not open processes, files, or event logs. The live path
lists event ids and safe error classes only.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SIBLING = ROOT / "downloads" / "DIAGNOSE_CANONICAL_ALERT_SIBLING_V9.ps1"
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


class AlertSiblingTests(unittest.TestCase):
    def test_script_is_ascii_and_read_only(self):
        raw = SIBLING.read_bytes()
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
            "OpenSubKey",
            "GetValue",
            "GetFileName",
            "Set-Content",
            "Out-File",
            "New-Item",
            "InvokePattern",
            "EnumerateFiles",
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
        self.assertIn("DIAGNOSE_CANONICAL_ALERT_SIBLING_READONLY", text)
        self.assertIn("QUERY_BEGIN log=oalerts", text)
        self.assertIn("sibling_listed", text)
        self.assertIn("access_denied", text)
        self.assertIn("if ($SelfTest) {\n    Invoke-AlertSiblingSelfTest\n    return\n}", text)
        start = text.index("function Invoke-AlertSiblingSelfTest")
        end = text.index("function Write-Refused", start)
        body = text[start:end]
        for banned_live in ("Get-Process", "Get-CimInstance", "Add-Type", "Get-WinEvent"):
            self.assertNotIn(banned_live, body)
        self.assertIn("Get-WinEvent", text)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_ALERT_SIBLING", controller)
        run = RUN.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_ALERT_SIBLING", run)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertIn("downloads/DIAGNOSE_CANONICAL_ALERT_SIBLING_V9.ps1", step)
        self.assertIn("- name: Canonical alert sibling selftest", workflow)

    def test_selftest_classifies_without_touching_state(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(SIBLING), "-SelfTest"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for needle in (
            "SELFTEST PASS",
            "PROOF judgment=sibling_listed",
            "PROOF error=access_denied",
            "NOTHING_TOUCHED=1",
        ):
            self.assertIn(needle, proc.stdout)
        count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
        self.assertIsNotNone(count)
        self.assertGreaterEqual(int(count.group(1)), 16)
        self.assertNotIn("JUDGMENT_SIBLING=", proc.stdout)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(SIBLING)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REASON=confirm_token_missing", proc.stdout)
        self.assertNotIn("JUDGMENT_SIBLING=", proc.stdout)


if __name__ == "__main__":
    unittest.main()
