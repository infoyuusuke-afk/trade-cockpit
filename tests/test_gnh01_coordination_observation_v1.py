"""Synthetic regression for GNH01 public observation and limited ACK.

An observed GitHub comment is neither authenticated Grok evidence nor a
PRE-NEXT scheduled receipt. No network, live tasks, orders or key handling.
"""
from copy import deepcopy
from datetime import datetime, timezone
import unittest

from scripts.coordination_ledger_v1 import (
    InvalidMessage, parse_message, reconcile, OBSERVATION_ACK_SCOPE
)

NOW = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
PARENT = {
    "message_id": "GNH01-ROUTINE-EGRESS-ONCE-20261022-01",
    "event_type": "DELIVERY_TEST",
    "source_role": "global_news_hunter_01",
    "recipient_role": "development_lead",
    "project_item_id": "P0-GLOBAL-INTELLIGENCE-TO-SHADOW-INTEGRATION-20261022",
    "state": "ROUTINE_SCHEDULED_TEST",
    "real_submit_allowed": "false",
    "routine_run_id": "UNKNOWN",
    "scheduled_fire_jst": "2026-10-22 16:35 (slot 16:30)",
    "actual_start_jst": "2026-10-22 16:35:21",
    "marker": "GNH01-MARK-0de7fd7c",
    "note": "Synthetic delivery test only. Contains no market data, news content, credentials, or personal data.",
}
ACK = {
    "message_id": "DEV-GNH01-OBSERVED-ACK-20261022-01",
    "event_type": "ACK",
    "source_role": "development_lead",
    "recipient_role": "global_news_hunter_01",
    "project_item_id": PARENT["project_item_id"],
    "sent_at_jst": "2026-10-22T16:50:00+09:00",
    "evidence_url": "https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-6335466037",
    "owner_approval_boundary": "REVIEW_ONLY",
    "real_submit_allowed": "false",
    "in_reply_to": PARENT["message_id"],
    "ack_scope": OBSERVATION_ACK_SCOPE,
    "state": "GITHUB_COMMENT_READ_VERIFIED_ONLY",
}


def body(fields):
    return "[100B_COORD_V1]\n" + "\n".join(f"{k}: {v}" for k, v in fields.items()) + "\n"


class ObservedGnh01ProtocolTests(unittest.TestCase):
    def test_exact_prior_delivery_test_is_observable(self):
        self.assertEqual(parse_message(body(PARENT), now=NOW), PARENT)

    def test_bounded_ack_reconciles_without_e2e(self):
        observed = reconcile([
            {"body": body(PARENT), "url": "https://github.com/example/first"},
            {"body": body(ACK), "url": "https://github.com/example/second"},
        ], now=NOW)
        self.assertEqual(len(observed["valid_messages"]), 2)
        self.assertEqual(observed["invalid_messages"], [])
        self.assertTrue(all(x["observation_only"] == "true"
                            for x in observed["valid_messages"]))
        self.assertFalse(observed["sender_role_authenticated"])
        self.assertFalse(observed["end_to_end_verified"])
        self.assertFalse(observed["real_submit_allowed"])

    def test_duplicate_ack_rejected(self):
        other = dict(ACK, message_id="DEV-GNH01-OBSERVED-ACK-20261022-02")
        result = reconcile([{"body": body(PARENT)},
                            {"body": body(ACK)},
                            {"body": body(other)}], now=NOW)
        self.assertEqual(result["invalid_messages"][0]["error"],
                         "DUPLICATE_ACK_FOR_PARENT")

    def test_external_role_cannot_assign(self):
        bad = dict(ACK, event_type="ASSIGN", ack_scope=OBSERVATION_ACK_SCOPE)
        with self.assertRaises(InvalidMessage):
            parse_message(body(bad), now=NOW)

    def test_ack_cannot_claim_task_receipt_or_secret_key(self):
        bad = dict(ACK, ack_scope="PRE_NEXT_AUTOMATED_RECEIPT")
        with self.assertRaises(InvalidMessage):
            parse_message(body(bad), now=NOW)
        bad = dict(ACK, state="ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
        with self.assertRaises(InvalidMessage):
            parse_message(body(bad), now=NOW)

    def test_missing_parent_rejected(self):
        result = reconcile([{"body": body(ACK)}], now=NOW)
        self.assertEqual(result["invalid_messages"][0]["error"],
                         "MISSING_OR_UNVERIFIED_PARENT")

    def test_no_forged_source_timestamp_or_evidence(self):
        for field in ("evidence_url", "sent_at_jst", "owner_approval_boundary"):
            bad = dict(PARENT, **{field: "fake"})
            with self.subTest(field=field):
                with self.assertRaisesRegex(InvalidMessage, "DELIVERY_TEST_FIELDS_INVALID"):
                    parse_message(body(bad), now=NOW)

    def test_future_or_malformed_synthetic_clock_rejected(self):
        for timestamp in ("2026-10-23 16:35:21", "bad", "2026-10-22 16:10:00"):
            bad = dict(PARENT, actual_start_jst=timestamp)
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(InvalidMessage):
                    parse_message(body(bad), now=NOW)

    def test_wrong_source_or_marker_rejected(self):
        for change in ({"source_role": "progress_coordinator"},
                       {"marker": "GNH01-MARK-xyz"}):
            with self.assertRaises(InvalidMessage):
                parse_message(body(dict(PARENT, **change)), now=NOW)

    def test_ack_with_wrong_project_cannot_reconcile(self):
        bad = dict(ACK, project_item_id="OTHER")
        report = reconcile([{"body": body(PARENT)}, {"body": body(bad)}], now=NOW)
        self.assertEqual(report["invalid_messages"][0]["error"],
                         "WRONG_DIRECTION_OR_PROJECT")


if __name__ == "__main__":
    unittest.main()
