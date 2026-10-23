"""Offline synthetic private local-review sender/reader; NEVER a ChatGPT Task ACK."""
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

from scripts.gnh01_intelligence_contract_v1 import canonical_bytes, content_digest
from scripts.gnh01_durable_archive_v1 import archive_event
from scripts.gnh01_private_review_handoff_v1 import (
    ACK_SCHEMA, ENVELOPE_SCHEMA, SENDER_KEY, READER_KEY,
    HandoffBlocked, export_review, receive_review, verify_local_ack,
)
from test_gnh01_intelligence_contract_v1 import fixture, NOW

S_KEY = "a7" * 32
R_KEY = "c8" * 32


class LocalPrivateReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="gnh01_local_review_")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "source_archive.db"
        self.event = fixture()
        key_patch = patch.dict(os.environ, {SENDER_KEY: S_KEY, READER_KEY: R_KEY})
        key_patch.start()
        self.addCleanup(key_patch.stop)

    def archive(self):
        return archive_event(self.db, self.event, clock=lambda: NOW)

    def send(self, *, now=NOW, folder=None):
        return export_review(self.db, self.event, private_dir=folder or self.root, now=now)

    def receive(self, path, *, now=NOW, folder=None):
        return receive_review(path, private_dir=folder or self.root, now=now)

    def test_private_round_trip_returns_local_ack_not_task_ack(self):
        self.archive()
        path = self.send()
        self.assertTrue(path.is_file())
        out = self.receive(path)
        self.assertTrue(out["signed_ack_independently_read_back"])
        self.assertEqual(out["state"], "LOCAL_REVIEW_READER_ACK_ONLY")
        self.assertEqual(out["ack_kind"], "LOCAL_READER_ONLY_NOT_CHATGPT_PRE_NEXT")
        self.assertEqual(out["event_id"], self.event["event_id"])
        self.assertIs(out["pre_next_scheduled_task_ack"], False)
        self.assertIs(out["source_authenticity_verified"], False)
        self.assertIs(out["brain_received"], False)
        self.assertIs(out["shadow_eligible"], False)
        self.assertIs(out["real_submit_allowed"], False)
        verified = verify_local_ack(out["ack_path"], private_dir=self.root)
        self.assertEqual(verified["event_content_sha256"], self.event["content_hash"])
        self.assertFalse(verified["pre_next_scheduled_task_ack"])

    def test_owner_relay_stays_relay_inside_signed_review(self):
        self.event["source_role"] = "owner_instruction_relay"
        self.event["content_hash"] = content_digest(self.event)
        self.archive()
        f = self.send()
        package = json.loads(f.read_text("utf-8"))
        record = package["payload"]["review"]
        self.assertEqual(record["source_role"], "owner_instruction_relay")
        self.assertIs(record["grok_direct_emission_verified"], False)
        self.assertIs(record["sender_role_authenticated"], False)
        self.assertIs(record["origin_transport_verified"], False)
        ack = self.receive(f)
        self.assertFalse(ack["brain_received"])

    def test_sender_marked_primary_is_not_elevated(self):
        self.event["evidence_status"] = "PRIMARY_VERIFIED"
        self.event["content_hash"] = content_digest(self.event)
        self.archive()
        package = json.loads(self.send().read_text("utf-8"))
        item = package["payload"]["review"]
        self.assertEqual(item["original_evidence_status_claim"], "PRIMARY_VERIFIED")
        self.assertFalse(item["source_authenticity_verified"])
        self.assertFalse(item["publication_available_at_verified"])

    def test_no_existing_archive_never_exports(self):
        with self.assertRaisesRegex(ValueError, "ARCHIVE_NOT_FOUND"):
            self.send()
        self.assertEqual(list(self.root.glob("gnh01_review_*.json")), [])

    def test_sender_key_required(self):
        self.archive()
        with patch.dict(os.environ, {SENDER_KEY: ""}):
            with self.assertRaisesRegex(HandoffBlocked, "PRIVATE_HMAC_KEY_MISSING_OR_INVALID"):
                self.send()
        self.assertEqual(list(self.root.glob("gnh01_review_*.json")), [])

    def test_reader_key_required_and_no_ack_written(self):
        self.archive()
        f = self.send()
        with patch.dict(os.environ, {READER_KEY: ""}):
            with self.assertRaisesRegex(HandoffBlocked, "PRIVATE_HMAC_KEY_MISSING_OR_INVALID"):
                self.receive(f)
        self.assertFalse(f.with_name(f.stem + ".ack.json").exists())

    def test_reader_sender_keys_must_differ(self):
        self.archive()
        f = self.send()
        with patch.dict(os.environ, {READER_KEY: S_KEY}):
            with self.assertRaisesRegex(HandoffBlocked, "READER_AND_SENDER_KEYS_MUST_DIFFER"):
                self.receive(f)
        self.assertFalse(f.with_name(f.stem + ".ack.json").exists())

    def test_duplicate_export_does_not_overwrite(self):
        self.archive()
        f = self.send()
        raw = f.read_bytes()
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_ALREADY_EXISTS"):
            self.send()
        self.assertEqual(f.read_bytes(), raw)

    def test_duplicate_receive_does_not_forge_second_ack(self):
        self.archive()
        f = self.send()
        first = self.receive(f)
        raw = Path(first["ack_path"]).read_bytes()
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_ALREADY_EXISTS"):
            self.receive(f)
        self.assertEqual(Path(first["ack_path"]).read_bytes(), raw)

    def test_tampering_payload_without_resigning_denied(self):
        self.archive()
        f = self.send()
        record = json.loads(f.read_text("utf-8"))
        record["payload"]["review"]["event_summary_claim"] = "BUY NOW"
        f.write_bytes(canonical_bytes(record) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_AUTHENTICATION_FAILED"):
            self.receive(f)
        self.assertFalse(f.with_name(f.stem + ".ack.json").exists())

    def test_even_signed_elevation_of_task_ack_is_denied(self):
        self.archive()
        f = self.send()
        record = json.loads(f.read_text("utf-8"))
        record["payload"]["review"]["pre_next_ack_verified"] = True
        record["hmac_sha256"] = hmac.new(
            bytes.fromhex(S_KEY),
            b"100B:GNH01:REVIEW:V1\n" + canonical_bytes(record["payload"]),
            hashlib.sha256,
        ).hexdigest()
        f.write_bytes(canonical_bytes(record) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "REVIEW_SAFETY_STATE_INVALID"):
            self.receive(f)
        self.assertFalse(f.with_name(f.stem + ".ack.json").exists())

    def test_even_signed_real_order_flag_denied(self):
        self.archive()
        f = self.send()
        record = json.loads(f.read_text("utf-8"))
        record["payload"]["real_submit_allowed"] = True
        record["hmac_sha256"] = hmac.new(
            bytes.fromhex(S_KEY),
            b"100B:GNH01:REVIEW:V1\n" + canonical_bytes(record["payload"]),
            hashlib.sha256,
        ).hexdigest()
        f.write_bytes(canonical_bytes(record) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ENVELOPE_SAFETY_INVALID"):
            self.receive(f)

    def test_stale_older_than_15_minutes_denied(self):
        self.archive()
        f = self.send()
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_STALE_OR_FUTURE"):
            self.receive(f, now=NOW + timedelta(minutes=16))

    def test_future_timestamp_denied(self):
        self.archive()
        f = self.send()
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_STALE_OR_FUTURE"):
            self.receive(f, now=NOW - timedelta(seconds=1))

    def test_reader_cannot_accept_renamed_review_file(self):
        self.archive()
        f = self.send()
        forged = self.root / "gnh01_review_FAKE_1_000000000000.json"
        forged.write_bytes(f.read_bytes())
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_FILENAME_CONTENT_MISMATCH"):
            self.receive(forged)

    def test_reader_detects_duplicate_json_keys(self):
        self.archive()
        f = self.send()
        f.write_bytes(b'{"schema_version":"x","schema_version":"y"}\n')
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_JSON_DUPLICATE_KEY"):
            self.receive(f)

    def test_reader_rejects_nan(self):
        self.archive()
        f = self.send()
        f.write_bytes(b'{"unexpected": NaN}')
        with self.assertRaisesRegex(HandoffBlocked, "HANDOFF_JSON_NONFINITE"):
            self.receive(f)

    def test_ack_tampering_fails_independent_verification(self):
        self.archive()
        f = self.send()
        receipt = self.receive(f)
        ack_file = Path(receipt["ack_path"])
        blob = json.loads(ack_file.read_text("utf-8"))
        blob["payload"]["brain_received"] = True
        ack_file.write_bytes(canonical_bytes(blob) + b"\n")
        with self.assertRaisesRegex(HandoffBlocked, "ACK_SAFETY_INVALID"):
            verify_local_ack(ack_file, private_dir=self.root)

    def test_ack_signature_tampering_rejected(self):
        self.archive()
        f = self.send()
        receipt = self.receive(f)
        ack_file = Path(receipt["ack_path"])
        blob = json.loads(ack_file.read_text("utf-8"))
        blob["hmac_sha256"] = "0" * 64
        ack_file.write_bytes(canonical_bytes(blob))
        with self.assertRaisesRegex(HandoffBlocked, "ACK_AUTHENTICATION_FAILED"):
            verify_local_ack(ack_file, private_dir=self.root)

    def test_wrong_receiver_key_cannot_verify_ack(self):
        self.archive()
        f = self.send()
        receipt = self.receive(f)
        with patch.dict(os.environ, {READER_KEY: "b1" * 32}):
            with self.assertRaisesRegex(HandoffBlocked, "ACK_AUTHENTICATION_FAILED"):
                verify_local_ack(receipt["ack_path"], private_dir=self.root)

    def test_private_directory_inside_public_checkout_blocked(self):
        self.archive()
        project = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(HandoffBlocked, "PRIVATE_HANDOFF_FOLDER_UNSAFE"):
            self.send(folder=project)

    def test_symlinked_output_dir_blocked(self):
        self.archive()
        link = self.root / "linked_dir"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("host does not permit symlinks")
        with self.assertRaisesRegex(HandoffBlocked, "PRIVATE_HANDOFF_FOLDER_UNSAFE"):
            self.send(folder=link)


if __name__ == "__main__":
    unittest.main()
