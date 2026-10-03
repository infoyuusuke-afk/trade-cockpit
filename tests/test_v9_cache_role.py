"""Read-only cache-role check must not touch the registry or Excel.

The classification checks run inside -SelfTest. That path does not open
processes or files. The live path does not open the registry.
"""
import os
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = ROOT / "downloads" / "DIAGNOSE_CANONICAL_CACHE_ROLE_V9.ps1"
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


class CacheRoleTests(unittest.TestCase):
    def test_script_is_ascii_and_read_only(self):
        raw = ROLE.read_bytes()
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
        self.assertIn("DIAGNOSE_CANONICAL_CACHE_ROLE_READONLY", text)
        self.assertIn("REGISTRY_REREAD=0", text)
        self.assertIn("PACKAGE_REREAD=0", text)
        self.assertIn("DIALOG_QUERIED=0", text)
        self.assertIn("DISABLED_LIST_REREAD=0", text)
        self.assertIn("RULES_MODE=filename_only", text)
        self.assertIn("name_only_not_crash_marker", text)
        self.assertIn("located_crash_needle", text)
        self.assertIn("fileRecoveryPr", text)
        self.assertIn("crashSave", text)
        self.assertNotIn("KEY_SET_VALUE", text)
        self.assertNotIn("RegSetValue", text)
        self.assertIn("if ($SelfTest) {\n    Invoke-CacheRoleSelfTest\n    return\n}", text)
        start = text.index("function Invoke-CacheRoleSelfTest")
        end = text.index("function Write-Refused", start)
        body = text[start:end]
        for banned_live in ("Get-Process", "Get-CimInstance", "Add-Type", "EnumerateFiles", "EnumerateDirectories"):
            self.assertNotIn(banned_live, body)
        controller = CONTROLLER.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_CACHE_ROLE", controller)
        run = RUN.read_text(encoding="utf-8")
        self.assertNotIn("DIAGNOSE_CANONICAL_CACHE_ROLE", run)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("- name: Windows PowerShell 5.1 parse", 1)[1].split("- name:", 1)[0]
        self.assertIn("shell: powershell", step)
        self.assertNotIn("shell: pwsh", step)
        self.assertIn("downloads/DIAGNOSE_CANONICAL_CACHE_ROLE_V9.ps1", step)
        self.assertIn("WINDOWS POWERSHELL 5.1 PARSE PASS", step)

    def test_selftest_classifies_without_touching_state(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed; Windows PowerShell 5.1 runs this selftest in CI")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(ROLE), "-SelfTest"],
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
            "REGISTRY_REREAD=0",
            "PACKAGE_REREAD=0",
            "DIALOG_QUERIED=0",
            "DISABLED_LIST_REREAD=0",
            "PROOF judgment=name_only_not_crash_marker",
            "PROOF judgment=located_crash_needle",
            "PROOF judgment=name_only_cache_incomplete",
            "PROOF role=recent_name",
        ):
            self.assertIn(needle, proc.stdout)
        count = re.search(r"CASE_COUNT=(\d+)", proc.stdout)
        self.assertIsNotNone(count, proc.stdout)
        self.assertGreaterEqual(int(count.group(1)), 20)
        self.assertNotIn("JUDGMENT_ROLE=", proc.stdout)

    def test_missing_confirm_token_changes_nothing(self):
        pwsh = _pwsh()
        if not pwsh:
            self.skipTest("pwsh is not installed")
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(ROLE)],
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
        self.assertNotIn("JUDGMENT_ROLE=", proc.stdout)


if __name__ == "__main__":
    unittest.main()
