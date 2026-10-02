"""Contract: V9 startup must not call BindToMoniker on the controller thread."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


def slice_between(text, start, end):
    begin = text.find(start)
    finish = text.find(end, begin + len(start))
    if begin < 0 or finish < 0:
        raise AssertionError("slice markers not found: %s .. %s" % (start, end))
    return text[begin:finish]


class V9ExcelIdentityProbeContract(unittest.TestCase):
    def setUp(self):
        self.controller = read("downloads/AI_COCKPIT_CONTROLLER_V9.ps1")
        self.helper = read("downloads/AI_COCKPIT_EXCEL_IDENTITY_PROBE_V9.ps1")

    def test_controller_main_path_has_no_synchronous_bindtomoniker(self):
        self.assertIsNone(re.search(r"BindToMoniker\s*\(", self.controller))
        self.assertNotIn("[Runtime.InteropServices.Marshal]::BindToMoniker", self.controller)
        self.assertEqual(len(re.findall(r"BindToMoniker\s*\(", self.helper)), 1)
        self.assertNotIn("Stop-Process", self.helper)
        self.assertNotIn("taskkill", self.helper.lower())
        self.assertNotIn("Get-Process EXCEL |", self.helper)

    def test_probe_wait_is_externally_bounded(self):
        self.assertIn("$EXCEL_IDENTITY_PROBE_BUDGET_SEC = 40", self.controller)
        self.assertIn("$EXCEL_IDENTITY_PROBE_ATTEMPT_SEC = 8", self.controller)
        self.assertIn("$EXCEL_IDENTITY_PROBE_KILL_GRACE_MS = 1000", self.controller)
        self.assertIn("function Wait-BoundedHelperProcess", self.controller)
        self.assertIn(".WaitForExit($TimeoutMs)", self.controller)
        self.assertIn(".WaitForExit($KillGraceMs)", self.controller)
        self.assertIsNone(re.search(r"\.WaitForExit\(\s*\)", self.controller))
        self.assertNotIn("-Wait", self.controller)
        self.assertIn("TerminateJobObject", self.controller)
        self.assertIn("EXCEL_IDENTITY_PROBE_TIMEOUT", self.controller)
        self.assertIn("EXCEL_IDENTITY_PROBE_FAILED", self.controller)
        self.assertIn("identity probe attempt ", self.controller)

    def test_timeout_fails_closed_without_touching_unrelated_excel(self):
        block = slice_between(
            self.controller,
            "if (-not $identityOk)",
            'Write-Status "Starting Watcher..."',
        )
        self.assertIn("Stop-VerifiedOwnedExcel ([int]$launchedExcelProc.Id)", block)
        self.assertIn("Resolve-ExcelIdentityFailureCode", block)
        self.assertNotIn("Stop-Process", block)
        self.assertNotIn("taskkill", block.lower())
        self.assertIn("Unrelated Excel was not touched.", block)
        owned = slice_between(
            self.controller,
            "function Stop-VerifiedOwnedExcel",
            "function Resolve-ExcelIdentityFailureCode",
        )
        stop_at = owned.find("Stop-Process")
        self.assertGreater(stop_at, 0)
        for needle in ("isCanonicalWorkbook", "isControllerChild", "isSameSession"):
            self.assertLess(owned.find(needle), stop_at, needle)
        self.assertIn("return $false", owned[:stop_at])
        self.assertIn("The launched Excel process is never assigned to this job.", self.controller)
        attempt = slice_between(
            self.controller,
            "function Invoke-ExcelIdentityProbeAttempt",
            "# ======================================================================",
        )
        self.assertIn('FilePath "powershell.exe"', attempt)
        self.assertNotIn("EXCEL.EXE", attempt)

    def test_success_still_requires_path_hwnd_pid_and_session(self):
        verdict = slice_between(
            self.controller,
            "function Get-ExcelIdentityProbeVerdict",
            "function Initialize-ExcelIdentityProbeJobType",
        )
        for needle in (
            "$full -ieq $WorkbookPath",
            "$verdict.hwnd",
            "$verdict.pid",
            "$verdict.session",
            "definitive_mismatch",
            "NO_RESULT",
        ):
            self.assertIn(needle, verdict)

    def test_ports_and_order_path_unchanged(self):
        for needle in (
            "$PORT_COLLECTOR = 28580",
            "$PORT_GATEWAY = 28581",
            "$PORT_WATCHER = 28582",
            "$PORT_VOICE = 28583",
        ):
            self.assertIn(needle, self.controller)
        self.assertEqual(self.controller.count("RssOrder"), 1)
        self.assertNotIn("real_submit_allowed =", self.controller)
        self.assertIn("Get-ForeignExcelProcesses", self.controller)
        self.assertIn("AI_COCKPIT_EXCEL_IDENTITY_PROBE_V9.ps1", self.controller)


if __name__ == "__main__":
    unittest.main()
