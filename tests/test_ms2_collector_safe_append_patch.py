"""Static negative tests for actual unmerged Collector patch (no MS2/Excel/data)."""
from pathlib import Path
import re
import unittest

SRC = Path(__file__).resolve().parents[1] / "ms2_live" / "MS2_RSS_100_Collector.ps1"
STREAMS = ("tick", "condition", "supply", "snapshot", "credit",
           "preopen", "pts", "irPts", "signal")


class CollectorPatchSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SRC.read_text(encoding="utf-8-sig")

    def test_no_live_order_flag(self):
        self.assertIn("$AutoOrderEnabled = $false", self.source)

    def test_helper_catches_terminating_error(self):
        self.assertIn("Add-Content -LiteralPath $Path -Value $Line -Encoding UTF8 -ErrorAction Stop", self.source)
        self.assertIn("function Invoke-MS2SafeCsvAppend", self.source)

    def test_all_nine_write_sites_routed(self):
        for name in STREAMS:
            with self.subTest(file=name):
                self.assertIn("Invoke-MS2SafeCsvAppend -Path $" + name + "Csv", self.source)
                self.assertNotRegex(self.source,
                                    "Add-Content -Encoding UTF8 -Path \\$" + name + "Csv\\b")

    def test_drop_does_not_raise_or_retry(self):
        self.assertIn("if ($script:ms2RecordFaulted) { return $false }", self.source)
        self.assertIn("$script:ms2RecordFaulted = $true", self.source)
        self.assertIn("$script:ms2RecordErrors[$Stream]++", self.source)

    def test_recorded_only_after_success(self):
        self.assertRegex(self.source, r"if \(Invoke-MS2SafeCsvAppend -Path \$tickCsv[\s\S]{0,160}\$seenTicks\[\$tickKey\]=\$now")
        self.assertRegex(self.source, r"if \(Invoke-MS2SafeCsvAppend -Path \$creditCsv[\s\S]{0,160}\$creditSaved\[\$ticker\]=\$true")
        self.assertRegex(self.source, r"if \(Invoke-MS2SafeCsvAppend -Path \$signalCsv[\s\S]{0,170}\$loggedSignals\[\$logKey\]=\$true")

    def test_market_missing_mask_precedes_zero_coercion(self):
        self.assertLess(self.source.index("$sourceMissingFields = @()"),
                        self.source.index("if ($null -eq $volume) {$volume=0}"))
        names=("volume","vwap","bid","ask","bidQty","askQty","marketSell","marketBuy","over","under")
        for name in names:
            with self.subTest(field=name):
                self.assertIn("if ($null -eq $" + name + ") {$sourceMissingFields +=", self.source)

    def test_actionable_signal_blocks_on_fault_or_missing(self):
        self.assertIn('if($script:ms2RecordFaulted -or @($result.source_missing_fields).Count -gt 0)', self.source)
        self.assertIn("foreach ($candidate in $results) {$candidate.signal='保存品質不明・売買禁止'}", self.source)
        self.assertIn("recording_degraded=[bool]$script:ms2RecordFaulted", self.source)

    def test_hold_gate_checks_writer_and_missing(self):
        self.assertIn("$provisionalHoldTop5=if($script:ms2RecordFaulted){@()}else{", self.source)
        self.assertIn("@($_.source_missing_fields).Count -eq 0", self.source)

    def test_csv_schema_unchanged(self):
        for cols in (
            'captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note',
            'captured_at,ticker,name,price,volume,vwap,bid,ask,bid_qty,ask_qty,market_sell,market_buy,over,under',
            'captured_at,ticker,name,signal,strategy,signal_bar,entry,stop,target1,target2,market_state,breadth_pct,sector_breadth_pct,hold_signal,hold_score',
        ):
            self.assertIn(cols, self.source)

    def test_disk_is_still_synchronous_and_not_claimed_safe(self):
        self.assertIn("Synchronous finite-error containment, NOT an isolated/nonblocking Writer", self.source)
        self.assertNotIn("RssOrder(", self.source)


if __name__ == "__main__":
    unittest.main()
