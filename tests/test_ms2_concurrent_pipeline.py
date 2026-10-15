import os
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import ms2_nonblocking_handoff as h
from scripts import ms2_ipc_integrity as ipc
from tests.ms2_concurrent_pipeline import run, normal_failure_evidence

class ConcurrentTests(unittest.TestCase):

    def test_gate_failure_snapshot_preserves_unknown_and_no_death_claim(self):
        buf = bytearray(h.SHM_SIZE)
        h._store(buf, h._OFF_HEARTBEAT, 800_000_000)
        h._store(buf, h._OFF_WRITE, 32)
        h._store(buf, h._OFF_READ, 31)
        h._store(buf, h._OFF_FAIL_CLOSED, 1)
        h._reason(buf, 'IPC_GATE_ABANDONED')
        struct.pack_into('<I', buf, ipc.GATE, 1)
        worker = SimpleNamespace(is_alive=lambda: False, exitcode=0)
        session = SimpleNamespace(_shm=SimpleNamespace(buf=buf), _process=worker)
        producer = SimpleNamespace(poll=lambda: 0)
        with patch('tests.ms2_concurrent_pipeline.time.monotonic_ns', return_value=1_000_000_000):
            evidence = normal_failure_evidence(
                {'PERSISTED_VERIFIED': 31, 'UNKNOWN_TERMINAL': 1, 'DROPPED_PRE_QUEUE': 68},
                [{'state': 'ACCEPTED'}] * 32, [{'transition': 'APPENDED'}] * 31,
                session, producer, True)
        self.assertEqual(evidence['accepted'], 32)
        self.assertEqual(evidence['heartbeat_age_ms'], 200.0)
        self.assertEqual(evidence['gate_word'], 1)
        self.assertEqual(evidence['fail_closed_count'], 1)
        self.assertEqual(evidence['write_index']-evidence['read_index'], 1)
        self.assertFalse(evidence['mutex_abandonment_proven'])
        self.assertEqual(evidence['production'], 'P0_BLOCKED')
        self.assertNotIn('symbol', str(evidence))
        self.assertNotIn('record', str(evidence))

    def test_uninitialized_heartbeat_is_unknown(self):
        buf = bytearray(h.SHM_SIZE)
        session = SimpleNamespace(_shm=SimpleNamespace(buf=buf),
                                  _process=SimpleNamespace(is_alive=lambda: True, exitcode=None))
        evidence = normal_failure_evidence({}, [], [], session, None, False)
        self.assertIsNone(evidence['heartbeat_age_ms'])
        self.assertIsNone(evidence['producer_exitcode'])
        self.assertEqual(evidence['worker_transitions'], {})
        self.assertFalse(evidence['mutex_abandonment_proven'])

    def test_real_bridge_writer_concurrent_faults(self):
        for mode in ('normal','delay','queue_full','gate_busy','permission','partial','before_replace','after_replace','worker_kill','kill','stop','duplicate','receipt_loss'):
            with self.subTest(mode=mode):
                r=run(mode,n=16)
                self.assertEqual(r['attempts'],16)
                self.assertEqual(r['queued']+r['drops'],16)
                self.assertEqual(r['close_state'],'NOT_CLOSED')
                self.assertEqual(r['production'],'P0_BLOCKED')
                self.assertEqual(r['five_ms'],'NOT_MET')
                self.assertEqual(sum(r['states'].values()),1 if mode=='duplicate' else 16)
                if mode=='gate_busy':self.assertGreater(r['cohorts']['GATE_BUSY']['full_ms']['N'],0)
    @unittest.skipUnless(os.name=='nt','Native Windows PS5.1 required')
    def test_native_real_bridge_concurrent(self):
        r=run('normal',n=16,native=True)
        self.assertEqual(r['ps'].split('.')[:2],['5','1'])
        self.assertTrue(r['concurrent_completion_observed'])
        self.assertEqual(r['states'].get('PERSISTED_VERIFIED'),r['queued'])

if __name__=='__main__':unittest.main()
