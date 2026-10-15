"""Synthetic-only negative checks for native release evidence classifier."""
import copy
import json
import unittest
from scripts.ms2_native_release_evidence_gate import classify


def fixture():
    return {
        "mode": "normal", "producer": "Native_PS5.1", "ps": "5.1.26100",
        "production": "P0_BLOCKED", "five_ms": "NOT_MET",
        "close_state": "NOT_CLOSED", "receipt_tail": "NOT_CLOSED",
        "concurrent_completion_observed": True,
        "restart_new_generation_no_replay": True,
        "attempts": 100, "queued": 100, "drops": 0,
        "states": {"PERSISTED_VERIFIED": 100},
        "cohorts": {"steady_ACCEPTED": {"full_ms": {
            "N": 99, "p99_ms": 2.0, "max_ms": 3.0}}},
        "latency_anatomy": {
            "status": "SYNTHETIC_SEGMENTS_REPORTED_ONLY",
            "n": 99, "over_5ms_count": 0, "slowest_full_ms": 3.0,
            "slowest_components_ms": {"capture_ms": 0.4, "packing_ms": 1.0,
                                      "submit_ms": 1.2, "unattributed_ms": 0.4},
            "largest_measured_component_at_peak": "submit_ms",
            "os_root_cause_proven": False, "production_latency_bound_proven": False,
        },
        "Writer_fsync": {"N": 100}, "verified_readback": {"N": 6},
        "receipt_to_verified_readback_upper_bound": {"N": 100},
        "private_symbol": "SYNTHETIC_SECRET",
        "record_digest": "a" * 64,
    }


