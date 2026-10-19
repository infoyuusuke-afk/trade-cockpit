"""Negative and compatibility cases for the read-only Issue #282 reader."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest

from scripts.coordination_compat_reader import classify, reconcile

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
GPT = {"slug": "chatgpt-codex-connector"}
CLAUDE = {"slug": "claude"}
_next_id = [1000]


def comment(fields, *, app=GPT, at="2026-10-19T08:00:00Z", tag="[100B_COORD_V1]",
            preamble="", edited=None, cid=None, trailer="\n\nfree text after the header"):
    _next_id[0] += 1
    cid = cid or _next_id[0]
    lines = ([preamble, ""] if preamble else []) + [tag]
    lines += [f"{k}: {v}" for k, v in fields.items()]
    return {
        "id": cid, "body": "\n".join(lines) + trailer,
        "html_url": f"https://github.com/infoyuusuke-afk/trade-cockpit/issues/282#issuecomment-{cid}",
        "created_at": at, "updated_at": edited or at,
        "performed_via_github_app": app,
    }


def msg(mid, event, src, dst, *, item="P0-ITEM", reply=None, **extra):
    fields = {"message_id": mid, "event_type": event, "source_role": src,
              "recipient_role": dst, "project_item_id": item}
    if reply:
        fields["in_reply_to"] = reply
    fields["real_submit_allowed"] = "false"
    fields.update(extra)
    return fields


def strict(mid, event, src, dst, *, reply=None):
    return msg(mid, event, src, dst, reply=reply,
               sent_at_jst="2026-10-19T16:00:00+09:00",
               evidence_url="https://github.com/infoyuusuke-afk/trade-cockpit/issues/282",
               owner_approval_boundary="REVIEW_ONLY")


ASSIGN = msg("COORD-A-1", "ASSIGN", "progress_coordinator", "revenue_hunter")
ACK = msg("REV-ACK-1", "ACK", "revenue_hunter", "progress_coordinator", reply="COORD-A-1")


def run(*comments, **kw):
    return reconcile(list(comments), now=NOW, **kw)


def rec(result, mid):
    return next(r for r in result["messages"] if r["message_id"] == mid)


class Formats(unittest.TestCase):
    def test_legacy_untagged_is_counted_not_parsed(self):
        r = classify({"id": 1, "body": "plain note", "created_at": "2026-10-19T08:00:00Z"}, now=NOW)
        self.assertEqual(r["protocol"], "LEGACY_UNTAGGED")
        self.assertIsNone(r["message_id"])

    def test_strict_385_body_is_recognised_as_strict(self):
        r = classify(comment(strict("COORD-S-1", "ASSIGN", "progress_coordinator",
                                    "development_lead"), trailer="\n"), now=NOW)
        self.assertEqual(r["protocol"], "COORD_V1_STRICT")

    def test_observed_dialect_is_read_with_the_385_rejection_kept(self):
        r = classify(comment(msg("DEV-1", "IMPLEMENTATION_RESULT", "development_lead",
                                 "progress_coordinator,supply_sq", head="x")), now=NOW)
        self.assertEqual(r["protocol"], "COORD_V1_OBSERVED")
        self.assertEqual(r["strict_rejection"], "UNKNOWN_DUPLICATE_OR_MALFORMED_FIELD")
        self.assertEqual(r["event_class"], "RESULT")
        self.assertEqual(r["recipient_roles"], ["progress_coordinator", "supply_demand_analyst"])

    def test_preamble_before_tag_is_read_and_flagged(self):
        r = classify(comment(ASSIGN, preamble="[OWNER ROSTER CORRECTION] note"), now=NOW)
        self.assertEqual(r["message_id"], "COORD-A-1")
        self.assertIn("PREAMBLE_BEFORE_TAG", r["warnings"])

    def test_447_delivery_envelope_is_read_but_has_no_roles(self):
        fields = {"message_id": "REPORT282-447-" + "a" * 40 + "-1", "event_type": "REPORT",
                  "sender_role_authenticated": "false", "state": "DELIVERY_PROBE",
                  "real_submit_allowed": "false"}
        r = classify(comment(fields, tag="[100B_REPORT_DELIVERY_V1]"), now=NOW)
        self.assertEqual(r["protocol"], "REPORT_DELIVERY_V1")
        self.assertIsNone(r["source_role"])
        self.assertIn("NO_ROLE_FIELDS_IN_DELIVERY_ENVELOPE", r["warnings"])

    def test_tag_with_no_message_id_cannot_be_correlated(self):
        r = classify(comment({}, tag="[100B_COORD_V1] free text review"), now=NOW)
        self.assertIn("MESSAGE_ID_MISSING", r["blocking"])

    def test_retired_role_flagged(self):
        r = classify(comment(msg("C-1", "ASSIGN", "progress_coordinator", "spec_audit")), now=NOW)
        self.assertIn("RETIRED_ROLE", r["warnings"])


class Safety(unittest.TestCase):
    def test_real_submit_true_blocks(self):
        r = classify(comment(msg("C-1", "REPORT", "development_lead", "progress_coordinator",
                                 real_submit_allowed="true")), now=NOW)
        self.assertIn("REAL_SUBMIT_TRUE", r["blocking"])

    def test_local_path_or_token_blocks(self):
        for leak in ("D:\\data\\x", "ghp_" + "A" * 20):
            r = classify(comment(msg("C-1", "REPORT", "development_lead",
                                     "progress_coordinator", note=leak)), now=NOW)
            self.assertIn("UNSAFE_CONTENT", r["blocking"])

    def test_result_never_authenticates_retries_or_claims_e2e(self):
        result = run(comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z"))
        self.assertFalse(result["sender_role_authenticated"])
        self.assertFalse(result["end_to_end_verified"])
        self.assertFalse(result["retry_allowed"])
        self.assertFalse(result["real_submit_allowed"])
        for row in result["role_matrix"].values():
            self.assertEqual(row["role_authentication"], "UNVERIFIED")
            self.assertEqual(row["scheduled_e2e"], "UNKNOWN")

    def test_safety_denial_report_is_marked_without_any_retry(self):
        result = run(comment(msg("REV-H-1", "REPORT", "revenue_hunter", "progress_coordinator",
                                 state="HANDOFF_PENDING", blocker="PLATFORM_SAFETY_DENIED")))
        self.assertTrue(rec(result, "REV-H-1")["denial_or_handoff_reported"])
        self.assertFalse(result["retry_allowed"])


class Correlation(unittest.TestCase):
    def test_normal_report_ack(self):
        result = run(comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z"))
        self.assertEqual(rec(result, "REV-ACK-1")["correlation"], "CORRELATED")
        self.assertEqual(result["role_matrix"]["revenue_hunter"]["correlated_acks"], 1)

    def test_ack_reread_needs_a_later_citation_by_original_sender(self):
        follow = msg("COORD-R-1", "REVIEW", "progress_coordinator", "revenue_hunter",
                     reply="REV-ACK-1")
        result = run(comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z"))
        self.assertFalse(rec(result, "REV-ACK-1")["ack_reread_observed"])
        result = run(comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z"),
                     comment(follow, at="2026-10-19T08:20:00Z"))
        self.assertTrue(rec(result, "REV-ACK-1")["ack_reread_observed"])

    def test_ack_with_different_project_item(self):
        bad = dict(ACK, project_item_id="OTHER-ITEM")
        result = run(comment(ASSIGN), comment(bad, at="2026-10-19T08:10:00Z"))
        self.assertIn("PROJECT_ITEM_MISMATCH", rec(result, "REV-ACK-1")["blocking"])

    def test_ack_to_missing_parent(self):
        result = run(comment(ACK))
        self.assertIn("ORPHAN_REPLY_PARENT_NOT_FOUND", rec(result, "REV-ACK-1")["blocking"])

    def test_ack_before_parent_is_orphan(self):
        result = run(comment(ACK, at="2026-10-19T07:00:00Z"), comment(ASSIGN))
        self.assertIn("ORPHAN_REPLY_PARENT_NOT_FOUND", rec(result, "REV-ACK-1")["blocking"])

    def test_ack_from_a_role_that_was_not_addressed(self):
        bad = dict(ACK, source_role="pre_next")
        result = run(comment(ASSIGN), comment(bad, at="2026-10-19T08:10:00Z"))
        self.assertIn("REPLIER_NOT_A_RECIPIENT", rec(result, "REV-ACK-1")["blocking"])

    def test_ack_addressed_to_the_wrong_role(self):
        bad = dict(ACK, recipient_role="development_lead")
        result = run(comment(ASSIGN), comment(bad, at="2026-10-19T08:10:00Z"))
        self.assertIn("REPLY_NOT_ADDRESSED_TO_PARENT_SENDER", rec(result, "REV-ACK-1")["blocking"])

    def test_role_spoofed_from_the_other_tool_family(self):
        result = run(comment(ASSIGN), comment(ACK, app=CLAUDE, at="2026-10-19T08:10:00Z"))
        self.assertIn("ROLE_CHANNEL_MISMATCH", rec(result, "REV-ACK-1")["blocking"])
        self.assertEqual(result["role_matrix"]["revenue_hunter"]["correlated_acks"], 0)

    def test_role_from_plain_token_is_unattested_not_verified(self):
        result = run(comment(ASSIGN), comment(ACK, app=None, at="2026-10-19T08:10:00Z"))
        self.assertIn("CHANNEL_UNATTESTED", rec(result, "REV-ACK-1")["warnings"])
        self.assertFalse(rec(result, "REV-ACK-1")["sender_role_verified"])

    def test_duplicate_message_id_same_body(self):
        first = comment(ASSIGN)
        again = dict(first, id=first["id"] + 1, created_at="2026-10-19T08:05:00Z")
        result = run(first, again)
        self.assertIn("DUPLICATE_MESSAGE_ID", result["messages"][1]["blocking"])

    def test_duplicate_message_id_other_body(self):
        result = run(comment(ASSIGN), comment(dict(ASSIGN, state="CHANGED"),
                                              at="2026-10-19T08:05:00Z"))
        self.assertIn("ID_CONTENT_CONFLICT", result["messages"][1]["blocking"])

    def test_duplicate_ack(self):
        second = dict(ACK, message_id="REV-ACK-2")
        result = run(comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z"),
                     comment(second, at="2026-10-19T08:20:00Z"))
        self.assertIn("DUPLICATE_ACK", rec(result, "REV-ACK-2")["blocking"])

    def test_ack_to_ack_is_invalid(self):
        bad = msg("COORD-ACK-2", "ACK", "progress_coordinator", "revenue_hunter",
                  reply="REV-ACK-1")
        result = run(comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z"),
                     comment(bad, at="2026-10-19T08:20:00Z"))
        self.assertIn("INVALID_ACK_PARENT", rec(result, "COORD-ACK-2")["blocking"])

    def test_self_continuation_is_a_reference_not_a_receipt(self):
        follow = msg("COORD-A-2", "REPORT", "progress_coordinator", "development_lead",
                     reply="COORD-A-1")
        result = run(comment(ASSIGN), comment(follow, at="2026-10-19T08:10:00Z"))
        self.assertEqual(rec(result, "COORD-A-2")["correlation"], "SELF_CONTINUATION")
        self.assertEqual(rec(result, "COORD-A-2")["blocking"], [])

    def test_ack_to_447_envelope_is_id_only(self):
        mid = "REPORT282-447-" + "a" * 40 + "-1"
        env = comment({"message_id": mid, "event_type": "REPORT"},
                      tag="[100B_REPORT_DELIVERY_V1]")
        ack = msg("COORD-ACK-447", "ACK", "progress_coordinator", "development_lead", reply=mid)
        result = run(env, comment(ack, at="2026-10-19T08:10:00Z"))
        self.assertEqual(rec(result, "COORD-ACK-447")["correlation"], "ID_ONLY_NO_ROLES")
        self.assertEqual(result["role_matrix"]["progress_coordinator"]["correlated_acks"], 0)

    def test_report_without_ack_stays_unanswered(self):
        result = run(comment(ASSIGN))
        row = result["role_matrix"]["revenue_hunter"]
        self.assertEqual(row["unanswered_addressed"], 1)
        self.assertEqual(row["write"], "NOT_OBSERVED")


class Time(unittest.TestCase):
    def test_declared_time_after_post_blocks(self):
        r = classify(comment(msg("C-1", "REPORT", "development_lead", "progress_coordinator",
                                 sent_at_jst="2026-10-19T20:00:00+09:00")), now=NOW)
        self.assertIn("DECLARED_TIME_AFTER_POST", r["blocking"])

    def test_future_server_time_blocks(self):
        r = classify(comment(ASSIGN, at="2026-10-19T10:00:00Z"), now=NOW)
        self.assertIn("FUTURE_SERVER_TIME", r["blocking"])

    def test_missing_and_invalid_declared_time(self):
        r = classify(comment(ASSIGN), now=NOW)
        self.assertIn("DECLARED_TIME_MISSING_SERVER_TIME_USED", r["warnings"])
        r = classify(comment(dict(ASSIGN, as_of="yesterday")), now=NOW)
        self.assertIn("DECLARED_TIME_INVALID", r["warnings"])

    def test_missing_server_time_blocks(self):
        c = comment(ASSIGN)
        c["created_at"] = None
        self.assertIn("SERVER_TIME_MISSING", classify(c, now=NOW)["blocking"])


class Integrity(unittest.TestCase):
    def test_edit_after_post_is_flagged(self):
        r = classify(comment(ASSIGN, edited="2026-10-19T08:30:00Z"), now=NOW)
        self.assertIn("EDITED_AFTER_POST", r["warnings"])

    def test_deleted_or_modified_since_baseline(self):
        a, b = comment(ASSIGN), comment(ACK, at="2026-10-19T08:10:00Z")
        changed = dict(b, body=b["body"] + "\nchanged")
        result = run(changed, baseline=[a, b])
        findings = {f["finding"] for f in result["tamper_findings"]}
        self.assertEqual(findings, {"DELETED_SINCE_BASELINE", "MODIFIED_SINCE_BASELINE"})

    def test_send_unknown_is_never_turned_into_failure_or_resend(self):
        result = run(comment(ASSIGN), expected_message_ids=["COORD-A-1", "LOST-1"])
        self.assertEqual(result["expected_delivery"], {
            "COORD-A-1": "OBSERVED_ON_ISSUE", "LOST-1": "SEND_UNKNOWN_NOT_OBSERVED"})
        self.assertFalse(result["retry_allowed"])


if __name__ == "__main__":
    unittest.main()
