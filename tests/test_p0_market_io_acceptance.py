import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.p0_market_io_acceptance import (
    evaluate_market_io,
    evaluate_resume,
    main,
    synthetic_bundle,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 5, 9, 16, 5, tzinfo=JST)


class MarketIoHarnessTests(unittest.TestCase):
    def test_matching_fixture_is_not_a_live_pass(self):
        report = evaluate_market_io(synthetic_bundle(), now=NOW)
        self.assertEqual(report["live_acceptance"], "NOT_LIVE")
        self.assertEqual(report["comparator"], "MATCH")
        self.assertEqual(report["gates"]["G0"], "OWNER_ACTION_PENDING")
        self.assertEqual(report["gates"]["G1"], "OWNER_ACTION_PENDING")
        self.assertEqual(report["gates"]["G4"], "NOT_LIVE")
        self.assertFalse(report["real_submit_allowed"])
        self.assertEqual(len(set(report["fingerprints"].values())), 1)

    def test_relabeling_a_fixture_as_owner_evidence_stays_not_live(self):
        bundle = synthetic_bundle()
        bundle["evidence_origin"] = "owner_pc_observed"
        report = evaluate_market_io(bundle, now=NOW)
        self.assertEqual(report["live_acceptance"], "NOT_LIVE")
        self.assertEqual(report["evidence_origin"], "synthetic_fixture")

    def test_price_mismatch_is_visible_and_still_not_live(self):
        report = evaluate_market_io(synthetic_bundle(other_price=101.0), now=NOW)
        self.assertEqual(report["comparator"], "MISMATCH")
        self.assertIn("PRICE_MISMATCH", report["reasons"])
        self.assertEqual(report["live_acceptance"], "NOT_LIVE")

    def test_old_evidence_is_stale_for_an_owner_bundle(self):
        bundle = synthetic_bundle()
        del bundle["generated_by"]
        bundle["evidence_origin"] = "owner_pc_observed"
        later = NOW + timedelta(hours=2)
        report = evaluate_market_io(bundle, now=later)
        self.assertEqual(report["live_acceptance"], "DATA_PLANE_FAIL")
        self.assertIn("EVIDENCE_STALE", report["reasons"])
        self.assertEqual(report["gates"]["G0"], "OWNER_ACTION_PENDING")
        self.assertEqual(report["gates"]["G4"], "FAIL")

    def test_owner_bundle_can_match_without_closing_g0(self):
        bundle = synthetic_bundle()
        del bundle["generated_by"]
        bundle["evidence_origin"] = "owner_pc_observed"
        bundle["rss"][0]["symbol"] = "285A.T"
        for key in ("collector", "gateway"):
            bundle[key]["all_targets"][0]["symbol"] = "285A.T"
            bundle[key]["all_targets"][0]["ticker"] = "285A.T"
        bundle["strategy_input"]["quotes"][0]["symbol"] = "285A.T"
        bundle["ms2_display"][0]["symbol"] = "285A.T"
        report = evaluate_market_io(bundle, now=NOW)
        self.assertEqual(report["comparator"], "MATCH")
        self.assertEqual(report["live_acceptance"], "DATA_PLANE_PASS")
        self.assertEqual(report["gates"]["G0"], "OWNER_ACTION_PENDING")
        self.assertEqual(report["gates"]["G1"], "OWNER_ACTION_PENDING")
        self.assertEqual(report["gates"]["G4"], "PASS")
        self.assertEqual(report["gates"]["G6"], "PASS")
        self.assertIn("G0_G1_STILL_PENDING", report["reasons"])

    def test_real_submit_true_fails_closed(self):
        bundle = synthetic_bundle()
        del bundle["generated_by"]
        bundle["evidence_origin"] = "owner_pc_observed"
        bundle["collector"]["real_submit_allowed"] = True
        report = evaluate_market_io(bundle, now=NOW)
        self.assertIn("REAL_SUBMIT_NOT_FALSE", report["reasons"])
        self.assertEqual(report["gates"]["G6"], "FAIL")
        self.assertEqual(report["live_acceptance"], "DATA_PLANE_FAIL")

    def test_missing_strategy_input_and_ms2_display_block_the_chain(self):
        bundle = synthetic_bundle()
        del bundle["generated_by"]
        bundle["evidence_origin"] = "owner_pc_observed"
        del bundle["strategy_input"]
        del bundle["ms2_display"]
        report = evaluate_market_io(bundle, now=NOW)
        self.assertIn("STRATEGY_INPUT_ABSENT", report["reasons"])
        self.assertIn("MS2_DISPLAY_ABSENT", report["reasons"])
        self.assertEqual(report["gates"]["G4"], "FAIL")

    def test_resume_without_agreement_fails_and_a_fixture_cannot_pass_it(self):
        failed = {"comparator": "MISMATCH", "live_acceptance": "DATA_PLANE_FAIL", "gates": {"G4": "FAIL"}}
        current = synthetic_bundle()
        self.assertEqual(evaluate_resume(failed, current)["status"], "NOT_LIVE")
        del current["generated_by"]
        current["evidence_origin"] = "owner_pc_observed"
        blocked = evaluate_resume(failed, current)
        self.assertEqual(blocked["status"], "FAIL")
        self.assertEqual(blocked["reason"], "AUTO_RESUME_WITHOUT_AGREEMENT")
        current["agreement_checked"] = True
        self.assertEqual(evaluate_resume(failed, current)["status"], "PASS")

    def test_missing_evidence_file_does_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / "absent.json")
            self.assertEqual(main(["--evidence", missing]), 2)

    def test_cli_prints_not_live_for_a_fixture_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.json"
            path.write_text(json.dumps(synthetic_bundle()), encoding="utf-8")
            self.assertEqual(main(["--evidence", str(path)]), 0)


if __name__ == "__main__":
    unittest.main()
