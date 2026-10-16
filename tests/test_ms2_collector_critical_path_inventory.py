"""Synthetic/public-code-only static inspection regression, no private MS2 data."""
import json
from pathlib import Path
import unittest

from scripts.ms2_collector_critical_path_inventory import inspect

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"


class CollectorCriticalPathAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = COLLECTOR.read_text(encoding="utf-8-sig")
        cls.result = inspect(cls.text)

    def test_actual_main_has_blocking_signatures(self):
        self.assertEqual(self.result["status"], "CRITICAL_PATH_BLOCKING_RISKS_PRESENT")

    def test_actual_main_has_nine_sync_csv_sinks(self):
        self.assertGreaterEqual(self.result["risk_counts"]["CSV_DIRECT_APPEND"], 9)

    def test_actual_main_rechecks_csv_headers(self):
        self.assertGreaterEqual(self.result["risk_counts"]["PER_POLL_HEADER_CHECK"], 10)

    def test_json_writes_are_in_main(self):
        self.assertGreaterEqual(self.result["risk_counts"]["JSON_ATOMIC_WRITE"], 2)

    def test_rowset_write_is_present(self):
        self.assertGreaterEqual(self.result["risk_counts"]["ROWSET_WRITE"], 2)

    def test_com_retry_wait_possible_but_not_measured_outage(self):
        self.assertEqual(
            self.result["risk_counts"]["EXCEL_COM_RETRY_SLEEP_POSSIBLE_MS"],
            60000,
        )
        self.assertIsNone(self.result["actual_latency_ms"])
        self.assertIsNone(self.result["actual_outage_count"])

    def test_atomic_json_retry_sleep_distinct(self):
        self.assertEqual(
            self.result["risk_counts"]["FILE_REPLACE_RETRY_SLEEP_POSSIBLE_MS"],
            600,
        )

    def test_process_isolation_not_proved_by_static_signature(self):
        for name in ("main_loop_isolated", "disk_io_isolated",
                     "excel_com_bounded_os_time", "monitor_continuity_verified",
                     "production_ready", "real_submit_allowed",
                     "promotion_eligible"):
            self.assertFalse(self.result[name], name)

    def test_no_shadow_or_performance_eligibility(self):
        self.assertEqual(self.result["eligible_observed_n"], 0)

    def test_missing_code_not_assumed_safe(self):
        x = inspect("")
        self.assertEqual(x["status"], "UNKNOWN_UNVERIFIED")
        self.assertIn("SOURCE_MISSING_OR_INVALID", x["risk_counts"])

    def test_restructured_code_not_assumed_safe(self):
        x = inspect("function MyCollector {}")
        self.assertEqual(x["status"], "UNKNOWN_UNVERIFIED")
        self.assertFalse(x["production_ready"])

    def test_synthetic_safe_append_still_counts_as_sync(self):
        synthetic = "while ($true) { Invoke-MS2SafeCsvAppend -Path $p -Line $v }"
        x = inspect(synthetic)
        self.assertEqual(x["status"], "CRITICAL_PATH_BLOCKING_RISKS_PRESENT")
        self.assertEqual(x["risk_counts"]["SAFE_APPEND_STILL_SYNCHRONOUS"], 1)

    def test_true_zero_and_unknown_not_inferred_from_source_scan(self):
        x = inspect(self.text)
        self.assertNotIn("pit_eligible", x)
        self.assertFalse(x["production_ready"])

    def test_no_private_paths_symbols_or_source_body_in_report(self):
        result = json.dumps(self.result, sort_keys=True)
        self.assertNotIn("285A.T", result)
        self.assertNotIn("MS2_RSS_100_Collector.ps1", result)
        self.assertNotIn("C:\\Users", result)

    def test_deterministic_counts(self):
        self.assertEqual(self.result, inspect(self.text))


if __name__ == "__main__":
    unittest.main()
