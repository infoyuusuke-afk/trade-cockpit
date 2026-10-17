"""P0-417 acceptance must not suppress or relabel old CI failures."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / ".github/workflows/p0-417-acceptance-matrix.yml"
MOBILE = ROOT / ".github/workflows/mobile-control-tests.yml"
DOC = ROOT / "docs/P0_417_ACCEPTANCE_MATRIX.md"
PIN = "b81b8877b12a33368e91e5e156a2fc7ac4529349"


class AcceptanceMatrixContract(unittest.TestCase):
    def test_four_independent_jobs_and_immutable_historical_pin(self):
        s = MATRIX.read_text(encoding="utf-8")
        for job in ("v10-current:", "legacy-v8-historic:",
                    "legacy-v9-historic:", "v2-readonly-synthetic:"):
            self.assertEqual(s.count("\n  " + job), 1)
        self.assertEqual(s.count("ref: " + PIN), 2)
        self.assertIn("--mode v8", s)
        self.assertIn("--mode collector", s)
        self.assertIn("--mode v9-diagnostics", s)
        self.assertIn("-p test_v10_collector_workbook_contract.py -v", s)
        self.assertIn("-p test_v10_owner_state_metadata_v2.py -v", s)
        self.assertIn("-p test_v10_metadata_v2_safety_contract.py -v", s)

    def test_no_mutating_owner_actions_in_matrix(self):
        s = MATRIX.read_text(encoding="utf-8")
        for token in ("-IncludeStopDryRun", "Stop-Process", "Start-Process",
                      "Invoke-Expression", "merge", "checkout -f",
                      "REAL_SUBMIT_ALLOWED=true", "CONTROLLER_STARTED=1"):
            self.assertNotIn(token, s)

    def test_monolithic_ci_retains_fail_visible_full_discovery(self):
        s = MOBILE.read_text(encoding="utf-8")
        self.assertIn("python scripts/ci_attributed_unittest.py --tests tests", s)
        runner = (ROOT / "scripts/ci_attributed_unittest.py").read_text(encoding="utf-8")
        self.assertIn('"-s", args.tests, "-p", "test_*.py", "-v"', runner)
        self.assertIn("return result.returncode", runner)

    def test_document_never_reclassifies_synthetic_as_live(self):
        s = DOC.read_text(encoding="utf-8")
        for text in ("MONOLITHIC_CI=FAIL", "OWNER_V10_RUNTIME=BLOCKED",
                     "INDEPENDENT_REVIEW=PENDING", "STOP_ALLOWED=false",
                     "CUTOVER_ELIGIBLE=false", "REAL_SUBMIT_ALLOWED=false"):
            self.assertIn(text, s)


if __name__ == "__main__":
    unittest.main()
