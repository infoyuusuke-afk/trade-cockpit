"""P0-417: mandatory gate/identity contract, not a blanket green CI waiver."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORKFLOW=ROOT/".github/workflows/mobile-control-tests.yml"

class ExplicitMandatoryJobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=WORKFLOW.read_text(encoding="utf-8")
    def test_all_five_evidence_jobs_are_required(self):
        w=self.text
        for item in ("current-v10:", "archived-v8:", "archived-v9:",
                     "shadow-cross-version:", "full-suite-forensic:", "synthetic-acceptance:"):
            self.assertEqual(w.count("\n  "+item),1)
        self.assertIn("needs: [current-v10, archived-v8, archived-v9, shadow-cross-version, full-suite-forensic]",w)
        self.assertIn('if [ "$result" != success ]; then',w)
        self.assertIn("P0_417_SYNTHETIC_ACCEPTANCE=BLOCKED",w)
    def test_historical_pin_and_original_unittest_are_preserved(self):
        w=self.text
        self.assertGreaterEqual(w.count("b81b8877b12a33368e91e5e156a2fc7ac4529349"),3)
        self.assertGreaterEqual(w.count("7c67b3da874610a3121c1f0d1b48ad5fae445fbb"),2)
        self.assertIn("--mode v9-diagnostics",w)
        self.assertIn("--mode collector",w)
        self.assertIn("--mode v8",w)
        self.assertIn("ci_shadow_gap_reconciliation.py historical second_history",w)
        self.assertIn("python scripts/ci_mobile_migration_gate.py",w)
        forensic=(ROOT/"scripts/ci_mobile_migration_gate.py").read_text()
        self.assertIn('ci_attributed_unittest.py"), "--tests", "tests"',forensic)
        original=(ROOT/"scripts/ci_attributed_unittest.py").read_text()
        self.assertIn('"-s", args.tests, "-p", "test_*.py", "-v"',original)
        self.assertIn("return result.returncode",original)
    def test_no_skip_or_owner_operation_or_live_override(self):
        w=self.text
        for term in ("continue-on-error", "|| true", "skip: true", "Stop-Process",
                     "Start-Process", "RssOrder", "merge:", "REAL_SUBMIT_ALLOWED=true"):
            self.assertNotIn(term,w)
        self.assertIn("P0_417_MONOLITH_FULL_PASS=false",w)
        self.assertIn("STOP_ALLOWED=false",w)
        self.assertIn("CUTOVER_ELIGIBLE=false",w)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",w)
    def test_legacy_debt_cannot_grant_live_trading(self):
        s=(ROOT/"scripts/ci_mobile_migration_gate.py").read_text()
        self.assertIn("LEGACY_DEBT_UNCHANGED_NOT_FULL_PASS",s)
        self.assertIn('P0_417_MONOLITH_FULL_PASS=false',s)
        self.assertNotIn("STOP_ALLOWED=true",s)
        self.assertNotIn("REAL_SUBMIT_ALLOWED=true",s)

if __name__=="__main__": unittest.main()
