"""Canonical workbook resiliency cleanup must fail closed.

These tests do not read or write an Office registry hive. The byte matcher
runs inside the script's -SelfTest, which also leaves the registry untouched.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLEAR = ROOT / "downloads" / "CLEAR_CANONICAL_WORKBOOK_RECOVERY_V9.ps1"
RESTORE = ROOT / "downloads" / "RESTORE_CANONICAL_WORKBOOK_RECOVERY_V9.ps1"
CONTROLLER = ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "v9-ui-voice-acceptance.yml"


def _pwsh():
    found = shutil.which("pwsh")
    if found:
        return found
    candidate = "/tmp/pwsh/pwsh"
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


class CanonicalWorkbookRecoveryTests(unittest.TestCase):
    def test_scripts_are_ascii_and_fail_closed(self):
        for path in (CLEAR, RESTORE):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            self.assertTrue(all(byte < 128 for byte in raw), path.name)
            self.assertTrue(raw.endswith(b"\n"), path.name)
            text = raw.decode("ascii")
            self.assertNotRegex(text, r"(?m)^\s*exit\b")
            self.assertNotIn("Stop-Process", text)
            self.assertNotIn("Start-Process", text)
            self.assertNotIn("SendKeys", text)
            self.assertNotIn("Remove-Item", text)
            self.assertNotIn("reg.exe", text)
            self.assertNotIn("real_submit_allowed = $true", text)
            self.assertNotIn("DeleteSubKey", text)
            for match in re.finditer(r"\[StringComparison\]::\w+", text):
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                line = text[line_start:line_end if line_end >= 0 else None]
                self.assertRegex(
                    line,
                    r"^\s*\$[A-Za-z_][A-Za-z0-9_:]*\s*=\s*\[StringComparison\]::",
                    path.name + " passes StringComparison into a call: " + line,
                )
        clear = CLEAR.read_text(encoding="ascii")
        restore = RESTORE.read_text(encoding="ascii")
        self.assertEqual(clear.count("DeleteValue("), 1)
        self.assertNotIn("DeleteValue(", restore)
        self.assertIn("CLEAR_ONE_CANONICAL_WORKBOOK_RECOVERY", clear)
        self.assertIn("RESTORE_ONE_CANONICAL_WORKBOOK_RECOVERY", restore)
        self.assertIn("Software\\Microsoft\\Office\\16.0\\Excel\\Resiliency\\DocumentRecovery", clear)
        self.assertIn("Software\\Microsoft\\Office\\16.0\\Excel\\Resiliency\\DocumentRecovery", restore)
        self.assertIn("MarketSpeed2_RSS", clear)
        self.assertIn("Kioxia_MS2_RSS_Live_Signals.xlsx", clear)
        self.assertIn("[char]0x30C7", clear)
        self.assertIn("NOTHING_CHANGED=1", clear)
        self.assertIn("BACKUP_VERIFY=1", clear)
        self.assertLess(clear.index("Write-VerifiedBackup"), clear.index("DeleteValue("))
        self.assertIn("outside_resiliency_match", clear)
        self.assertIn("not_unique", clear)
        self.assertIn("canonical_excel_still_running", clear)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("CLEAR_CANONICAL_WORKBOOK_RECOVERY", controller)
        self.assertNotIn("RESTORE_CANONICAL_WORKBOOK_RECOVERY", controller)
        self.assertIn("real_submit_allowed = $false", controller)
        self.assertIn("V9-CONTROLLER-20261002-EXCEL-FOREIGN-SURVIVE-01", controller)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertNotIn("shell: pwsh", step)
        self.assertIn("downloads/CLEAR_CANONICAL_WORKBOOK_RECOVERY_V9.ps1", step)
        self.assertIn("downloads/RESTORE_CANONICAL_WORKBOOK_RECOVERY_V9.ps1", step)

    def test_selftest_matches_only_the_canonical_workbook(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed; Windows PowerShell 5.1 runs this selftest in CI")
        for script, minimum in ((CLEAR, 40), (RESTORE, 10)):
            proc = subprocess.run(
                [pwsh, "-NoProfile", "-File", str(script), "-SelfTest"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("SELFTEST PASS", proc.stdout)
            self.assertIn("NOTHING_CHANGED=1", proc.stdout)
            self.assertIn("REGISTRY_CHANGED=0", proc.stdout)
            count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
            self.assertIsNotNone(count, proc.stdout)
            self.assertGreaterEqual(int(count.group(1)), minimum)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(CLEAR)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REASON=confirm_token_missing", proc.stdout)
        self.assertIn("NOTHING_CHANGED=1", proc.stdout)
        self.assertNotIn("DELETED=1", proc.stdout)
        self.assertNotIn("SUCCESS=1", proc.stdout)


if __name__ == "__main__":
    unittest.main()
