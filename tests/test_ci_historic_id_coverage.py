"""P0-417 fail-closed historical test-ID correspondence contract."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_historic_id_coverage as c


class CoverageContract(unittest.TestCase):
    def test_current_source_includes_explicit_shadow_and_collector(self):
        result=c.test_ids(Path(__file__).resolve().parents[1])
        self.assertIn("test_collector_workbook_identity",result)
        self.assertIn("test_ai_shadow_supervisor",result)
        self.assertIn(next(iter(c.EXACT)),result["test_ai_shadow_supervisor"])

    def test_no_invented_module_mapping(self):
        self.assertTrue(c.classify_id("test_v9_cache_rest.CacheRestTests.test_script_is_ascii_and_read_only"))
        self.assertTrue(c.classify_id("test_collector_workbook_identity.CollectorWorkbookIdentityContract.test_deploy_runtime_only_does_not_start_excel_or_stop_the_collector"))
        self.assertFalse(c.classify_id("test_v10_collector_workbook_contract.V10CollectorSourceContract.test_no_order_and_controller_fail_closed"))
        self.assertFalse(c.classify_id("test_ai_shadow_supervisor.CycleTests.test_missing_ledger_is_not_treated_as_healthy"))

    def test_missing_historical_test_id_is_reported(self):
        with tempfile.TemporaryDirectory(prefix="p0417-historic-id-") as d:
            root=Path(d)
            (root/"tests").mkdir()
            (root/"tests"/"test_v9_fake.py").write_text("import unittest\nclass A(unittest.TestCase):\n    def test_kept(self): pass\n",encoding="utf-8")
            result=c.audit(Path(__file__).resolve().parents[1],root)
            self.assertGreater(len(result["unmapped"]),0)
            self.assertEqual(result["historical_executed"],1)
            self.assertFalse(any(x.startswith("test_ai_shadow_supervisor") for x in result["historical_only"]))

    def test_observed_history_pin_is_immutable(self):
        self.assertEqual(c.PIN,"b81b8877b12a33368e91e5e156a2fc7ac4529349")


if __name__=="__main__":
    unittest.main()
