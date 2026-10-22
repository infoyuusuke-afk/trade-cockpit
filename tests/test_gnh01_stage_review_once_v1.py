"""Synthetic private staging acceptance; never calls GitHub/PRE-NEXT/Brain."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.gnh01_intelligence_contract_v1 import canonical_bytes, content_digest, ContractBlocked
from scripts.gnh01_durable_archive_v1 import ArchiveBlocked
from scripts.gnh01_private_review_handoff_v1 import (
    SENDER_KEY, READER_KEY, HandoffBlocked, export_review, receive_review,
)
from scripts.gnh01_delivery_chain_audit_v1 import audit_local_chain
from scripts.gnh01_stage_review_once_v1 import stage_json_once, inspect_staged_review
from test_gnh01_intelligence_contract_v1 import fixture, NOW

MODULE = 'scripts.gnh01_stage_review_once_v1'


class StagingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='gnh01_stage_')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / 'archive.db'
        self.event = fixture()
        keys = patch.dict(os.environ, {SENDER_KEY: 'c2'*32, READER_KEY: ''})
        keys.start()
        self.addCleanup(keys.stop)

    def stage(self, *, now=NOW, folder=None):
        return stage_json_once(self.db, canonical_bytes(self.event),
                               private_dir=folder or self.root, now=now)

    def envelope(self):
        return next(self.root.glob('gnh01_review_*.json'))

    def test_stages_without_receiver_key_or_ack(self):
        result = self.stage()
        self.assertEqual(result['state'], 'STAGED_REVIEW_ONLY')
        self.assertTrue(result['local_archive_and_envelope_readback_verified'])
        for key in ('source_authenticity_verified', 'pre_next_automated_receipt_verified',
                    'pre_next_ack_verified', 'shadow_ingestion_verified',
                    'brain_receipt_verified', 'end_to_end_verified', 'real_submit_allowed'):
            self.assertIs(result[key], False)
        self.assertEqual(list(self.root.glob('*.ack.json')), [])

    def test_duplicate_is_readback_only(self):
        first = self.stage()
        before = self.envelope().read_bytes()
        with patch(MODULE+'.export_review', side_effect=AssertionError('resend')):
            self.assertEqual(self.stage(), first)
        self.assertEqual(self.envelope().read_bytes(), before)

    def test_failure_before_file_creation_stays_unknown(self):
        with patch(MODULE+'.export_review', side_effect=OSError('synthetic failure')) as send:
            with self.assertRaises(OSError):
                self.stage()
            with self.assertRaisesRegex(HandoffBlocked, 'SEND_UNKNOWN_NO_RETRY'):
                self.stage()
            self.assertEqual(send.call_count, 1)
        self.assertEqual(list(self.root.glob('gnh01_review_*.json')), [])

    def test_write_then_exception_never_resends(self):
        def uncertain(*args, **kwargs):
            export_review(*args, **kwargs)
            raise OSError('synthetic post-write failure')
        with patch(MODULE+'.export_review', side_effect=uncertain) as send:
            with self.assertRaises(OSError):
                self.stage()
            original = self.envelope().read_bytes()
            with self.assertRaisesRegex(HandoffBlocked, 'SEND_UNKNOWN_NO_RETRY'):
                self.stage()
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.envelope().read_bytes(), original)

    def test_readback_failure_stays_unknown(self):
        with patch(MODULE+'._inspect', side_effect=HandoffBlocked('synthetic read failure')):
            with self.assertRaises(HandoffBlocked):
                self.stage()
        with self.assertRaisesRegex(HandoffBlocked, 'SEND_UNKNOWN_NO_RETRY'):
            self.stage()

    def test_unknown_cannot_be_promoted_by_inspection(self):
        self.stage()
        with closing(sqlite3.connect(self.db)) as con, con:
            con.execute("UPDATE gnh01_review_dispatch_v1 SET state='SEND_UNKNOWN'")
        with self.assertRaisesRegex(HandoffBlocked, 'DISPATCH_UNVERIFIED_NO_RETRY'):
            inspect_staged_review(self.db, self.event, private_dir=self.root, now=NOW)

    def test_conflicting_content_blocked(self):
        self.stage()
        self.event['event_summary'] = 'Different synthetic content'
        self.event['content_hash'] = content_digest(self.event)
        with self.assertRaisesRegex(ArchiveBlocked, 'REVISION_CONTENT_CONFLICT'):
            self.stage()

    def test_changed_destination_blocked(self):
        self.stage()
        other = self.root / 'other'
        other.mkdir(mode=0o700)
        with self.assertRaisesRegex(HandoffBlocked, 'DISPATCH_IDENTITY_CONFLICT'):
            self.stage(folder=other)
        self.assertEqual(list(other.iterdir()), [])

    def test_missing_completed_file_not_recreated(self):
        self.stage()
        self.envelope().unlink()
        with patch(MODULE+'.export_review', side_effect=AssertionError('resend')):
            with self.assertRaises(HandoffBlocked):
                self.stage()
        self.assertEqual(list(self.root.glob('gnh01_review_*.json')), [])

    def test_tampered_envelope_blocks(self):
        self.stage()
        self.envelope().write_bytes(b'{}')
        with self.assertRaisesRegex(HandoffBlocked, 'STAGED_ENVELOPE_INVALID'):
            self.stage()

    def test_changed_key_blocks_existing_file(self):
        self.stage()
        with patch.dict(os.environ, {SENDER_KEY:'d4'*32}):
            with self.assertRaisesRegex(HandoffBlocked, 'STAGED_SIGNATURE_INVALID'):
                self.stage()

    def test_stale_duplicate_not_refreshed(self):
        self.stage()
        before = self.envelope().read_bytes()
        with self.assertRaisesRegex(HandoffBlocked, 'STAGED_STALE_OR_FUTURE'):
            self.stage(now=NOW+timedelta(minutes=16))
        self.assertEqual(self.envelope().read_bytes(), before)

    def test_concurrent_workers_export_at_most_once(self):
        def worker(_):
            try:
                return self.stage()['state']
            except HandoffBlocked as exc:
                return str(exc)
        with patch(MODULE+'.export_review', wraps=export_review) as send:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(worker, range(8)))
            self.assertEqual(send.call_count, 1)
        self.assertIn('STAGED_REVIEW_ONLY', results)
        self.assertTrue(set(results) <= {'STAGED_REVIEW_ONLY', 'SEND_UNKNOWN_NO_RETRY'})

    def test_delivery_test_is_not_market_event(self):
        raw = b'[100B_COORD_V1]\nmessage_id: SYNTHETIC\nevent_type: DELIVERY_TEST'
        with self.assertRaises(ContractBlocked):
            stage_json_once(self.db, raw, private_dir=self.root, now=NOW)
        self.assertFalse(self.db.exists())

    def test_duplicate_json_keys_rejected_before_storage(self):
        with self.assertRaises(ContractBlocked):
            stage_json_once(self.db, b'{"event_id":"a","event_id":"b"}',
                            private_dir=self.root, now=NOW)
        self.assertFalse(self.db.exists())

    def test_unsafe_order_flag_rejected_before_storage(self):
        self.event['real_submit_allowed'] = True
        self.event['content_hash'] = content_digest(self.event)
        with self.assertRaises(ArchiveBlocked):
            self.stage()
        self.assertFalse(self.db.exists())

    def test_missing_key_has_no_side_effect(self):
        with patch.dict(os.environ, {SENDER_KEY:''}):
            with self.assertRaises(HandoffBlocked):
                self.stage()
        self.assertFalse(self.db.exists())

    def test_naive_clock_rejected(self):
        with self.assertRaises(ArchiveBlocked):
            self.stage(now=NOW.replace(tzinfo=None))
        self.assertFalse(self.db.exists())

    def test_future_event_rejected(self):
        with self.assertRaises(ArchiveBlocked):
            self.stage(now=NOW-timedelta(days=1))
        self.assertFalse(self.db.exists())

    def test_separate_local_reader_can_use_existing_contract(self):
        self.stage()
        with patch.dict(os.environ, {READER_KEY:'d3'*32}):
            receive_review(self.envelope(), private_dir=self.root, now=NOW)
            result = audit_local_chain(self.db, self.event, private_dir=self.root, now=NOW)
        self.assertEqual(result['state'], 'LOCAL_CHAIN_MATCH_RESEARCH_ONLY')
        self.assertFalse(result['pre_next_scheduled_task_ack_verified'])
        self.assertFalse(result['brain_receiver_ack_verified'])


if __name__ == '__main__':
    unittest.main()
