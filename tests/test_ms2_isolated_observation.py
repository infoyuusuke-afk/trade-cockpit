import ast
import hashlib
import os
import tempfile
import time
import unittest
from multiprocessing import get_context, shared_memory
from pathlib import Path
from scripts.ms2_isolated_observation import OfflineLane, Ingress, READY, STOP, KILL, DEAD, contract
from scripts.ms2_bridge_record import pack_capture
from scripts import ms2_nonblocking_handoff as h
from tests.test_ms2_ps_python_bridge import _board, RELATIVE


def foreign(i_data, tags, meta, gate, generation, owner_pid, conn):
    i = Ingress.__new__(Ingress)
    i.data, i.tags, i.meta, i.gate = i_data, tags, meta, gate
    i.generation, i.owner_pid = generation, owner_pid
    import threading
    i.owner_thread = threading.get_ident()
    from scripts.ms2_isolated_observation import REASONS
    i.counts = {k: [0]*5 for k in REASONS}; i.last_poll = i.accepted = 0
    i.view = memoryview(i_data).cast('B')
    conn.send(i.offer(pack_capture(_board())['record'], 3, time.monotonic_ns())); conn.close()


class IsolatedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.lanes = []
        self.record = pack_capture(_board())['record']

    def tearDown(self):
        for lane in self.lanes:
            lane.stop()
            if lane.process and lane.process.is_alive():
                lane.process.join(3)
                self.assertFalse(lane.process.is_alive(), 'owned consumer did not stop')
        self.tmp.cleanup()

    def lane(self, **kwargs):
        lane = OfflineLane(self.tmp.name, RELATIVE, enabled=True,
                           require_authentication=False, **kwargs)
        self.lanes.append(lane); self.assertEqual(lane.status, 'READY', vars(lane))
        return lane

    def wait(self, predicate):
        end = time.monotonic()+5
        while time.monotonic()<end:
            if predicate(): return
            time.sleep(.005)
        self.fail('condition not observed')

    def manual(self):
        i = Ingress(get_context('spawn'), 123)
        i.meta[2] = READY; i.meta[3] = time.monotonic_ns()
        return i

    def test_default_and_required_auth_refuse_without_creating_private_files(self):
        self.assertEqual(OfflineLane(self.tmp.name, RELATIVE).status, 'DISABLED')
        lane = OfflineLane(self.tmp.name, RELATIVE, enabled=True)
        self.assertEqual((lane.status,lane.reason), ('P0_BLOCKED','SAME_USER_AUTH_UNRESOLVED'))
        self.assertIsNone(lane.ingress); self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_normal_independent_consumer_preserves_canonical_missing_quantity(self):
        lane = self.lane(); i = lane.ingress
        self.assertEqual(i.offer(self.record,3,time.monotonic_ns())[0], 'ACCEPTED')
        self.wait(lambda: lane.control('metrics')['writer']['durable']==1)
        import json
        record = json.loads((Path(self.tmp.name)/RELATIVE).read_text())
        self.assertEqual(contract()['close_state'], 'NOT_CLOSED')
        self.assertFalse(record['snapshot_atomic'])
        self.assertFalse(record['levels'][0]['bid_qty_known'])
        self.assertEqual(record['levels'][0]['ask_qty'],0)
        self.assertEqual(contract()['eligible_observed_n'],0)

    def test_full_drop_exact_point_time_counters_no_stale_retry(self):
        i=self.manual(); at=time.monotonic_ns()
        for n in range(1,9): self.assertEqual(i.offer(self.record,n,at)[0],'ACCEPTED')
        for n in range(9,29): self.assertEqual(i.offer(self.record,n,at),('DROP','QUEUE_FULL'))
        self.assertEqual(i.audit()['drops']['QUEUE_FULL']['count'],20)
        self.assertEqual(i.audit()['drops']['QUEUE_FULL']['first_poll'],9)
        self.assertEqual(i.audit()['drops']['QUEUE_FULL']['last_poll'],28)
        self.assertEqual(i.offer(self.record,28,at),('DROP','STALE_INPUT'))

    def test_gate_abandonment_never_waits_or_resets_foreign_lock(self):
        i=self.manual(); i.gate.acquire()
        try:
            for n in range(1,101): self.assertEqual(i.offer(self.record,n,time.monotonic_ns()),('DROP','GATE_BUSY'))
            self.assertEqual(i.audit()['drops']['GATE_BUSY']['count'],100)
        finally: i.gate.release()

    def test_stop_kill_stale_generation_and_input_fail_closed(self):
        i=self.manual()
        for n,state,reason in ((1,STOP,'STOP_PENDING'),(2,KILL,'KILL_SWITCH'),(3,DEAD,'NOT_READY')):
            i.meta[2]=state; self.assertEqual(i.offer(self.record,n,time.monotonic_ns()),('DROP',reason))
        i.meta[2]=READY; i.meta[3]=0
        self.assertEqual(i.offer(self.record,4,time.monotonic_ns()),('DROP','CONSUMER_STALE'))
        i.meta[3]=time.monotonic_ns()
        self.assertEqual(i.offer(self.record,5,time.monotonic_ns(),122),('DROP','OLD_GENERATION'))
        self.assertEqual(i.offer(self.record,6,time.monotonic_ns()-2_000_000_000),('DROP','STALE_INPUT'))
        self.assertEqual(i.offer(bytearray(self.record),7,time.monotonic_ns()),('DROP','INPUT_INVALID'))

    def test_spawned_second_producer_refused(self):
        i=self.manual(); ctx=get_context('spawn'); p,c=ctx.Pipe()
        process=ctx.Process(target=foreign,args=(i.data,i.tags,i.meta,i.gate,i.generation,i.owner_pid,c))
        process.start(); self.assertTrue(p.poll(5)); self.assertEqual(p.recv(),('DROP','WRONG_PRODUCER'))
        process.join(5); self.assertEqual(process.exitcode,0); self.assertEqual(i.meta[0],0)
        p.close();c.close()

    def inject(self, mutation, reason):
        lane=self.lane(); lane.control('hold'); lane.control('metrics')
        i=lane.ingress; self.assertEqual(i.offer(self.record,3,time.monotonic_ns())[0],'ACCEPTED')
        with i.gate: mutation(i)
        lane.control('resume')
        self.wait(lambda: lane.control('metrics')['refused'].get(reason)==1)
        self.assertFalse((Path(self.tmp.name)/RELATIVE).exists())
        self.assertEqual(i.meta[1],i.meta[0])

    def test_torn_commit_refused_consumed_no_replay(self):
        self.inject(lambda i: i.tags.__setitem__(0,0),'TORN_OR_OLD_GENERATION')

    def test_ABA_generation_refused(self):
        self.inject(lambda i: i.tags.__setitem__(1,i.generation-1),'TORN_OR_OLD_GENERATION')

    def test_payload_corruption_refused(self):
        self.inject(lambda i: i.data.__setitem__(600,42),'PAYLOAD_CORRUPT')

    def test_stale_acquisition_refused(self):
        self.inject(lambda i: i.tags.__setitem__(2,time.monotonic_ns()-2_000_000_000),'STALE_ACQUISITION')

    def test_consumer_hard_stop_price_voice_signal_continue(self):
        lane=self.lane(); lane.process.kill(); lane.process.join(2)
        # Exact owned child only. Orphan writer must detect dead B owner.
        i=lane.ingress
        price=voice=signal=0
        for n in range(1,201):
            price+=1;voice+=1;signal+=1
            i.offer(self.record,n,time.monotonic_ns())
        self.assertEqual((price,voice,signal),(200,200,200))
        self.assertGreater(sum(v[0] for v in i.counts.values()),0)
        self.assertLessEqual(i.meta[0]-i.meta[1],8)
        old=shared_memory.SharedMemory(name=lane.start_report['map_name'])
        try:
            self.wait(lambda: h._read_reason(old.buf)=='OWNER_DEAD_QUARANTINED')
        finally:
            old.close()
            if os.name!='nt':
                try: old.unlink()
                except FileNotFoundError: pass

    def test_writer_stop_disables_observation_without_stopping_critical_mock(self):
        lane=self.lane(); lane.control('kill_writer')
        self.wait(lambda: lane.ingress.meta[2]==DEAD)
        ticks=[lane.ingress.offer(self.record,n,time.monotonic_ns()) for n in range(1,101)]
        self.assertTrue(all(x==('DROP','NOT_READY') for x in ticks))

    def test_simulated_unresponsive_writer_killed_preserves_existing_jsonl(self):
        from scripts.ms2_offline_observation_writer import record_captured_observation
        record_captured_observation(self.tmp.name,RELATIVE,_board(),enabled=True)
        path=Path(self.tmp.name)/RELATIVE; original=path.read_bytes()
        lane=self.lane(fault=h.FAULT_WRITE_INFLIGHT)
        blob=pack_capture(_board(poll_seq=4))['record']
        lane.ingress.offer(blob,4,time.monotonic_ns())
        old=shared_memory.SharedMemory(name=lane.start_report['map_name'])
        try:
            self.wait(lambda:h._read_reason(old.buf)=='IO_INFLIGHT')
            report=lane.stop(); self.assertEqual(report['status'],'STOPPED')
            self.assertTrue(report['stop']['killed'])
            self.assertEqual(path.read_bytes(),original)
            for n in range(5,105):
                self.assertEqual(lane.ingress.offer(blob,n,time.monotonic_ns())[0],'DROP')
        finally:
            h._store(old.buf,h._OFF_FAULT,h.FAULT_NONE)
            lane.process.join(5); old.close()
        self.assertFalse(lane.process.is_alive()); self.assertEqual(path.read_bytes(),original)

    def test_critical_method_excludes_start_attach_pack_sha_io_and_wait(self):
        import inspect
        source=inspect.getsource(Ingress.offer)
        import textwrap
        tree=ast.parse(textwrap.dedent(source))
        calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
        for denied in ('open','sleep','join','start','pack_capture','publish_bytes','ComputeHash','send','recv'):
            self.assertFalse(any(c.endswith('.'+denied) or c==denied for c in calls),calls)
        self.assertIn('self.gate.acquire(False)',source)

    def test_consumer_gate_stop_pending_keeps_critical_path_dropping(self):
        lane=self.lane(); i=lane.ingress
        i.gate.acquire()
        try:
            report=lane.stop(); self.assertEqual(report['status'],'STOP_PENDING')
            for n in range(1,101):
                self.assertEqual(i.offer(self.record,n,time.monotonic_ns()),('DROP','GATE_BUSY'))
        finally: i.gate.release()
        lane.process.join(3); self.assertFalse(lane.process.is_alive())
