"""Synthetic-only tests for future MS2 receipt semantics; no real market data."""
from copy import deepcopy
import json
import unittest

from scripts import ms2_observation_receipt_contract as c


SHA = "a" * 40
SESSION = "b" * 32
DIGEST = "c" * 64
START = "2026-10-14T09:00:00+09:00"
FINISH = "2026-10-14T09:00:01+09:00"
AVAILABLE = "2026-10-14T09:00:02+09:00"
CREATED = "2026-10-14T09:00:03+09:00"
QUEUED = "2026-10-14T09:00:04+09:00"
CLAIMED = "2026-10-14T09:00:05+09:00"
DECISION_AT = "2026-10-14T09:00:06+09:00"
STREAMS = ("MARKET_SNAPSHOT", "CONDITION", "UNDER_OVER")


def capture(stream="MARKET_SNAPSHOT", poll_seq=1):
    return dict(schema_version=c.SCHEMA_VERSION,
                producer_sha=SHA, session_id=SESSION, poll_seq=poll_seq,
                symbol="PRIVATE_SYNTHETIC.T", stream=stream,
                record_sha256=DIGEST, read_started_at=START,
                read_finished_at=FINISH, available_at=AVAILABLE, created_at=CREATED)


def receipt(source, phase="QUEUED", at=QUEUED):
    return dict(schema_version=c.SCHEMA_VERSION,
                session_id=source["session_id"], poll_seq=source["poll_seq"],
                symbol=source["symbol"], stream=source["stream"],
                record_sha256=source["record_sha256"], phase=phase, at=at)


def health():
    return dict(schema_version="local-source-health-1.0",
                source="MS2_RSS", state="HEALTHY",
                observed_at=DECISION_AT, last_data_at=AVAILABLE,
                consecutive_failures=0, reasons=[])


def fixture():
    caps = [capture(stream) for stream in STREAMS]
    recs = []
    for row in caps:
        recs.extend([receipt(row), receipt(row, "PERSISTENCE_CLAIM", CLAIMED)])
    return caps, recs


