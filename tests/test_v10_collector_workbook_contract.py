"""P0-417: V10 Collector identity and no-order fail-closed contract.

This checks current files only. It does not replace or delete the legacy V9
contract, start the cockpit, access Excel, or claim a live-source result.
The one optional PowerShell self-test runs exclusively in Windows GitHub Actions.
"""
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
CONTROLLER = ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"
WINDOWS_ACTIONS = (
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
)


class V10CollectorSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collector = COLLECTOR.read_text(encoding="utf-8-sig")
        cls.controller = CONTROLLER.read_text(encoding="utf-8-sig")

    def test_current_files_exist_without_legacy_v9_dependency(self):
        self.assertTrue(COLLECTOR.is_file())
        self.assertTrue(CONTROLLER.is_file())
        self.assertIn("function Get-PublishedWorkbookGate", self.collector)
        self.assertIn("function Resolve-RuntimeDir", self.controller)
        self.assertNotIn("AI_COCKPIT_GATEWAY_V9.ps1", self.collector)

    def test_canonical_workbook_identity_is_not_name_or_wildcard_only(self):
        for token in (
            "BindToMoniker($script:canonicalWorkbookPath)",
            "function Test-CollectorWorkbookIdentity",
            "function Test-SameCanonicalWorkbookFile",
            "workbook_identity_verified",
            "workbook_full_name",
            '"WRONG_SOURCE_WORKBOOK"',
        ):
            self.assertIn(token, self.collector)
        for unsafe in (
            "Kioxia_MS2_RSS_Live_Signals*.xlsx",
            'GetActiveObject("Excel.Application")',
            'Worksheets.Item("DASHBOARD")',
        ):
            self.assertNotIn(unsafe, self.collector)

    def test_gate_refuses_mismatched_symbol_and_unproved_workbook(self):
        m = re.search(r"(?m)^function Get-PublishedWorkbookGate\s*\{", self.collector)
        self.assertIsNotNone(m)
        end = self.collector.index("\nfunction Get-WorkbookIdentityInitialization", m.end())
        body = self.collector[m.start():end]
        self.assertIn("WRONG_SYMBOL_MAPPING", body)
        self.assertIn("WRONG_SOURCE_WORKBOOK", body)
        self.assertIn("$IdentityVerified -and (Test-SameCanonicalWorkbookFile $FullName $ExpectedPath)", body)
        self.assertIn("elseif (-not $ControllerVerified)", body)
        self.assertIn("return ($reasons -join", body)
        self.assertNotIn("RssOrder", body)

    def test_selftest_covers_wrong_book_and_wrong_ticker(self):
        start = self.collector.index("function Invoke-WorkbookIdentitySelfTest")
        end = self.collector.index("\nif ($WorkbookIdentitySelfTest)", start)
        body = self.collector[start:end]
        for required in (
            "WRONG_SOURCE_WORKBOOK", "WRONG_SYMBOL_MAPPING",
            '"285A.T"', '"8035.T"',
            "other workbook must fail closed",
            "legacy payload without identity proof must stay fail-closed",
            "bridge copy",
        ):
            self.assertIn(required, body)
        guard = self.collector[end:self.collector.index("\nfunction Get-ScriptProcessCount", end)]
        self.assertIn("Invoke-WorkbookIdentitySelfTest", guard)
        self.assertIn("exit 0", guard)

    def test_no_order_and_controller_fail_closed(self):
        self.assertIn("$AutoOrderEnabled = $false", self.collector)
        self.assertNotIn("RssOrder", self.collector)
        self.assertIn("real_submit_allowed = $false", self.collector)
        self.assertIn("real_submit_allowed = $false", self.controller)
        self.assertIn('Join-Path $resolved "Kioxia_MS2_RSS_Live_Signals.xlsx"', self.controller)
        self.assertIn("function Get-CanonicalWorkbookConflicts", self.controller)
        self.assertIn("function Test-LaunchedExcelOwnership", self.controller)
        for evidence in ("$isCanonicalWorkbook", "$isControllerChild", "$isSameSession"):
            self.assertIn(evidence, self.controller)
        self.assertIn("REAL_SUBMIT_ALLOWED=false", (ROOT / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V2.ps1").read_text(encoding="utf-8"))

    @unittest.skipUnless(WINDOWS_ACTIONS, "Only disposable Windows GitHub Actions; no OWNER run")
    def test_current_collector_selftest_on_windows_synthetic_only(self):
        shell = shutil.which("powershell.exe") or shutil.which("powershell")
        self.assertIsNotNone(shell)
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(COLLECTOR), "-WorkbookIdentitySelfTest"],
            capture_output=True, text=True, errors="replace", timeout=95, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout[-1600:] + result.stderr[-1600:])
        self.assertIn("WORKBOOK_IDENTITY_SELFTEST PASS", result.stdout)
        self.assertNotIn("LIVE PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
