import json
import os
import struct
import tempfile
import unittest
from scripts.ms2_drop_evidence import Evidence, read_snapshot, recover


class DropEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.e=Evidence(self.tmp.name, 23)
    def tearDown(self):
        self.e.close(); self.tmp.cleanup()
    def event(self, reason=1):
        b=self.e.shm.buf
        struct.pack_into('<q',b,0,1)
        struct.pack_into('<qq',b,16,1,7)
        struct.pack_into('<5q',b,64+reason*40,1,7,7,100,101)
        struct.pack_into('<q',b,0,2)
    def test_open_precedes_producer_and_never_means_no_gap(self):
        r=recover(self.e.path); self.assertEqual(r['tail'],'UNKNOWN'); self.assertEqual(r['close_state'],'NOT_CLOSED')
    def test_drop_survives_producer_death_and_idempotent_recovery(self):
        self.event(); r=self.e.checkpoint('PRODUCER_CRASH')
        self.assertEqual(r['snapshot']['counters']['QUEUE_FULL']['count'],1)
        self.assertEqual(r['tail'],'UNKNOWN'); self.assertEqual(recover(self.e.path),recover(self.e.path))
        self.e.checkpoint('PRODUCER_CRASH'); self.assertEqual(recover(self.e.path)['snapshot']['total'],1)
    def test_kill_during_partial_checkpoint_keeps_last_committed_evidence(self):
        self.event(); self.e.checkpoint(); old=self.e.path.read_bytes()
        for fault in ('partial','before_replace'):
            with self.assertRaises(RuntimeError): self.e.checkpoint('EXIT_0',fault)
            self.assertEqual(self.e.path.read_bytes(),old)
            self.assertEqual(recover(self.e.path)['tail'],'UNKNOWN')
    def test_torn_shared_update_preserves_lower_bound_and_unknown_tail(self):
        self.event(); self.e.checkpoint(); struct.pack_into('<q',self.e.shm.buf,0,3)
        r=self.e.checkpoint('PRODUCER_CRASH')
        self.assertEqual(r['snapshot']['total'],1); self.assertEqual(r['snapshot_integrity'],'TORN_OR_INVALID')
    def test_corrupt_generation_counter_and_regression_refused(self):
        self.event(); self.e.checkpoint()
        struct.pack_into('<q',self.e.shm.buf,16,0)
        self.assertIsNone(read_snapshot(self.e.shm.buf,23))
        self.assertEqual(self.e.checkpoint()['snapshot_integrity'],'TORN_OR_INVALID')
        self.assertIsNone(read_snapshot(self.e.shm.buf,24))
    def test_truncated_or_tampered_ledger_blocked_no_replay(self):
        self.e.path.write_bytes(b'{"body":')
        self.assertEqual(recover(self.e.path)['state'],'BLOCKED')
    def test_complete_still_not_closed_or_persisted(self):
        self.event(0); struct.pack_into('<q',self.e.shm.buf,32,1)
        r=self.e.checkpoint('EXIT_0'); self.assertEqual(r['tail'],'ACCOUNTED_TO_PRODUCER_COMPLETE')
        self.assertEqual(r['accepted_means'],'QUEUED_ONLY'); self.assertEqual(r['close_state'],'NOT_CLOSED')
    def test_new_generation_no_old_replay(self):
        self.event(); self.e.checkpoint('PRODUCER_CRASH')
        other=Evidence(self.tmp.name,24)
        try:
            self.assertNotEqual(other.session,self.e.session)
            self.assertEqual(recover(other.path)['snapshot']['total'],0)
            self.assertEqual(recover(other.path)['tail'],'UNKNOWN')
        finally: other.close()

if __name__=='__main__': unittest.main()