class ReleaseGateTests(unittest.TestCase):
    def gate(self, **changed):
        return classify(dict(fixture(), **changed))

    def test_perfect_synthetic_still_no_promotion(self):
        x = self.gate()
        self.assertEqual(x["status"], "SYNTHETIC_EVIDENCE_CLASSIFIED_ONLY")
        self.assertTrue(x["normal_no_drop"])
        self.assertTrue(x["readback_count_consistent"])
        self.assertTrue(x["max_five_ms_observed"])
        for name in ("release_eligible", "real_submit_allowed", "promotion_eligible",
                     "statistical_edge_confirmed", "source_authenticated",
                     "pit_research_eligible", "shadow_forward_eligible"):
            self.assertFalse(x[name])
        self.assertEqual(x["eligible_observed_n"], 0)

    def test_no_raw_market_or_hash_leak(self):
        x = json.dumps(self.gate())
        self.assertNotIn("SYNTHETIC_SECRET", x)
        self.assertNotIn("a" * 64, x)

    def test_unknown_or_non_dict_report(self):
        x = classify(None)
        self.assertEqual(x["status"], "EVIDENCE_INVALID")
        self.assertFalse(x["release_eligible"])

    def test_python_fixture_not_native(self):
        self.assertIn("NATIVE_PROCESS_UNVERIFIED",
                      self.gate(producer="Python_protocol_fixture")["reasons"])

    def test_receipt_without_readback_fails_closed(self):
        x = self.gate(states={"UNKNOWN_TERMINAL": 100})
        self.assertIn("COUNT_INVALID_PERSISTED_READBACK", x["reasons"])
        self.assertEqual(x["status"], "EVIDENCE_INVALID")

    def test_accept_count_not_same_as_persisted(self):
        x = self.gate(states={"PERSISTED_VERIFIED": 99, "UNKNOWN_TERMINAL": 1})
        self.assertIn("ACCEPTED_VS_READBACK_CONFLICT", x["reasons"])
        self.assertFalse(x["readback_count_consistent"])

    def test_normal_drop_is_not_zero_loss(self):
        x = self.gate(queued=99, drops=1, states={"PERSISTED_VERIFIED": 99})
        self.assertIn("NORMAL_DROP_DETECTED", x["reasons"])
        self.assertFalse(x["normal_no_drop"])

    def test_attempts_mismatch_blocks(self):
        x = self.gate(attempts=100, queued=99, drops=0)
        self.assertIn("ATTEMPTS_NOT_ACCOUNTED", x["reasons"])

    def test_max_five_ms_failure_is_not_p99_pass(self):
        x = self.gate(cohorts={"steady_ACCEPTED": {"full_ms": {
            "N": 99, "p99_ms": 0.8, "max_ms": 58.57}}})
        self.assertIn("MAX_FIVE_MS_FAILED", x["reasons"])
        self.assertFalse(x["max_five_ms_observed"])

    def test_latency_null_not_imputed_as_zero(self):
        x = self.gate(cohorts={"steady_ACCEPTED": {"full_ms": {"N": 0}}})
        self.assertIn("LATENCY_EVIDENCE_MISSING_OR_INVALID", x["reasons"])

    def test_latency_nan_and_negative_block(self):
        for val in (float("nan"), float("inf"), -1, "2"):
            with self.subTest(val=repr(val)):
                x = self.gate(cohorts={"steady_ACCEPTED": {"full_ms": {
                    "N": 99, "p99_ms": 0.2, "max_ms": val}}})
                self.assertIn("LATENCY_EVIDENCE_MISSING_OR_INVALID", x["reasons"])

    def test_latency_out_of_order_block(self):
        x = self.gate(cohorts={"steady_ACCEPTED": {"full_ms": {
            "N": 99, "p99_ms": 2.1, "max_ms": 2.0}}})
        self.assertIn("LATENCY_EVIDENCE_MISSING_OR_INVALID", x["reasons"])

    def test_writer_fsync_and_readback_required(self):
        for name in ("Writer_fsync", "verified_readback", "receipt_to_verified_readback_upper_bound"):
            with self.subTest(name=name):
                x = self.gate(**{name: {"N": 0}})
                self.assertIn("MISSING_WRITER_EVIDENCE_" + name.upper(), x["reasons"])

    def test_stale_generation_block(self):
        x = self.gate(restart_new_generation_no_replay=False)
        self.assertIn("RESTART_NO_REPLAY_UNVERIFIED", x["reasons"])

    def test_not_closed_required(self):
        x = self.gate(close_state="CLOSED")
        self.assertIn("EVIDENCE_CLOSURE_STATE_UNAUTHORIZED", x["reasons"])

    def test_partial_overlap_not_sufficient(self):
        x = self.gate(concurrent_completion_observed=False)
        self.assertIn("ACTUAL_WRITER_OVERLAP_NOT_OBSERVED", x["reasons"])

    def test_bool_as_count_is_rejected(self):
        x = self.gate(queued=True)
        self.assertIn("COUNT_INVALID_QUEUED", x["reasons"])

    def test_small_n_fail_closed(self):
        x = self.gate(attempts=2, queued=2, states={"PERSISTED_VERIFIED": 2},
                      cohorts={"steady_ACCEPTED": {"full_ms": {
                          "N": 1, "p99_ms": 1.0, "max_ms": 1.0}}})
        self.assertIn("SYNTHETIC_COHORT_TOO_SMALL", x["reasons"])
        self.assertFalse(x["normal_no_drop"])

    def test_missing_latency_anatomy_refuses_synthetic_classification(self):
        row = fixture()
        row.pop("latency_anatomy")
        x = classify(row)
        self.assertEqual(x["status"], "EVIDENCE_INVALID")
        self.assertIn("CORRELATED_STAGE_EVIDENCE_MISSING", x["reasons"])

    def test_peak_from_another_sample_refused(self):
        row = fixture()
        row["latency_anatomy"]["slowest_full_ms"] = 12.0
        x = classify(row)
        self.assertIn("CORRELATED_STAGE_EVIDENCE_INCONSISTENT", x["reasons"])
        self.assertFalse(x["release_eligible"])

    def test_missing_stage_rejected(self):
        row = fixture()
        row["latency_anatomy"]["slowest_components_ms"].pop("submit_ms")
        x = classify(row)
        self.assertEqual(x["status"], "EVIDENCE_INVALID")

    def test_anatomy_does_not_authorize_live_if_fast(self):
        x = self.gate()
        self.assertEqual(x["latency_anatomy"]["status"], "SYNTHETIC_CORRELATED_TIMING_ONLY")
        self.assertFalse(x["source_authenticated"])
        self.assertFalse(x["release_eligible"])

    def test_deterministic(self):
        self.assertEqual(self.gate(), self.gate())


if __name__ == "__main__":
    unittest.main()
