"""Fail-closed contract for the exactly-one historic V9 Shadow gap."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"scripts"))
import ci_shadow_gap_reconciliation as mod

def example(gaps=None):
    if gaps is None:
        gaps=[mod.GAP]
    return ("P0_417_COVERAGE_CURRENT_ARCHIVE=126\n"
            "P0_417_COVERAGE_EXACT_MATCHED=125\n"
            "P0_417_COVERAGE_UNMAPPED="+str(len(gaps))+"\n"
            + "".join("P0_417_UNMAPPED_ID="+x+"\n" for x in gaps)
            + "P0_417_COVERAGE_RESULT=GAP_PRESENT\n")


class ShadowGapReconciliationTests(unittest.TestCase):
    def test_exact_one_and_original_fail_required(self):
        self.assertTrue(mod.reconcile(example(), 1))
        self.assertFalse(mod.reconcile(example(), 0))

    def test_unexpected_second_gap_is_blocked(self):
        self.assertFalse(mod.reconcile(example([mod.GAP,"test_v9_other.Test.test_x"]),1))
        self.assertFalse(mod.reconcile(example([]),1))

    def test_historical_completeness_cannot_be_falsely_reported(self):
        self.assertFalse(mod.reconcile(example().replace("125","126"),1))
        self.assertFalse(mod.reconcile(example().replace("GAP_PRESENT","COMPLETE"),1))
        self.assertFalse(mod.reconcile(example().replace("CURRENT_ARCHIVE=126","CURRENT_ARCHIVE=125"),1))

    def test_no_legacy_code_restore_or_stop_operations(self):
        source=(ROOT/"scripts"/"ci_shadow_gap_reconciliation.py").read_text(encoding="utf-8")
        for forbidden in ("Stop-Process","Start-Process","RssOrder","-IncludeStopDryRun",
                          "REAL_SUBMIT_ALLOWED=true","CUTOVER_ELIGIBLE=true"):
            self.assertNotIn(forbidden,source)
        for expected in ("ACCOUNTED_FOR_NOT_HISTORICALLY_VERIFIED",
                         "P0_417_HISTORIC_ID_COVERAGE=125_OF_126",
                         "STOP_ALLOWED=false","CUTOVER_ELIGIBLE=false","REAL_SUBMIT_ALLOWED=false"):
            self.assertIn(expected,source)

    def test_unverified_source_gate_remains_strict(self):
        source=(ROOT/"scripts"/"ci_historic_id_coverage.py").read_text(encoding="utf-8")
        self.assertIn('return 0 if not report["unmapped"] else 1',source)
        self.assertIn('P0_417_COVERAGE_RESULT=',source)


if __name__=="__main__":
    unittest.main()
