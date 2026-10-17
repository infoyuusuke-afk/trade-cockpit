"""Synthetic contract for explicit historical/current provenance."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ci_current_v10_lane as lane


class Stub(unittest.TestCase):
    def test_pass(self): self.assertTrue(True)


class ProvenanceTests(unittest.TestCase):
    def test_legacy_categories_explicit(self):
        names=[
            "test_v8_controller.Test.test_a",
            "test_v9_alert_log.Test.test_a",
            "test_ai_cockpit_v8_controller_contract.Test.test_a",
            "test_ai_cockpit_v9_contract.Test.test_a",
            "test_collector_workbook_identity.Contract.test_any",
            "test_ai_shadow_supervisor.ContractSourceTests.test_controller_and_gateway_keep_real_submit_locked",
        ]
        for item in names:self.assertTrue(lane.is_historic(item),item)
        for item in ["test_v10_collector_workbook_contract.C.test_x",
                     "test_ai_shadow_supervisor.CycleTests.test_missing_ledger_is_not_treated_as_healthy",
                     "test_ci_failure_regression_guard.C.test_x"]:
            self.assertFalse(lane.is_historic(item),item)

    def test_no_silent_legacy_move(self):
        self.assertEqual(lane.HISTORY_COMMIT,"b81b8877b12a33368e91e5e156a2fc7ac4529349")
        script=(Path(__file__).resolve().parents[1]/"scripts"/"ci_current_v10_lane.py").read_text()
        self.assertIn("ADDITIONAL_NOT_REPLACING_MONOLITH",script)
        workflow=(Path(__file__).resolve().parents[1]/".github/workflows"/"mobile-control-tests.yml").read_text()
        self.assertIn("python scripts/ci_mobile_migration_gate.py", workflow)
        gate=(Path(__file__).resolve().parents[1]/"scripts"/"ci_mobile_migration_gate.py").read_text()
        self.assertIn('ci_attributed_unittest.py"), "--tests", "tests"',gate)
        self.assertIn("P0_417_MONOLITH_FULL_PASS=false",gate)

    def test_partition_reports_accountability(self):
        case=Stub("test_pass")
        s=unittest.TestSuite([unittest.TestSuite([case])])
        with self.assertRaisesRegex(RuntimeError,"DISCOVERY_INVENTORY_UNSAFE"):
            lane.partition_discovery(s)
