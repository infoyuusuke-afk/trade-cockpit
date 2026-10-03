"""Read-only OAlerts Event ID 300 field split must not touch Excel.

-SelfTest does not open processes, files, or event logs. The live path
reads OAlerts id 300 only and prints field kinds, not alert text.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "downloads" / "DIAGNOSE_CANONICAL_ALERT_PAYLOAD_V9.ps1"
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


class AlertPayloadTests(unittest.TestCase):
    def test_script_is_ascii_and_read_only(self):
        raw = PAYLOAD.read_bytes()
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
            "Get-Process",
            "Get-CimInstance",
            "Add-Type",
            "real_submit_allowed = $true",
            "LogName = 'Application'",
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
        self.assertIn("DIAGNOSE_CANONICAL_ALERT_PAYLOAD_READONLY", text)
        self.assertIn("QUERY_BEGIN log=oalerts id=300", text)
        self.assertIn("fields_read", text)
        self.assertIn("id_300_is_alert_record_not_cause", text)
        self.assertIn("APPLICATION_QUERIED=0", text)
        self.assertIn("PROCESS_QUERIED=0", text)
        self.assertIn("if ($SelfTest) {\n    Invoke-AlertPayloadSelfTest\n    return\n}", text)
        start = text.index("function Invoke-AlertPayloadSelfTest")
        end = text.index("function Write-Refused", start)
        body = text[start:end]
        self.assertNotIn("Get-WinEvent", body)
        self.assertIn("Get-WinEvent", text)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_ALERT_PAYLOAD", controller)
        run = RUN.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_ALERT_PAYLOAD", run)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertIn("downloads/DIAGNOSE_CANONICAL_ALERT_PAYLOAD_V9.ps1", step)
        self.assertIn("- name: Canonical alert payload selftest", workflow)

    def test_selftest_classifies_fields_without_printing_text(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(PAYLOAD), "-SelfTest"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for needle in (
            "SELFTEST PASS",
            "PROOF judgment=fields_read",
            "PROOF judgment=message_only",
            "PROOF judgment=payload_absent",
            "PROOF field=excel_app",
            "PROOF value=200054",
            "PROOF value=16.0.18623.20208",
            "APPLICATION_QUERIED=0",
            "PROCESS_QUERIED=0",
            "NOTHING_TOUCHED=1",
        ):
            self.assertIn(needle, proc.stdout)
        self.assertNotIn("Kioxia_MS2_RSS_Live_Signals.xlsx", proc.stdout)
        self.assertNotIn("Compositor", proc.stdout)
        self.assertNotIn("JUDGMENT_PAYLOAD=", proc.stdout)
        count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
        self.assertIsNotNone(count)
        self.assertGreaterEqual(int(count.group(1)), 20)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(PAYLOAD)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REASON=confirm_token_missing", proc.stdout)
        self.assertNotIn("JUDGMENT_PAYLOAD=", proc.stdout)
        self.assertIn("PROCESS_QUERIED=0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
