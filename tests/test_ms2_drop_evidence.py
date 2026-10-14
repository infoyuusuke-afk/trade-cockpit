import json
import os
import struct
import tempfile
import time
import unittest
from multiprocessing import get_context, shared_memory
from pathlib import Path
from scripts.ms2_drop_evidence import Evidence, read_snapshot, recover


def checkpoint_victim(root, conn, fault):
    e=Evidence(root,31)
    conn.send((str(e.path),e.shm.name));conn.close()
    try: e.checkpoint('EXIT_0',fault)
    finally: e.close()


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
        struct.pack_into('<q',self.e.shm.buf,520,25)
        self.assertIsNone(read_snapshot(self.e.shm.buf,23))
        self.assertEqual(self.e.checkpoint()['snapshot_integrity'],'TORN_OR_INVALID')
        self.assertIsNone(read_snapshot(self.e.shm.buf,24))
    def test_mirrored_complete_bank_survives_next_poll_crash_without_checkpoint(self):
        self.event();self.e.shm.buf[512:1024]=self.e.shm.buf[:512]
        struct.pack_into('<q',self.e.shm.buf,0,3)
        r=self.e.checkpoint('PRODUCER_CRASH')
        self.assertEqual(r['snapshot']['total'],1)
        self.assertEqual(r['snapshot_integrity'],'VERIFIED')
        self.assertEqual(r['tail'],'UNKNOWN')
    def test_terminal_dead_ingress_rejects_before_shutdown_gate(self):
        from scripts.ms2_isolated_observation import Ingress, DEAD
        i=Ingress(get_context('spawn'),7);i.meta[2]=DEAD
        i.gate.acquire()
        try:
            self.assertEqual(i.offer(b'x'*2048,1,time.monotonic_ns()),('DROP','NOT_READY'))
            self.assertEqual(i.meta[0],0)
        finally:i.gate.release()
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
    def test_real_checkpoint_owner_kill_preserves_open_commit(self):
        for fault in ('pause_partial','pause_before_replace'):
            ctx=get_context('spawn');parent,child=ctx.Pipe()
            victim=ctx.Process(target=checkpoint_victim,args=(self.tmp.name,child,fault))
            victim.start();child.close()
            retained=None
            try:
                self.assertTrue(parent.poll(5));path_text,map_name=parent.recv();path=Path(path_text)
                retained=shared_memory.SharedMemory(name=map_name)
                deadline=time.monotonic()+5
                while not path.with_suffix('.tmp').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(path.with_suffix('.tmp').exists())
                victim.kill();victim.join(3);self.assertFalse(victim.is_alive())
                r=recover(path)
                self.assertEqual(r['outcome'],'OPEN');self.assertEqual(r['tail'],'UNKNOWN')
            finally:
                if victim.is_alive():victim.kill();victim.join(3)
                parent.close()
                if retained is not None:
                    retained.close()
                    if os.name!='nt':retained.unlink()

if __name__=='__main__': unittest.main()
