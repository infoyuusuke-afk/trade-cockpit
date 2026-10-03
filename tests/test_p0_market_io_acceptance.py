import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.p0_market_io_acceptance import (
    evaluate_market_io,
    evaluate_resume,
    main,
    quote_clock,
    run_acceptance,
    synthetic_bundle,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 5, 9, 16, 5, tzinfo=JST)


class MarketIoHarnessTests(unittest.TestCase):
    def test_matching_fixture_is_not_a_live_pass(self):
        report = evaluate_market_io(synthetic_bundle(), now=NOW)
        self.assertEqual(report["live_acceptance"], "NOT_LIVE")
        self.assertEqual(report["freshness"], "UNVERIFIED")
        self.assertIn("TIMESTAMP_UNVERIFIED", report["reasons"])
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
        for row in bundle["rss"] + bundle["ms2_display"] + bundle["strategy_input"]["quotes"]:
            row["quote_date"] = "2026-10-05"
            row["quote_date_source"] = "rss_cell"
        for key in ("collector", "gateway"):
            item = bundle[key]["all_targets"][0]
            item["quote_date"] = "2026-10-05"
            item["quote_date_source"] = "rss_cell"
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

    def test_collector_clock_date_does_not_verify_a_time_only_stamp(self):
        quote = {"source_timestamp": "09:16:00", "quote_date": "2026-10-05", "quote_date_source": "collector_clock"}
        instant, state = quote_clock(quote)
        self.assertIsNone(instant)
        self.assertEqual(state, "UNVERIFIED")

    def test_rss_cell_date_is_the_only_completion_that_verifies(self):
        instant, state = quote_clock({
            "source_timestamp": "09:16:00",
            "quote_date": "2026-10-05",
            "quote_date_source": "rss_cell",
        })
        self.assertEqual(state, "VERIFIED")
        self.assertEqual(instant.tzinfo, JST)
        self.assertEqual(instant.date().isoformat(), "2026-10-05")

    def test_one_run_without_files_stays_not_run_and_stores_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            evidence = run_acceptance(root / "in", root / "out", now=NOW)
            self.assertEqual(evidence["report"]["live_acceptance"], "NOT_RUN")
            self.assertEqual(evidence["report"]["gates"]["G0"], "OWNER_ACTION_PENDING")
            self.assertEqual(evidence["report"]["gates"]["G2"], "NOT_RUN")
            self.assertEqual(evidence["report"]["gates"]["G6"], "NOT_RUN")
            saved = json.loads((root / "out" / "latest_evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["run_id"], evidence["run_id"])
            self.assertNotIn("\"price\"", json.dumps(saved))
            self.assertFalse(saved["real_submit_allowed"])

    def test_one_run_compares_collector_and_gateway_without_passing_g0(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            incoming = root / "in"
            incoming.mkdir()
            bundle = synthetic_bundle()
            row = bundle["collector"]["all_targets"][0]
            row["quote_date"] = "2026-10-05"
            row["quote_date_source"] = "rss_cell"
            (incoming / "live_ms2.json").write_text(json.dumps(bundle["collector"]), encoding="utf-8")
            (incoming / "gateway_live.json").write_text(json.dumps(bundle["gateway"]), encoding="utf-8")
            (incoming / "rss_rows.json").write_text(json.dumps([{
                "symbol": "TEST",
                "price": 100.0,
                "source_timestamp": "09:16:00",
                "source": "MarketSpeed II RSS / local PC",
                "quote_date": "2026-10-05",
                "quote_date_source": "rss_cell",
            }]), encoding="utf-8")
            evidence = run_acceptance(incoming, root / "out", now=NOW)
            report = evidence["report"]
            self.assertEqual(report["gates"]["G0"], "OWNER_ACTION_PENDING")
            self.assertEqual(report["gates"]["G1"], "OWNER_ACTION_PENDING")
            self.assertEqual(report["gates"]["G4"], "FAIL")
            self.assertIn("MS2_DISPLAY_ABSENT", report["reasons"])
            self.assertNotEqual(report["live_acceptance"], "DATA_PLANE_PASS")
            self.assertNotIn("\"price\"", json.dumps(evidence))
            again = run_acceptance(incoming, root / "out", now=NOW)
            self.assertEqual(again["run_id"], evidence["run_id"])
            self.assertEqual(again["report"]["gates"]["G5"], "FAIL")

    def test_cli_prints_not_live_for_a_fixture_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.json"
            path.write_text(json.dumps(synthetic_bundle()), encoding="utf-8")
            self.assertEqual(main(["--evidence", str(path)]), 0)


if __name__ == "__main__":
    unittest.main()
