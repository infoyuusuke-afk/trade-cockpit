"""Negative acceptance cases for read-only 100B coordination ledger v1."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import unittest

from scripts.coordination_ledger_v1 import (
    InvalidMessage, parse_message, reconcile,
)

NOW = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)
BASE = {
    "message_id": "COORD-20261015-DEV-001",
    "event_type": "ASSIGN",
    "source_role": "progress_coordinator",
    "recipient_role": "development_lead",
    "project_item_id": "P0-WINDOWS-WRITER",
    "sent_at_jst": "2026-10-15T15:32:00+09:00",
    "evidence_url": "https://github.com/infoyuusuke-afk/trade-cockpit/issues/382",
    "owner_approval_boundary": "REVIEW_ONLY",
    "real_submit_allowed": "false",
}
PREFIX = "[100B_COORD_V1]"


def body(values: dict[str, str]) -> str:
    return PREFIX + "\n" + "\n".join(f"{k}: {v}" for k, v in values.items()) + "\n"


def reply(event: str = "ACK") -> dict[str, str]:
    out = deepcopy(BASE)
    out.update({
        "message_id": "DEV-20261015-ACK-001",
        "event_type": event,
        "source_role": "development_lead",
        "recipient_role": "progress_coordinator",
        "in_reply_to": BASE["message_id"],
    })
    return out


class CoordinationLedgerV1Tests(unittest.TestCase):
    def test_legacy_ignored(self):
        self.assertIsNone(parse_message("ordinary #282 comment", now=NOW))

    def test_valid_assignment(self):
        self.assertEqual(parse_message(body(BASE), now=NOW)["event_type"], "ASSIGN")

    def test_valid_ack_causal_chain(self):
        report = reconcile([
            {"body": body(BASE), "url": "https://github.com/test#1"},
            {"body": body(reply()), "url": "https://github.com/test#2"},
        ], now=NOW)
        self.assertEqual(len(report["valid_messages"]), 2)
        self.assertEqual(report["invalid_messages"], [])
        self.assertFalse(report["sender_role_authenticated"])
        self.assertFalse(report["end_to_end_verified"])
        self.assertFalse(report["real_submit_allowed"])

    def test_orphan_ack_blocked(self):
        report = reconcile([{"body": body(reply())}], now=NOW)
        self.assertEqual(report["invalid_messages"][0]["error"],
                         "MISSING_OR_UNVERIFIED_PARENT")

    def test_duplicate_id_blocked(self):
        report = reconcile([{"body": body(BASE)}, {"body": body(BASE)}], now=NOW)
        self.assertEqual(report["invalid_messages"][0]["error"],
                         "DUPLICATE_MESSAGE_ID")

    def test_wrong_direction_blocked(self):
        other = reply()
        other["recipient_role"] = "spec_audit"
        report = reconcile([{"body": body(BASE)}, {"body": body(other)}], now=NOW)
        self.assertEqual(report["invalid_messages"][0]["error"],
                         "WRONG_DIRECTION_OR_PROJECT")

    def test_wrong_project_blocked(self):
        other = reply()
        other["project_item_id"] = "OTHER"
        report = reconcile([{"body": body(BASE)}, {"body": body(other)}], now=NOW)
        self.assertEqual(report["invalid_messages"][0]["error"],
                         "WRONG_DIRECTION_OR_PROJECT")

    def test_duplicate_field_blocked(self):
        with self.assertRaisesRegex(InvalidMessage, "UNKNOWN_DUPLICATE"):
            parse_message(body(BASE) + "message_id: OTHER\n", now=NOW)

    def test_missing_field_blocked(self):
        bad = dict(BASE)
        del bad["evidence_url"]
        with self.assertRaisesRegex(InvalidMessage, "MISSING_REQUIRED_FIELD"):
            parse_message(body(bad), now=NOW)

    def test_fake_live_trade_flag_blocked(self):
        bad = dict(BASE, real_submit_allowed="true")
        with self.assertRaises(InvalidMessage):
            parse_message(body(bad), now=NOW)

    def test_future_timestamp_blocked(self):
        bad = dict(BASE, sent_at_jst="2026-10-15T18:32:00+09:00")
        with self.assertRaisesRegex(InvalidMessage, "FUTURE_TIMESTAMP"):
            parse_message(body(bad), now=NOW)

    def test_non_jst_timezone_blocked(self):
        bad = dict(BASE, sent_at_jst="2026-10-15T06:32:00+00:00")
        with self.assertRaisesRegex(InvalidMessage, "TIMESTAMP_NOT_JST_OFFSET"):
            parse_message(body(bad), now=NOW)

    def test_public_repo_only(self):
        bad = dict(BASE, evidence_url="https://example.com/private")
        with self.assertRaisesRegex(InvalidMessage, "PUBLIC_REPO_EVIDENCE_REQUIRED"):
            parse_message(body(bad), now=NOW)

    def test_secret_blocked(self):
        bad = dict(BASE, next_action="Use ghp_AAAABBBBCCCCDDDDEEEE in CI")
        with self.assertRaisesRegex(InvalidMessage, "UNSAFE_OR_OVERSIZE_BODY"):
            parse_message(body(bad), now=NOW)

    def test_pc_path_blocked(self):
        bad = dict(BASE, next_action=r"Read C:\private\file")
        with self.assertRaisesRegex(InvalidMessage, "UNSAFE_OR_OVERSIZE_BODY"):
            parse_message(body(bad), now=NOW)

    def test_unknown_role_blocked(self):
        bad = dict(BASE, source_role="autonomous_broker")
        with self.assertRaisesRegex(InvalidMessage, "UNKNOWN_ROLE"):
            parse_message(body(bad), now=NOW)

    def test_only_coordinator_assigns(self):
        bad = dict(BASE, source_role="revenue_hunter")
        with self.assertRaisesRegex(InvalidMessage, "ASSIGN_REQUIRES_COORDINATOR"):
            parse_message(body(bad), now=NOW)

    def test_invalid_sha_blocked(self):
        bad = dict(BASE, main_sha="deadbeef")
        with self.assertRaisesRegex(InvalidMessage, "INVALID_SHA"):
            parse_message(body(bad), now=NOW)

    def test_bad_parent_event(self):
        source = reply()
        source["message_id"] = "DEV-RESULT-001"
        source["event_type"] = "RESULT"
        source["in_reply_to"] = BASE["message_id"]
        back = deepcopy(BASE)
        back.update({
            "message_id": "COORD-ACK-INVALID",
            "event_type": "ACK",
            "in_reply_to": source["message_id"],
        })
        result = reconcile([{"body": body(BASE)}, {"body": body(source)},
                            {"body": body(back)}], now=NOW)
        self.assertEqual(result["invalid_messages"][0]["error"], "INVALID_ACK_PARENT")

    def test_schema_validation_does_not_authenticate_agents(self):
        result = reconcile([{"body": body(BASE)}], now=NOW)
        self.assertEqual(result["status"], "SCHEMA_CHECK_ONLY")
        self.assertFalse(result["end_to_end_verified"])

    def test_legacy_ack_does_not_upgrade_e2e(self):
        result = reconcile([{
            "body": "message_id: SDCOORD-20261015-V2-PILOT-01"
        }, {
            "body": "in_reply_to: SDCOORD-20261015-V2-PILOT-01"
        }], now=NOW)
        self.assertFalse(result["end_to_end_verified"])
        self.assertEqual(result["valid_messages"], [])


if __name__ == "__main__":
    unittest.main()
