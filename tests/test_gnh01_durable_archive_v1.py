"""Synthetic GNH01 durable archive acceptance: no network, broker, V10 or paid APIs."""
from __future__ import annotations

import copy
import json
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from scripts.gnh01_intelligence_contract_v1 import content_digest
from scripts.gnh01_durable_archive_v1 import (
    ArchiveBlocked, archive_event, archive_json_once, read_archive_receipt,
)
from test_gnh01_intelligence_contract_v1 import fixture, NOW


class DurableArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gnh01_archive_")
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "private_archive.db"
        self.clock = lambda: NOW

    def event(self, *, revision=1, summary=None):
        x = fixture()
        x["event_revision"] = revision
        if summary is not None:
            x["event_summary"] = summary
        x["content_hash"] = content_digest(x)
        return x

    def record(self, event=None, *, clock=None):
        return archive_event(self.db, event or self.event(), clock=clock or self.clock)

    def test_new_event_requires_independent_durable_readback(self):
        result = self.record()
        self.assertEqual(result["state"], "ARCHIVED_RESEARCH_ONLY")
        self.assertEqual(result["available_at"], NOW.isoformat())
        self.assertTrue(result["receipt_independently_read_back"])
        self.assertFalse(result["available_at_verified"])
        self.assertFalse(result["receiver_clock_attested"])
        self.assertFalse(result["source_authenticity_verified"])
        self.assertFalse(result["shadow_eligible"])
        self.assertFalse(result["brain_receiver_ack_verified"])
        self.assertIs(result["real_submit_allowed"], False)
        self.assertFalse(result["duplicate"])
        self.assertEqual(read_archive_receipt(self.db, result["event_id"], 1)["state"], "ARCHIVED")

    def test_one_shot_json_ingest_durable_without_delivery_claim(self):
        raw = json.dumps(self.event(), ensure_ascii=False).encode("utf-8")
        first = archive_json_once(self.db, raw, clock=self.clock)
        self.assertEqual(first["state"], "ARCHIVED_RESEARCH_ONLY")
        self.assertTrue(first["receipt_independently_read_back"])
        self.assertFalse(first["available_at_verified"])
        self.assertFalse(first["brain_receiver_ack_verified"])
        self.assertFalse(first["shadow_eligible"])
        again = archive_json_once(self.db, raw, clock=self.clock)
        self.assertTrue(again["duplicate"])

    def test_one_shot_rejects_ambiguous_json_before_sqlite_creation(self):
        with self.assertRaisesRegex(ArchiveBlocked, "JSON_DUPLICATE_KEY"):
            archive_json_once(self.db, b'{"a":1,"a":2}', clock=self.clock)
        self.assertFalse(self.db.exists())

    def test_one_shot_real_order_true_denied_before_sqlite_creation(self):
        x = self.event()
        x["real_submit_allowed"] = True
        x["content_hash"] = content_digest(x)
        raw = json.dumps(x, ensure_ascii=False).encode("utf-8")
        with self.assertRaisesRegex(ArchiveBlocked, "SCHEMA_OR_SAFETY_GATE_INVALID"):
            archive_json_once(self.db, raw, clock=self.clock)
        self.assertFalse(self.db.exists())

    def test_same_event_revision_and_hash_is_idempotent(self):
        first = self.record()
        again = self.record()
        self.assertTrue(again["duplicate"])
        self.assertEqual(first["raw_payload_sha256"], again["raw_payload_sha256"])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM grok_archive_v1").fetchone()[0], 1)

    def test_changed_claimed_receipt_cannot_backdate_real_local_receipt(self):
        x = self.event()
        first = self.record(x)
        y = copy.deepcopy(x)
        y["bridge_received_at"] = "2026-10-21T23:08:00Z"
        self.assertEqual(x["content_hash"], y["content_hash"])
        again = self.record(y)
        self.assertTrue(again["duplicate"])
        self.assertEqual(first["received_at"], again["received_at"])
        self.assertEqual(first["available_at"], again["available_at"])

    def test_conflicting_revision_rejected_even_when_rehashed(self):
        self.record()
        with self.assertRaisesRegex(ArchiveBlocked, "REVISION_CONTENT_CONFLICT"):
            self.record(self.event(summary="changed with same revision"))

    def test_correction_appends_and_preserves_previous_revision(self):
        first = self.record()
        second = self.record(self.event(revision=2, summary="material correction"))
        self.assertNotEqual(first["content_hash"], second["content_hash"])
        self.assertEqual(read_archive_receipt(self.db, first["event_id"], 1)["content_hash"], first["content_hash"])
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM grok_archive_v1").fetchone()[0], 2)

    def test_revision_gap_without_history_blocked(self):
        with self.assertRaisesRegex(ArchiveBlocked, "REVISION_GAP_OR_REGRESSION"):
            self.record(self.event(revision=2))

    def test_nonsequential_revision_blocked(self):
        self.record()
        with self.assertRaisesRegex(ArchiveBlocked, "REVISION_GAP_OR_REGRESSION"):
            self.record(self.event(revision=3))

    def test_new_revision_clock_rollback_rejected(self):
        self.record()
        earlier = NOW - timedelta(minutes=1)
        # An earlier local clock can otherwise backdate a newly delivered correction.
        with self.assertRaisesRegex(ArchiveBlocked, "RECEIVER_CLOCK_REGRESSION"):
            self.record(self.event(revision=2), clock=lambda: earlier)

    def test_missing_db_readback_blocked(self):
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_NOT_FOUND"):
            read_archive_receipt(self.db, "SYN-GNH01-001", 1)

    def test_relative_database_path_blocked(self):
        with self.assertRaisesRegex(ArchiveBlocked, "PRIVATE_STORAGE_PATH_REQUIRED"):
            archive_event(Path("public_repo.db"), self.event(), clock=self.clock)

    def test_checkout_storage_path_blocked_without_creating_db(self):
        # Never allow even a synthetic event to place raw research in public git.
        unsafe = Path(__file__).resolve().parents[1] / "GNH01_UNSAFE.db"
        self.assertFalse(unsafe.exists())
        with self.assertRaisesRegex(ArchiveBlocked, "PRIVATE_STORAGE_INSIDE_REPOSITORY"):
            archive_event(unsafe, self.event(), clock=self.clock)
        self.assertFalse(unsafe.exists())

    def test_external_symlinked_private_folder_blocked(self):
        link = Path(self.tmp.name) / "redirect"
        safe = Path(self.tmp.name) / "real"
        safe.mkdir()
        try:
            link.symlink_to(safe, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation prohibited by host")
        with self.assertRaisesRegex(ArchiveBlocked, "PRIVATE_STORAGE_LINK_UNTRUSTED"):
            archive_event(link / "archive.db", self.event(), clock=self.clock)
        self.assertFalse((safe / "archive.db").exists())

    def test_externally_world_readable_parent_blocked_on_posix(self):
        import os
        if os.name == "nt":
            self.skipTest("Windows ACLs require separate independent validation")
        path = Path(self.tmp.name) / "shared"
        path.mkdir(mode=0o755)
        path.chmod(0o755)
        with self.assertRaisesRegex(ArchiveBlocked, "PRIVATE_STORAGE_PERMISSION_UNSAFE"):
            archive_event(path / "archive.db", self.event(), clock=self.clock)
        self.assertFalse((path / "archive.db").exists())

    def test_existing_hardlinked_archive_blocked(self):
        source = Path(self.tmp.name) / "source.db"
        source.write_text("synthetic", encoding="utf-8")
        try:
            source.hardlink_to(self.db)
        except FileNotFoundError:
            # Path.hardlink_to(target): create self as link to target.
            self.db.hardlink_to(source)
        except OSError:
            self.skipTest("hard links unsupported")
        # Ensure the path itself is not a normal single-link database file.
        if not self.db.exists():
            self.db.hardlink_to(source)
        with self.assertRaisesRegex(ArchiveBlocked, "PRIVATE_STORAGE_FILE_UNSAFE"):
            archive_event(self.db, self.event(), clock=self.clock)

    def test_sender_real_submit_allowed_true_rejected_before_storage(self):
        x = self.event()
        x["real_submit_allowed"] = True
        with self.assertRaisesRegex(ArchiveBlocked, "SCHEMA_OR_SAFETY_GATE_INVALID"):
            self.record(x)
        self.assertFalse(self.db.exists())

    def test_naive_local_clock_rejected(self):
        with self.assertRaisesRegex(ArchiveBlocked, "RECEIVER_CLOCK_UNVERIFIED"):
            self.record(clock=lambda: datetime(2026, 10, 22))

    def test_unverified_source_primary_claim_never_becomes_trading_authority(self):
        x = self.event()
        x["evidence_status"] = "PRIMARY_VERIFIED"
        x["content_hash"] = content_digest(x)
        v = self.record(x)
        self.assertFalse(v["source_authenticity_verified"])
        self.assertFalse(v["shadow_eligible"])

    def test_payload_db_corruption_detected_after_restart(self):
        result = self.record()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE grok_archive_v1 SET payload_json='{}'")
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            read_archive_receipt(self.db, result["event_id"], 1)

    def test_payload_sha_db_corruption_detected(self):
        result = self.record()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE grok_archive_v1 SET payload_sha256=?", ("0" * 64,))
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            read_archive_receipt(self.db, result["event_id"], 1)

    def test_available_at_tamper_after_archive_rejected(self):
        result = self.record()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(
                "UPDATE grok_archive_v1 SET available_at=?",
                ((NOW - timedelta(minutes=2)).isoformat(),)
            )
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            read_archive_receipt(self.db, result["event_id"], 1)

    def test_received_at_tamper_after_archive_rejected(self):
        result = self.record()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute(
                "UPDATE grok_archive_v1 SET received_at=?",
                ((NOW - timedelta(minutes=10)).isoformat(),)
            )
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            read_archive_receipt(self.db, result["event_id"], 1)

    def test_receipt_checksum_tamper_rejected(self):
        result = self.record()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute("UPDATE grok_archive_v1 SET receipt_sha256=?", ("0" * 64,))
        with self.assertRaisesRegex(ArchiveBlocked, "ARCHIVE_INTEGRITY_FAILURE"):
            read_archive_receipt(self.db, result["event_id"], 1)

    def test_crash_between_pending_and_archived_can_recover_without_duplicate(self):
        sequence = iter([NOW, NOW - timedelta(seconds=1)])
        with self.assertRaisesRegex(ArchiveBlocked, "RECEIVER_CLOCK_REGRESSION"):
            self.record(clock=lambda: next(sequence))
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT state FROM grok_archive_v1").fetchone()[0], "PENDING")
        recovered = self.record(clock=self.clock)
        self.assertTrue(recovered["duplicate"])
        self.assertEqual(recovered["state"], "ARCHIVED_RESEARCH_ONLY")
        self.assertEqual(read_archive_receipt(self.db, recovered["event_id"], 1)["state"], "ARCHIVED")

    def test_concurrent_same_message_serializes_to_one_durable_row(self):
        results, errors = [], []
        def write():
            try:
                results.append(self.record())
            except Exception as exc:
                errors.append(type(exc).__name__ + ":" + str(exc))
        threads = [threading.Thread(target=write) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(errors, errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM grok_archive_v1").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