class MS2ReceiptContractTests(unittest.TestCase):
    def assess(self, caps=None, recs=None, source_health=None, decisions=None):
        if caps is None or recs is None:
            cap0, rec0 = fixture()
            caps = cap0 if caps is None else caps
            recs = rec0 if recs is None else recs
        return c.evaluate(caps, recs, health() if source_health is None else source_health, decisions)

    def test_all_claimed_but_not_verified(self):
        result = self.assess()
        self.assertEqual(result["status"], "STRUCTURALLY_CONSISTENT_UNATTESTED")
        self.assertEqual(result["capture_count"], 3)
        self.assertEqual(result["receipt_state_counts"]["PERSISTENCE_CLAIM_UNVERIFIED"], 3)
        for flag in ("source_authenticated", "shared_poll_durability_proven",
                     "persisted_verified", "decision_asof_proven",
                     "pit_research_eligible", "shadow_forward_eligible",
                     "performance_eligible", "real_submit_allowed",
                     "promotion_eligible", "statistical_edge_confirmed"):
            self.assertFalse(result[flag], flag)
        self.assertEqual(result["eligible_observed_n"], 0)

    def test_missing_stream_fail_closed(self):
        caps, recs = fixture()
        caps = caps[:-1]
        recs = recs[:-2]
        r = self.assess(caps, recs)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("REQUIRED_STREAM_NOT_CAPTURED", r["reason_counts"])

    def test_missing_receipt_is_unknown(self):
        caps, recs = fixture()
        r = self.assess(caps, recs[:-2])
        self.assertIn("RECEIPT_MISSING", r["reason_counts"])
        self.assertEqual(r["receipt_state_counts"]["UNKNOWN_NO_RECEIPT"], 1)

    def test_queue_is_not_durable(self):
        caps, _ = fixture()
        r = self.assess(caps, [receipt(row) for row in caps])
        self.assertEqual(r["receipt_state_counts"]["UNKNOWN_QUEUED_NOT_PERSISTED"], 3)
        self.assertFalse(r["persisted_verified"])
        self.assertIn("PERSISTENCE_UNCONFIRMED", r["reason_counts"])

    def test_prequeue_drop_recorded_not_success(self):
        caps, recs = fixture()
        recs = [r for r in recs if r["stream"] != STREAMS[0]]
        recs += [receipt(caps[0], "PRE_QUEUE_DROP")]
        r = self.assess(caps, recs)
        self.assertEqual(r["receipt_state_counts"]["DROPPED_PRE_QUEUE"], 1)
        self.assertEqual(r["status"], "BLOCKED")
        self.assertIn("CAPTURE_DROPPED_PRE_QUEUE", r["reason_counts"])

    def test_postqueue_reject_recorded_not_success(self):
        caps, recs = fixture()
        recs = [r for r in recs if not (r["stream"] == STREAMS[0] and r["phase"] == "PERSISTENCE_CLAIM")]
        recs += [receipt(caps[0], "POST_QUEUE_REJECT", CLAIMED)]
        r = self.assess(caps, recs)
        self.assertEqual(r["receipt_state_counts"]["REJECTED_AFTER_QUEUE"], 1)
        self.assertEqual(r["status"], "BLOCKED")

    def test_conflicting_drop_and_queue(self):
        caps, recs = fixture()
        recs += [receipt(caps[0], "PRE_QUEUE_DROP", CLAIMED)]
        self.assertIn("ILLEGAL_RECEIPT_TRANSITION", self.assess(caps, recs)["reason_counts"])

    def test_claim_without_queue_is_illegal(self):
        caps, recs = fixture()
        recs = [r for r in recs if not (r["stream"] == STREAMS[0] and r["phase"] == "QUEUED")]
        self.assertIn("CLAIM_OR_REJECTION_WITHOUT_QUEUE", self.assess(caps, recs)["reason_counts"])

    def test_claim_precedes_queue_fails(self):
        caps, recs = fixture()
        recs = [dict(r, at=QUEUED) if r["phase"] == "PERSISTENCE_CLAIM" and r["stream"] == STREAMS[0] else r for r in recs]
        recs = [dict(r, at=CLAIMED) if r["phase"] == "QUEUED" and r["stream"] == STREAMS[0] else r for r in recs]
        self.assertIn("CLAIM_BEFORE_QUEUE", self.assess(caps, recs)["reason_counts"])

    def test_receipt_earlier_than_capture_creation(self):
        caps, recs = fixture()
        recs[0] = dict(recs[0], at=START)
        self.assertIn("RECEIPT_PRECEDES_CREATION", self.assess(caps, recs)["reason_counts"])

    def test_digest_mismatch_refuses(self):
        caps, recs = fixture()
        recs[0] = dict(recs[0], record_sha256="d" * 64)
        self.assertIn("RECEIPT_IDENTITY_CONFLICT", self.assess(caps, recs)["reason_counts"])

    def test_receipt_without_capture(self):
        caps, recs = fixture()
        recs.append(dict(recs[0], poll_seq=91))
        self.assertIn("RECEIPT_WITHOUT_CAPTURE", self.assess(caps, recs)["reason_counts"])

    def test_duplicate_capture_idempotent(self):
        caps, recs = fixture()
        result = self.assess(caps + [deepcopy(caps[0])], recs + [deepcopy(recs[0])])
        self.assertEqual(result["capture_count"], 3)
        self.assertEqual(result["status"], "STRUCTURALLY_CONSISTENT_UNATTESTED")

    def test_duplicate_conflicting_capture_fails(self):
        caps, recs = fixture()
        caps.append(dict(caps[0], record_sha256="d" * 64))
        self.assertIn("CAPTURE_IDENTITY_CONFLICT", self.assess(caps, recs)["reason_counts"])

    def test_conflicting_duplicate_phase_time_fails(self):
        caps, recs = fixture()
        recs.append(dict(recs[0], at=CLAIMED))
        self.assertIn("RECEIPT_EVENT_CONFLICT", self.assess(caps, recs)["reason_counts"])

    def test_naive_timestamp_refused(self):
        caps, recs = fixture()
        caps[0]["available_at"] = "2026-10-14T09:00:02"
        self.assertIn("TIMEZONE_OR_TIMESTAMP_INVALID", self.assess(caps, recs)["reason_counts"])

    def test_utc_offset_comparison_not_string_order(self):
        caps, recs = fixture()
        caps[0]["available_at"] = "2026-10-14T00:00:02Z"
        self.assertEqual(self.assess(caps, recs)["status"], "STRUCTURALLY_CONSISTENT_UNATTESTED")

    def test_future_available_at_rejected(self):
        caps, recs = fixture()
        caps[0]["available_at"] = "2026-10-14T09:00:09+09:00"
        self.assertIn("CAPTURE_TEMPORAL_ORDER_INVALID", self.assess(caps, recs)["reason_counts"])

    def test_bad_sha_rejected(self):
        caps, recs = fixture()
        caps[0]["producer_sha"] = "not-a-sha"
        self.assertIn("PRODUCER_SHA_INVALID", self.assess(caps, recs)["reason_counts"])

    def test_two_producers_one_session_conflict(self):
        caps, recs = fixture()
        caps[1]["producer_sha"] = "f" * 40
        self.assertIn("SESSION_PRODUCER_CONFLICT", self.assess(caps, recs)["reason_counts"])

    def test_reused_poll_missing_sequence_evidence(self):
        caps1, recs1 = fixture()
        caps2 = [dict(row, poll_seq=3) for row in caps1]
        recs2 = [dict(r, poll_seq=3) for r in recs1]
        self.assertIn("OBSERVED_POLL_SEQ_GAP", self.assess(caps1 + caps2, recs1 + recs2)["reason_counts"])

    def test_invalid_bool_seq_rejected(self):
        caps, recs = fixture()
        caps[0]["poll_seq"] = True
        self.assertIn("POLL_SEQ_INVALID", self.assess(caps, recs)["reason_counts"])

    def test_health_missing_or_stopped_fails(self):
        snapshot = health()
        snapshot["state"] = "STOPPED"
        self.assertIn("SOURCE_HEALTH_NOT_READY", self.assess(source_health=snapshot)["reason_counts"])

    def test_health_untrusted_without_last_data(self):
        snapshot = health()
        snapshot["last_data_at"] = None
        self.assertIn("SOURCE_HEALTH_NOT_READY", self.assess(source_health=snapshot)["reason_counts"])

    def test_health_last_data_in_future(self):
        snapshot = health()
        snapshot["last_data_at"] = "2026-10-14T09:00:20+09:00"
        self.assertIn("SOURCE_HEALTH_CLOCK_INVALID", self.assess(source_health=snapshot)["reason_counts"])

    def test_decision_with_existing_inputs_still_unattested(self):
        decision = dict(schema_version=c.DECISION_SCHEMA, session_id=SESSION,
                        poll_seq=1, symbol="PRIVATE_SYNTHETIC.T",
                        decision_at=DECISION_AT,
                        input_streams=list(STREAMS))
        result = self.assess(decisions=[decision])
        self.assertEqual(result["status"], "STRUCTURALLY_CONSISTENT_UNATTESTED")
        self.assertEqual(result["decision_count"], 1)
        self.assertFalse(result["decision_asof_proven"])

    def test_future_input_decision_rejected(self):
        caps, recs = fixture()
        decision = dict(schema_version=c.DECISION_SCHEMA, session_id=SESSION,
                        poll_seq=1, symbol="PRIVATE_SYNTHETIC.T",
                        decision_at="2026-10-14T09:00:01+09:00",
                        input_streams=["CONDITION"])
        self.assertIn("DECISION_REFERENCES_FUTURE_INPUT", self.assess(caps, recs, decisions=[decision])["reason_counts"])

    def test_decision_input_missing_fails(self):
        decision = dict(schema_version=c.DECISION_SCHEMA, session_id=SESSION,
                        poll_seq=2, symbol="PRIVATE_SYNTHETIC.T",
                        decision_at=DECISION_AT, input_streams=["CONDITION"])
        self.assertIn("DECISION_INPUT_MISSING", self.assess(decisions=[decision])["reason_counts"])

    def test_queued_signal_cannot_prove_decision_input(self):
        caps, recs = fixture()
        recs = [r for r in recs if not (r["phase"] == "PERSISTENCE_CLAIM" and r["stream"] == "CONDITION")]
        decision = dict(schema_version=c.DECISION_SCHEMA, session_id=SESSION,
                        poll_seq=1, symbol="PRIVATE_SYNTHETIC.T",
                        decision_at=DECISION_AT, input_streams=["CONDITION"])
        self.assertIn("DECISION_INPUT_NOT_PERSISTED", self.assess(caps, recs, decisions=[decision])["reason_counts"])

    def test_no_private_symbol_hash_or_times_in_aggregate(self):
        s = json.dumps(self.assess(), sort_keys=True)
        for forbidden in ("PRIVATE_SYNTHETIC.T", DIGEST, SESSION, "2026-10-14", SHA):
            self.assertNotIn(forbidden, s)

    def test_determinism_when_inputs_reordered(self):
        caps, recs = fixture()
        self.assertEqual(self.assess(caps, recs), self.assess(list(reversed(caps)), list(reversed(recs))))


if __name__ == "__main__":
    unittest.main()
