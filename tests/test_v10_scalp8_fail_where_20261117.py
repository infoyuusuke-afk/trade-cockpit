"""OWNER 2026-11-17 「SCALP8の起動時の準備が失敗する原因を調べて…③失敗した時に、止まった行番号も残るようにする」."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")


class Scalp8FailWhere(unittest.TestCase):
    def test_the_step_line_and_code_go_with_every_failure(self):
        self.assertIn("function Get-Scalp8FailWhere($ErrorRecord) {", TEXT)
        self.assertIn('" @step=" + [string]$script:scalp8Step + " line="', TEXT)
        self.assertIn("[string]$inv.ScriptLineNumber", TEXT)
        self.assertIn("$reason = $reason + (Get-Scalp8FailWhere $_)", TEXT)          # setup
        self.assertIn("$s8Reason = $s8Reason + (Get-Scalp8FailWhere $_)", TEXT)      # read

    def test_setup_marks_each_step_and_null_book_or_sheet(self):
        i = TEXT.index("function Initialize-Scalp8([int]$Retries = 240) {")
        block = TEXT[i:TEXT.index("$scalp8StartConfig = Get-Scalp8Config", i)]
        for step in ('"config"', '"find-sheet"', '"add-sheet"', '"name-sheet"', '"formulas-"', '"hide-sheet"'):
            self.assertIn("$script:scalp8Step = " + step, block)
        self.assertIn('if ($null -eq $book) { throw "SCALP8_BOOK_NULL" }', block)
        self.assertIn('if ($null -eq $sheet) { throw "SCALP8_ADD_RETURNED_NULL" }', block)

    def test_the_first_failure_at_start_is_recorded(self):
        self.assertIn('",setup0-start,30," + $reason', TEXT)
        self.assertIn("if ($script:scalp8SetupTries -eq 1) {", TEXT)


if __name__ == "__main__":
    unittest.main()
