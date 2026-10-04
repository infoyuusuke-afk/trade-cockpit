"""Collector workbook identity and the 285A diagnostic quote.

The fixture price is synthetic. This file does not claim a live market PASS.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V9.ps1"


def _function_body(text, name):
    match = re.search(r"function %s\b.*?\{" % re.escape(name), text)
    if match is None:
        raise AssertionError(name + " is missing")
    start = match.end()
    depth = 1
    index = start
    while index < len(text) and depth:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return text[start:index - 1]


class CollectorWorkbookIdentityContract(unittest.TestCase):
    def setUp(self):
        self.collector = COLLECTOR.read_text(encoding="utf-8")
        self.gateway = GATEWAY.read_text(encoding="utf-8")

    def test_selection_locks_the_canonical_file_and_does_not_scan_other_books(self):
        self.assertIn("BindToMoniker($script:canonicalWorkbookPath)", self.collector)
        self.assertIn("Test-CollectorWorkbookIdentity", self.collector)
        self.assertIn("workbook_full_name", self.collector)
        self.assertIn("workbook_identity_verified", self.collector)
        self.assertIn('$script:IdentityTicker = "285A.T"', self.collector)
        self.assertNotIn("Kioxia_MS2_RSS_Live_Signals*.xlsx", self.collector)
        self.assertNotIn('.Workbooks', self.collector)
        self.assertNotIn('Worksheets.Item("DASHBOARD")', self.collector)
        self.assertNotIn('GetActiveObject("Excel.Application")', self.collector)
        self.assertNotIn("RssOrder", self.collector)
        self.assertIn("$AutoOrderEnabled = $false", self.collector)
        self.assertIn("real_submit_allowed=$false", self.collector)
        self.assertIn("real_submit_allowed = $false", self.collector)

    def test_published_symbol_comes_from_the_285a_row(self):
        block = self.collector.split("$identityQuote = Get-IdentityQuote $results", 1)[1]
        block = block.split("real_submit_allowed = $false", 1)[0]
        self.assertIn("symbol = $identityQuote.symbol", block)
        self.assertIn("current_price = $identityQuote.current_price", block)
        self.assertNotIn("diagnosticSamples[0]", block)

    def test_gateway_uses_the_same_gate_and_keeps_real_submit_false(self):
        for name in (
            "Get-NormalizedLocalWorkbookPath",
            "Test-SameCanonicalWorkbookFile",
            "Get-PublishedWorkbookGate",
        ):
            self.assertEqual(_function_body(self.collector, name), _function_body(self.gateway, name))
        self.assertIn("Get-PublishedWorkbookGate", self.gateway)
        self.assertIn("real_submit_allowed = $false", self.gateway)
        self.assertNotIn("RssOrder", self.gateway)
        self.assertIn('Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"', self.gateway)

    def test_code_column_read_stays_on_the_single_column_b_range(self):
        self.assertIn('Data = $sheet.Range("B2:B101").Value2', self.collector)
        self.assertIn("$sheet.Cells.Item($row,2).Value2 = $tickerText", self.collector)
        self.assertIn("Get-TableValue $table $row 1 1", self.collector)

    def test_windows_powershell_selftest_accepts_285a_and_rejects_8035(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell is not installed in this environment")
        proc = subprocess.run(
            [shell, "-NoProfile", "-File", str(COLLECTOR), "-WorkbookIdentitySelfTest"],
            check=False,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertIn("WORKBOOK_IDENTITY_SELFTEST PASS", proc.stdout)
        self.assertNotIn("LIVE PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
