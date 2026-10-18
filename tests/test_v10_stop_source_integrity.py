"""Read-only integrity checks for the V10 safe-stop source file.

No processes, Excel instances or market systems are launched or stopped.
"""
import unittest
from pathlib import Path

STOP = Path(__file__).resolve().parents[1] / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
SUCCESS = 'Write-Host "AI Cockpit V10 managed processes and verified managed Excel stopped." -ForegroundColor Green'

class SafeStopSourceIntegrity(unittest.TestCase):
    def test_single_terminal_success_statement(self):
        source = STOP.read_text(encoding="utf-8-sig")
        self.assertEqual(source.count(SUCCESS), 1,
                         "STOP source has a duplicate program tail or repeated success path")
        self.assertEqual(source.rstrip().splitlines()[-1], SUCCESS,
                         "STOP source must not contain executable content after terminal success")

    def test_no_truncated_interpreter_identity_guard(self):
        source = STOP.read_text(encoding="utf-8-sig")
        self.assertIn("if ([int]$wmi.ProcessId -ne $ProcessId", source)
        self.assertIn("if ([int]$proc.SessionId -ne [int]$selfSession)", source)
        self.assertNotIn("\\.exe\n", source,
                         "A PowerShell regex was truncated across lines")

if __name__ == "__main__":
    unittest.main()
