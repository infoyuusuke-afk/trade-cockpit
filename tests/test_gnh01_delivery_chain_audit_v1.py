"""Synthetic zero-network local chain acceptance; NOT actual Bot/PRE/Brain."""
from __future__ import annotations

import copy
from datetime import timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.gnh01_durable_archive_v1 import archive_event, ArchiveBlocked
from scripts.gnh01_intelligence_contract_v1 import canonical_bytes, content_digest
from scripts.gnh01_private_review_handoff_v1 import (
    SENDER_KEY, READER_KEY, HandoffBlocked, export_review, receive_review,
)
from scripts.gnh01_delivery_chain_audit_v1 import audit_local_chain
from test_gnh01_intelligence_contract_v1 import fixture, NOW

S_KEY = "c2" * 32
R_KEY = "d3" * 32


class LocalChainAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gnh01_chain_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "private_archive.db"
        self.event = fixture()
        keys = patch.dict(os.environ, {SENDER_KEY:S_KEY, READER_KEY:R_KEY})
        keys.start()
        self.addCleanup(keys.stop)

    def persist(self, event=None):
        return archive_event(self.db, event or self.event, clock=lambda: NOW)

    def send(self, event=None):
        return export_review(self.db, event or self.event, private_dir=self.root, now=NOW)

    def ack(self, path):
        return receive_review(path, private_dir=self.root, now=NOW)

    def audit(self, event=None, *, now=NOW):
        return audit_local_chain(self.db, event or self.event, private_dir=self.root, now=now)

    def complete(self):
        self.persist()
        path = self.send()
        self.ack(path)
        return path

    def test_complete_chain_reports_only_local_evidence(self):
        self.complete()
        a = self.audit()
        self.assertEqual(a["state"], "LOCAL_CHAIN_MATCH_RESEARCH_ONLY")
        self.assertEqual(a["content_hash"], self.event["content_hash"])
        for key in ("local_archive_readback_verified", "local_signed_review_verified",
                    "local_signed_reader_ack_verified"):
            self.assertIs(a[key], True)
        for key in ("sender_role_authenticated", "grok_unattended_routine_verified",
                    "grok_direct_emission_verified", "pre_next_scheduled_task_delivery_verified",
                    "pre_next_scheduled_task_ack_verified", "source_authenticity_verified",
                    "brain_receiver_ack_verified", "shadow_eligible", "real_submit_allowed"):
            self.assertIs(a[key], False)

    def test_owner_relay_chain_is_still_not_grok_delivery(self):
        self.event["source_role"] = "owner_instruction_relay"
        self.event["content_hash"] = content_digest(self.event)
        self.complete()
        out = self.audit()
        self.assertFalse(out["grok_direct_emission_verified"])
        self.assertFalse(out["sender_role_authenticated"])

    def test_missing_archive_blocks_audit(self):
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_NOT_FOUND"):
            self.audit()

    def test_missing_handoff_blocks_audit(self):
        self.persist()
        with self.assertRaisesRegex(HandoffBlocked, "ENVELOPE_NOT_DURABLE"):
            self.audit()

    def test_missing_ack_blocks_audit(self):
        self.persist()
        self.send()
        with self.assertRaisesRegex(HandoffBlocked, "ACK_NOT_DURABLE"):
            self.audit()

    def test_mismatched_private_event_blocks(self):
        self.complete()
        altered = copy.deepcopy(self.event)
        altered["event_summary"] = "completely different original assertion"
        altered["content_hash"] = content_digest(altered)
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_CONTENT_OR_STATUS_MISMATCH"):
            self.audit(altered)

    def test_changed_signed_handoff_body_blocks(self):
        path = self.complete()
        record = json.loads(path.read_text("utf-8"))
        record["payload"]["review"]["event_summary_claim"] = "tampered"
        path.write_bytes(canonical_bytes(record) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ENVELOPE_ARCHIVE_CONTENT_MISMATCH"):
            self.audit()

    def test_sender_wrong_key_blocks(self):
        self.complete()
        with patch.dict(os.environ, {SENDER_KEY: "e1"*32}):
            with self.assertRaisesRegex(HandoffBlocked, "ENVELOPE_SIGNATURE_INVALID"):
                self.audit()

    def test_reader_wrong_key_blocks(self):
        self.complete()
        with patch.dict(os.environ, {READER_KEY: "e2"*32}):
            with self.assertRaisesRegex(HandoffBlocked, "ACK_NOT_DURABLE_OR_INVALID"):
                self.audit()

    def test_signed_but_foreign_ack_fails_identity(self):
        one = self.complete()
        second = copy.deepcopy(self.event)
        second["event_id"] = "SYN_GNH01_OTHER_002"
        second["content_hash"] = content_digest(second)
        self.persist(second)
        other = self.send(second)
        other_ack = self.ack(other)
        one_ack = one.with_name(one.stem + ".ack.json")
        one_ack.write_bytes(Path(other_ack["ack_path"]).read_bytes())
        with self.assertRaisesRegex(HandoffBlocked, "ACK_ENVELOPE_IDENTITY_MISMATCH"):
            self.audit()

    def test_re_signed_wrong_envelope_digest_denied(self):
        first = self.complete()
        ack_path = first.with_name(first.stem + ".ack.json")
        obj = json.loads(ack_path.read_text("utf-8"))
        obj["payload"]["envelope_sha256"] = "0" * 64
        obj["hmac_sha256"] = hmac.new(
            bytes.fromhex(R_KEY),
            b"100B:GNH01:LOCAL-ACK:V1\n" + canonical_bytes(obj["payload"]),
            hashlib.sha256,
        ).hexdigest()
        ack_path.write_bytes(canonical_bytes(obj) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ACK_ENVELOPE_IDENTITY_MISMATCH"):
            self.audit()

    def test_stale_envelope_fails_independent_audit(self):
        self.complete()
        with self.assertRaisesRegex(HandoffBlocked, "ENVELOPE_STALE_OR_FUTURE"):
            self.audit(now=NOW + timedelta(minutes=16))

    def test_ack_precedes_envelope_fails_even_when_signed(self):
        path = self.complete()
        ack_path = path.with_name(path.stem + ".ack.json")
        obj = json.loads(ack_path.read_text("utf-8"))
        obj["payload"]["received_at"] = (NOW-timedelta(seconds=2)).isoformat()
        obj["hmac_sha256"] = hmac.new(
            bytes.fromhex(R_KEY),
            b"100B:GNH01:LOCAL-ACK:V1\n" + canonical_bytes(obj["payload"]),
            hashlib.sha256,
        ).hexdigest()
        ack_path.write_bytes(canonical_bytes(obj) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ACK_STALE_OR_FUTURE"):
            self.audit()

    def test_ack_future_fails_even_when_signed(self):
        path = self.complete()
        ack_path = path.with_name(path.stem + ".ack.json")
        obj = json.loads(ack_path.read_text("utf-8"))
        obj["payload"]["received_at"] = (NOW+timedelta(seconds=2)).isoformat()
        obj["hmac_sha256"] = hmac.new(
            bytes.fromhex(R_KEY),
            b"100B:GNH01:LOCAL-ACK:V1\n" + canonical_bytes(obj["payload"]),
            hashlib.sha256,
        ).hexdigest()
        ack_path.write_bytes(canonical_bytes(obj) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ACK_STALE_OR_FUTURE"):
            self.audit()

    def test_ack_wrong_role_promotion_fails_even_when_signed(self):
        path = self.complete()
        ack_path = path.with_name(path.stem + ".ack.json")
        obj = json.loads(ack_path.read_text("utf-8"))
        obj["payload"]["pre_next_scheduled_task_ack"] = True
        obj["hmac_sha256"] = hmac.new(
            bytes.fromhex(R_KEY),
            b"100B:GNH01:LOCAL-ACK:V1\n" + canonical_bytes(obj["payload"]),
            hashlib.sha256,
        ).hexdigest()
        ack_path.write_bytes(canonical_bytes(obj) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ACK_NOT_DURABLE_OR_INVALID"):
            self.audit()

    def test_ack_extra_field_does_not_pass(self):
        path = self.complete()
        ack_path = path.with_name(path.stem + ".ack.json")
        obj = json.loads(ack_path.read_text("utf-8"))
        obj["payload"]["sneaky_claim"] = "PRE_NEXT_DONE"
        obj["hmac_sha256"] = hmac.new(
            bytes.fromhex(R_KEY),
            b"100B:GNH01:LOCAL-ACK:V1\n" + canonical_bytes(obj["payload"]),
            hashlib.sha256,
        ).hexdigest()
        ack_path.write_bytes(canonical_bytes(obj) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ACK_FIELDS_INVALID"):
            self.audit()

    def test_archive_metadata_tamper_fails_before_network(self):
        self.complete()
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE grok_archive_v1 SET received_at=?", ("2025-01-01T00:00:00+00:00",))
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            self.audit()


if __name__ == "__main__":
    unittest.main()
