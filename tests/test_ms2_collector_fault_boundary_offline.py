"""Offline-only regression suite: actual checked-in source inventory + synthetic faults."""
from pathlib import Path
import json
import unittest

from scripts.ms2_collector_fault_boundary_offline import (
    inspect_collector_source,
    model_failure_boundary,
)

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_SOURCE = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
HEALTHY = dict(price=123.5, volume=0, quote_age_ms=5, ttl_ms=100,
               writer_state="PERSISTED_VERIFIED", health_state="HEALTHY",
               source_proven=True, available_at_proven=True)


class CollectorFaultBoundaryTests(unittest.TestCase):
    def test_current_repo_source_has_inline_csv_writes(self):
        r = inspect_collector_source(COLLECTOR_SOURCE.read_text(encoding="utf-8-sig"))
        self.assertEqual(r["status"], "RISK_PRESENT")
        self.assertEqual(r["risk_counts"]["SYNC_FILE_WRITES_IN_COLLECTOR_LOOP"], 4)
        self.assertEqual(r["risk_counts"]["SEQUENTIAL_NONATOMIC_TRIPLET_WRITES"], 1)
        self.assertEqual(r["risk_counts"]["TICK_WRITE_PRECEDES_RESULT_ASSEMBLY"], 1)
        self.assertGreaterEqual(r["risk_counts"]["MISSING_AS_ZERO_IN_MARKET_FIELDS"], 8)
        self.assertFalse(r["monitoring_isolation_proven"])
        self.assertFalse(r["ready_for_live_patch"])

    def test_static_scan_is_not_proof_of_remediation(self):
        r = inspect_collector_source("no known write function")
        self.assertEqual(r["status"], "UNKNOWN_REQUIRES_NEW_REVIEW")
        self.assertFalse(r["monitoring_isolation_proven"])

    def test_missing_source_remains_unverified(self):
        self.assertIn("SOURCE_UNAVAILABLE", inspect_collector_source(None)["risk_counts"])

    def test_status_unknown_if_source_restructured(self):
        self.assertEqual(inspect_collector_source("function Other-Collector {}")["status"],
                         "UNKNOWN_REQUIRES_NEW_REVIEW")

    def test_healthy_synthetic_cannot_authorize_trading(self):
        r = model_failure_boundary(**HEALTHY)
        self.assertEqual(r["status"], "RESEARCH_CANDIDATE_ONLY")
        self.assertFalse(r["actionable_signal_allowed"])
        self.assertFalse(r["real_submit_allowed"])
        self.assertFalse(r["monitor_continuity_measured"])
        self.assertFalse(r["worst_case_latency_proven"])

    def test_writer_queue_alone_is_not_persistence(self):
        r = model_failure_boundary(**dict(HEALTHY, writer_state="QUEUED"))
        self.assertIn("PERSISTENCE_NOT_VERIFIED", r["reason_codes"])

    def test_unverified_fsync_claim_rejected(self):
        r = model_failure_boundary(**dict(HEALTHY, writer_state="PERSISTENCE_CLAIM"))
        self.assertIn("PERSISTENCE_NOT_VERIFIED", r["reason_codes"])

    def test_prequeue_drop_fails_closed_but_monitor_should_continue(self):
        r = model_failure_boundary(**dict(HEALTHY, writer_state="PRE_QUEUE_DROP"))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertTrue(r["market_monitor_should_continue"])
        self.assertTrue(r["kill_switch_should_remain_available"])

    def test_writer_rejection_fails_closed(self):
        r = model_failure_boundary(**dict(HEALTHY, writer_state="POST_QUEUE_REJECT"))
        self.assertIn("PERSISTENCE_NOT_VERIFIED", r["reason_codes"])

    def test_unknown_writer_fails_closed(self):
        r = model_failure_boundary(**dict(HEALTHY, writer_state="UNKNOWN"))
        self.assertFalse(r["actionable_signal_allowed"])
        self.assertIn("PERSISTENCE_NOT_VERIFIED", r["reason_codes"])

    def test_bogus_writer_state_fails_closed(self):
        r = model_failure_boundary(**dict(HEALTHY, writer_state=["PERSISTED_VERIFIED"]))
        self.assertIn("WRITER_STATE_INVALID", r["reason_codes"])

    def test_none_and_zero_price_not_interchangeable(self):
        for price in (None, 0, -1, "123", float("nan"), float("inf")):
            with self.subTest(price=repr(price)):
                r = model_failure_boundary(**dict(HEALTHY, price=price))
                self.assertIn("PRICE_INVALID_OR_MISSING", r["reason_codes"])

    def test_known_volume_zero_allowed_as_observation(self):
        r = model_failure_boundary(**HEALTHY)
        self.assertNotIn("VOLUME_INVALID_OR_MISSING", r["reason_codes"])

    def test_missing_volume_cannot_be_imputed_as_zero(self):
        for v in (None, -1, "0", float("nan"), float("inf")):
            with self.subTest(volume=repr(v)):
                r = model_failure_boundary(**dict(HEALTHY, volume=v))
                self.assertIn("VOLUME_INVALID_OR_MISSING", r["reason_codes"])

    def test_stale_or_missing_age_denied(self):
        for age in (None, -1, 101, float("nan"), float("inf"), "0"):
            with self.subTest(age=repr(age)):
                r = model_failure_boundary(**dict(HEALTHY, quote_age_ms=age))
                self.assertIn("QUOTE_STALE_OR_TIME_UNKNOWN", r["reason_codes"])

    def test_negative_or_unknown_ttl_denied(self):
        for ttl in (None, -10, 1, "100", float("inf")):
            with self.subTest(ttl=repr(ttl)):
                r = model_failure_boundary(**dict(HEALTHY, ttl_ms=ttl))
                self.assertIn("QUOTE_STALE_OR_TIME_UNKNOWN", r["reason_codes"])

    def test_stopped_source_blocks_action_but_not_monitor(self):
        r = model_failure_boundary(**dict(HEALTHY, health_state="STOPPED"))
        self.assertEqual(r["status"], "BLOCKED")
        self.assertTrue(r["risk_monitor_should_continue"])
        self.assertIn("SOURCE_HEALTH_NOT_READY", r["reason_codes"])

    def test_missing_producer_authentication_blocks(self):
        r = model_failure_boundary(**dict(HEALTHY, source_proven=False))
        self.assertIn("SOURCE_AUTHENTICITY_NOT_PROVEN", r["reason_codes"])

    def test_available_at_not_proven_blocks(self):
        r = model_failure_boundary(**dict(HEALTHY, available_at_proven=False))
        self.assertIn("AVAILABLE_AT_NOT_PROVEN", r["reason_codes"])

    def test_no_private_inputs_in_return_payload(self):
        bad = dict(HEALTHY, price=314159.25, volume=271828)
        s = json.dumps(model_failure_boundary(**bad), sort_keys=True)
        self.assertNotIn("314159", s)
        self.assertNotIn("271828", s)

    def test_determinism_and_no_external_state(self):
        a = model_failure_boundary(**dict(HEALTHY, writer_state="UNKNOWN"))
        b = model_failure_boundary(**dict(HEALTHY, writer_state="UNKNOWN"))
        self.assertEqual(a, b)

    def test_multiple_independent_risks_retained(self):
        r = model_failure_boundary(price=None, volume=None, quote_age_ms=None,
                                   ttl_ms=None, writer_state="UNKNOWN",
                                   health_state="UNKNOWN", source_proven=None,
                                   available_at_proven=None)
        self.assertGreaterEqual(len(r["reason_codes"]), 6)
        self.assertEqual(r["eligible_observed_n"], 0)
        self.assertFalse(r["statistical_edge_confirmed"])


if __name__ == "__main__":
    unittest.main()
