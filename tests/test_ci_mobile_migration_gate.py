"""Synthetic negative tests for P0-417 monolithic forensic migration gate."""
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from ci_mobile_migration_gate import classify,EXACT_MARKERS

def fixture():
    return "\n".join(sorted(EXACT_MARKERS))+ "\nP0_417_EXECUTED=1950\n"

class MigrationGate(unittest.TestCase):
    def test_exact_known_115_stays_labelled_as_debt(self):
        self.assertEqual(classify(fixture(),1),"LEGACY_DEBT_UNCHANGED_NOT_FULL_PASS")
    def test_preexisting_failures_are_not_full_pass(self):
        self.assertEqual(classify(fixture(),0),"BLOCKED_UNEXPECTED_FAILURE")
    def test_new_failure_blocks(self):
        s=fixture().replace("P0_417_NEW_FAILURES=0","P0_417_NEW_FAILURES=1")
        self.assertEqual(classify(s,1),"BLOCKED_UNEXPECTED_FAILURE")
    def test_missing_historic_failure_blocks(self):
        s=fixture().replace("P0_417_MISSING_KNOWN_FAILURES=0","P0_417_MISSING_KNOWN_FAILURES=1")
        self.assertEqual(classify(s,1),"BLOCKED_UNEXPECTED_FAILURE")
    def test_missing_test_inventory_blocks(self):
        self.assertEqual(classify("\n".join(sorted(EXACT_MARKERS))+"\n",1),
                         "BLOCKED_INCOMPLETE_DISCOVERY")
    def test_changed_known_failure_count_blocks(self):
        s=fixture().replace("P0_417_BASELINE_OBSERVED=115","P0_417_BASELINE_OBSERVED=114")
        self.assertEqual(classify(s,1),"BLOCKED_UNEXPECTED_FAILURE")
    def test_truncated_discovery_blocks(self):
        self.assertEqual(classify(fixture().replace("1950","200"),1),
                         "BLOCKED_INCOMPLETE_DISCOVERY")
    def test_documented_original_full_suite_command_retained(self):
        code=(ROOT/"scripts"/"ci_mobile_migration_gate.py").read_text()
        self.assertIn('ci_attributed_unittest.py"), "--tests", "tests"',code)
        self.assertIn("P0_417_MONOLITH_FULL_PASS=false",code)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",code)
if __name__=="__main__":unittest.main()
