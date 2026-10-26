"""Synthetic read-only GNH01 -> PRE-NEXT review preparation, no transmission."""
import copy
from contextlib import closing
from datetime import timedelta, datetime
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.gnh01_intelligence_contract_v1 import content_digest
from scripts.gnh01_durable_archive_v1 import ArchiveBlocked, archive_event
from scripts.gnh01_pre_next_review_v1 import (
    SCHEMA_VERSION, build_pre_next_review_request,
)
from test_gnh01_intelligence_contract_v1 import fixture, NOW


class PreNextReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="gnh01_pre_next_")
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "private_archive.db"
        self.event = fixture()
        self.local = lambda: NOW

    def archived(self, *, event=None):
        data = event or self.event
        return archive_event(self.db, data, clock=self.local)

    def review(self, *, event=None, now=None):
        return build_pre_next_review_request(
            self.db, event or self.event, now=now or NOW,
        )

    def test_never_claims_pre_next_brain_shadow_delivery(self):
        self.archived()
        out = self.review()
        self.assertEqual(out["schema_version"], SCHEMA_VERSION)
        self.assertEqual(out["state"], "SOURCE_REVIEW_REQUIRED")
        self.assertEqual(out["intended_recipient_role"], "pre_next")
        self.assertEqual(out["event_id"], self.event["event_id"])
        self.assertEqual(out["local_archived_at"], NOW.isoformat())
        self.assertFalse(out["source_authenticity_verified"])
        self.assertFalse(out["ticker_identity_verified"])
        self.assertFalse(out["publication_available_at_verified"])
        self.assertFalse(out["brain_trade_decision_eligible"])
        self.assertFalse(out["pre_next_delivery_verified"])
        self.assertFalse(out["pre_next_ack_verified"])
        self.assertFalse(out["shadow_eligible"])
        self.assertIs(out["real_submit_allowed"], False)
        self.assertNotIn("available_at", out)
        self.assertNotIn("sources", out)

    def test_claimed_direct_grok_sender_never_becomes_authenticated(self):
        self.archived()
        out = self.review()
        self.assertEqual(out["source_role"], "grok_bot_gnh01")
        self.assertFalse(out["sender_role_authenticated"])
        self.assertFalse(out["grok_direct_emission_verified"])
        self.assertFalse(out["origin_transport_verified"])

    def test_owner_relay_remains_relay_not_direct_grok(self):
        # OWNER relay must not be turned into a forged direct-Bot provenance.
        self.event["source_role"] = "owner_instruction_relay"
        self.event["content_hash"] = content_digest(self.event)
        self.archived()
        out = self.review()
        self.assertEqual(out["source_role"], "owner_instruction_relay")
        self.assertFalse(out["sender_role_authenticated"])
        self.assertFalse(out["grok_direct_emission_verified"])
        self.assertFalse(out["origin_transport_verified"])
        self.assertFalse(out["pre_next_ack_verified"])
        self.assertFalse(out["brain_trade_decision_eligible"])

    def test_changing_archived_relay_to_direct_grok_rejected(self):
        self.event["source_role"] = "owner_instruction_relay"
        self.event["content_hash"] = content_digest(self.event)
        self.archived()
        forged = copy.deepcopy(self.event)
        forged["source_role"] = "grok_bot_gnh01"
        forged["content_hash"] = content_digest(forged)
        with self.assertRaisesRegex(
                ArchiveBlocked, "ARCHIVE_CONTENT_OR_STATUS_MISMATCH"):
            self.review(event=forged)

    def test_primary_verified_sender_claim_never_becomes_verified_source(self):
        self.event["evidence_status"] = "PRIMARY_VERIFIED"
        self.event["content_hash"] = content_digest(self.event)
        self.archived()
        out = self.review()
        self.assertEqual(out["original_evidence_status_claim"], "PRIMARY_VERIFIED")
        self.assertFalse(out["source_authenticity_verified"])

    def test_no_archive_rejected(self):
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_NOT_FOUND"):
            self.review()

    def test_stale_local_receipt_blocked(self):
        self.archived()
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_STALE_OR_FUTURE"):
            self.review(now=NOW + timedelta(hours=3))

    def test_future_local_receipt_blocked(self):
        self.archived()
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_STALE_OR_FUTURE"):
            self.review(now=NOW - timedelta(seconds=1))

    def test_naive_local_clock_rejected(self):
        self.archived()
        with self.assertRaisesRegex(ArchiveBlocked, "LOCAL_CLOCK_UNVERIFIED"):
            self.review(now=datetime(2026, 10, 22))

    def test_event_tampering_blocked(self):
        self.archived()
        modified = copy.deepcopy(self.event)
        modified["event_summary"] = "Changed by an untrusted party"
        with self.assertRaisesRegex(ArchiveBlocked, "CONTENT_HASH_MISMATCH"):
            self.review(event=modified)

    def test_rehashed_event_not_matching_private_archive_blocked(self):
        self.archived()
        modified = copy.deepcopy(self.event)
        modified["event_summary"] = "A different valid revision body"
        modified["content_hash"] = content_digest(modified)
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_CONTENT_OR_STATUS_MISMATCH"):
            self.review(event=modified)

    def test_changed_transport_claim_does_not_backdate_local_archive(self):
        self.archived()
        modified = copy.deepcopy(self.event)
        modified["bridge_received_at"] = "2026-10-21T23:08:00Z"
        self.assertEqual(modified["content_hash"], self.event["content_hash"])
        out = self.review(event=modified)
        self.assertEqual(out["local_archived_at"], NOW.isoformat())

    def test_revision_requires_matching_durable_archive(self):
        self.archived()
        modified = copy.deepcopy(self.event)
        modified["event_revision"] = 2
        modified["content_hash"] = content_digest(modified)
        with self.assertRaisesRegex(ArchiveBlocked, "RECEIPT_NOT_DURABLE"):
            self.review(event=modified)

    def test_invalidated_claim_stays_review_only(self):
        self.event["evidence_status"] = "INVALIDATED"
        self.event["content_hash"] = content_digest(self.event)
        self.archived()
        out = self.review()
        self.assertEqual(out["original_evidence_status_claim"], "INVALIDATED")
        self.assertFalse(out["brain_trade_decision_eligible"])

    def test_corrupt_archive_blocks_review(self):
        self.archived()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE grok_archive_v1 SET payload_json=?", ("{}",))
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            self.review()


if __name__ == "__main__":
    unittest.main()
