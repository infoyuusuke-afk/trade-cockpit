import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from multiprocessing import get_context
from scripts.ms2_poll_reconciliation import Ledger, canonical, digest, expected_record
from scripts.ms2_offline_observation_writer import record_captured_observation

T0='2026-10-14T00:00:00+00:00'
T1='2026-10-14T00:00:01+00:00'
T2='2026-10-14T00:00:02+00:00'
T3='2026-10-14T00:00:03+00:00'

def capture(poll):
    return dict(symbol='285A.T',market='TSE',poll_seq=poll,source='synthetic-370',
                observation_id='synthetic-370-'+str(poll),watcher_observed_at=T0,
                read_started_at=T0,read_finished_at=T0,sequence_basis='POLL',snapshot_atomic=False,
                levels=[dict(Level=1,AskPrice=101,BidPrice=100,AskQty=0,BidQty=None,read_at=T0)])

def receipt(ledger,poll,stage='QUEUED',identity=None,t=T0,reason='SYNTHETIC_RECEIPT'):
    if stage=='PERSISTED_VERIFIED':
        row=expected_record(capture(poll))
        return ledger.verify_readback(canonical(row)+b'\n',{poll:row},t,source_session=ledger.session,source_generation=ledger.generation)
    return ledger.add(poll_seq=poll,payload_identity=identity or digest(expected_record(capture(poll))),
        stage=stage,observed_at=t,reason_code=reason,source_digest=digest({'fixture':poll,'stage':stage}))

def crash_transaction(directory,conn):
    ledger=Ledger(directory,'s',1)
    ledger.db.execute('BEGIN IMMEDIATE')
    ledger.db.execute('INSERT INTO events VALUES (?,?)',('uncommitted',b'{}'))
    conn.send('uncommitted');conn.close()
    __import__('time').sleep(30)

class PollTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.l=Ledger(self.tmp.name,'s',1)
    def tearDown(self):
        self.l.close();self.tmp.cleanup()
    def rows(self,t=T3,terminal=False):
        return self.l.reconcile(t,window_ended=terminal)['polls']
    def test_exact_shapes_timeout_and_late_recovery(self):
        for accepted,persisted in ((83,80),(79,77),(8,0)):
            with tempfile.TemporaryDirectory() as tmp:
                ledger=Ledger(tmp,'shape',1)
                try:
                    expected={p:expected_record(capture(p)) for p in range(1,accepted+1)}
                    for p in expected:receipt(ledger,p)
                    if persisted:
                        raw=b'\n'.join(canonical(expected[p]) for p in range(1,persisted+1))+b'\n'
                        ledger.verify_readback(raw,expected,T1,source_session='shape',source_generation=1)
                    rows=ledger.reconcile(T2)['polls']
                    self.assertEqual(sum(r['evidence_status']=='PERSISTED_VERIFIED' for r in rows),persisted)
                    self.assertEqual(sum(r['evidence_status']=='UNKNOWN_PENDING' for r in rows),accepted-persisted)
                    rows=ledger.checkpoint(T2,window_ended=True)['polls']
                    self.assertEqual(sum(r['evidence_status']=='UNKNOWN_TERMINAL' for r in rows),accepted-persisted)
                    self.assertTrue(all(r['close_state']=='NOT_CLOSED' and not r['permanent_loss_proven'] for r in rows))
                    # Worker resumes in same session: terminal audit window is
                    # not permanent loss; later evidence resolves the unknowns.
                    raw=b'\n'.join(canonical(expected[p]) for p in expected)+b'\n'
                    ledger.verify_readback(raw,expected,T3,source_session='shape',source_generation=1)
                    self.assertTrue(all(r['evidence_status']=='PERSISTED_VERIFIED' for r in ledger.reconcile(T3)['polls']))
                    self.assertEqual(sum(r['evidence_status']=='PERSISTED_VERIFIED' for r in ledger.reconcile(T2)['polls']),persisted)
                finally:ledger.close()
    def test_explicit_postqueue_rejection_and_prequeue_drop(self):
        receipt(self.l,1); receipt(self.l,1,'REJECTED_POST_QUEUE',t=T1,reason='WORKER_VALIDATION_REFUSED')
        receipt(self.l,2,'DROPPED_PRE_QUEUE',reason='QUEUE_FULL')
        self.assertEqual([r['evidence_status'] for r in self.rows()],['REJECTED_POST_QUEUE','DROPPED_PRE_QUEUE'])
        with self.assertRaisesRegex(ValueError,'QUEUE_EVIDENCE'):receipt(self.l,3,'REJECTED_POST_QUEUE')
    def test_duplicate_idempotent_deterministic_conflicting_poll_failclosed(self):
        receipt(self.l,1); before=canonical(self.l.events());receipt(self.l,1)
        self.assertEqual(before,canonical(self.l.events()))
        receipt(self.l,1,identity='f'*64)
        self.assertTrue(self.rows()[0]['fail_closed'])
        receipt(self.l,1,'PERSISTED_VERIFIED',t=T1)
        self.assertIsNone(self.rows()[0]['persisted_at'])
    def test_drop_and_saved_or_rejection_and_saved_conflict(self):
        receipt(self.l,1,'DROPPED_PRE_QUEUE');receipt(self.l,1)
        receipt(self.l,2);receipt(self.l,2,'REJECTED_POST_QUEUE',t=T1);receipt(self.l,2,'PERSISTED_VERIFIED',t=T2)
        self.assertTrue(all(r['fail_closed'] for r in self.rows()))
    def test_stale_generation_rejected_no_replay(self):
        receipt(self.l,1)
        with self.assertRaisesRegex(ValueError,'STALE'):
            self.l.add(poll_seq=1,payload_identity='a'*64,stage='QUEUED',observed_at=T0,
                reason_code='STALE',source_digest='b'*64,generation=2)
        other=Ledger(self.tmp.name,'s',2)
        try:self.assertEqual(other.reconcile(T3)['polls'],[])
        finally:other.close()
    def test_partial_readback_and_wrong_identity_refused(self):
        receipt(self.l,1);expected={1:expected_record(capture(1))}
        with self.assertRaises(ValueError):self.l.verify_readback(b'{',expected,T1,source_session='s',source_generation=1)
        self.assertEqual(self.rows()[0]['evidence_status'],'UNKNOWN_PENDING')
        altered=expected_record(capture(1));altered['source']='synthetic-other'
        with self.assertRaisesRegex(ValueError,'IDENTITY'):
            self.l.verify_readback(canonical(altered)+b'\n',expected,T1,source_session='s',source_generation=1)
        self.assertTrue(self.rows()[0]['fail_closed'])
    def test_partial_checkpoint_disk_failure_and_stale_cache_cannot_promote(self):
        receipt(self.l,1);self.l.checkpoint(T1);path=self.l.path.with_suffix('.checkpoint.json');old=path.read_bytes()
        for fault in ('partial','before_replace'):
            with self.assertRaises(RuntimeError):self.l.checkpoint(T2,fault=fault)
            self.assertEqual(path.read_bytes(),old)
            self.l.quarantine_partials()
        path.write_text('{"polls":[{"evidence_status":"PERSISTED_VERIFIED"}]}')
        self.assertEqual(self.rows()[0]['evidence_status'],'UNKNOWN_PENDING')
        self.l.db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):receipt(self.l,2)
        self.assertEqual(len(self.rows()),1)
    def test_actual_process_kill_rolls_back_uncommitted_event(self):
        receipt(self.l,1);self.l.close();ctx=get_context('spawn');a,b=ctx.Pipe()
        p=ctx.Process(target=crash_transaction,args=(self.tmp.name,b));p.start();b.close()
        try:
            self.assertTrue(a.poll(10));a.recv();p.kill();p.join(5)
            self.l=Ledger(self.tmp.name,'s',1)
            self.assertEqual(len(self.rows()),1)
            self.assertEqual(self.rows()[0]['evidence_status'],'UNKNOWN_PENDING')
        finally:
            if p.is_alive():p.kill();p.join(3)
            a.close()
    def test_actual_writer_bytes_verify_and_no_pit_price_inference(self):
        receipt(self.l,1);r=record_captured_observation(self.tmp.name,'data/private/ms2_sidecar/test.jsonl',capture(1),enabled=True)
        self.assertEqual(r['transition'],'APPENDED')
        raw=Path(self.tmp.name,'data/private/ms2_sidecar/test.jsonl').read_bytes()
        self.l.verify_readback(raw,{1:expected_record(capture(1))},T1,source_session='s',source_generation=1)
        self.assertEqual(self.rows(T0)[0]['evidence_status'],'UNKNOWN_PENDING')
        self.assertEqual(self.rows()[0]['persisted_at'],T1)
        row=json.loads(raw);self.assertIsNone(row['available_at']);self.assertIsNone(row['levels'][0]['bid_qty'])
        self.assertEqual(row['levels'][0]['ask_qty'],0)
    def test_clock_required_future_evidence_and_unknown_not_closed(self):
        with self.assertRaises(ValueError):receipt(self.l,1,t='2026-10-14T00:00:00')
        receipt(self.l,1,t=T2);self.assertEqual(self.rows(T1),[])
        self.assertEqual(self.rows()[0]['close_state'],'NOT_CLOSED')
    def test_stop_kill_and_simultaneous_death_are_not_rejection_evidence(self):
        for p,reason in enumerate(('STOP','KILL','PRODUCER_CRASH','WRITER_CRASH','SIMULTANEOUS_DEATH','DISK_ERROR'),1):
            receipt(self.l,p);receipt(self.l,p,'UNKNOWN_TERMINAL',t=T1,reason=reason)
        self.assertTrue(all(r['evidence_status']=='UNKNOWN_TERMINAL' and not r['permanent_loss_proven'] for r in self.rows()))

if __name__=='__main__':unittest.main()

class SpawnedWriterReplayTests(unittest.TestCase):
    def test_exact_shapes_real_delayed_writer_resume_and_hard_kill(self):
        from tests.ms2_poll_fault_replay import replay
        for accepted,persisted in ((83,80),(79,77),(8,0)):
            for resume in (False,True):
                r=replay(accepted,persisted,resume=resume)
                self.assertEqual(r['paused'].get('UNKNOWN_TERMINAL'),accepted-persisted)
                self.assertEqual(r['final'].get('PERSISTED_VERIFIED',0),accepted if resume else persisted)
                self.assertEqual(r['close_state'],'NOT_CLOSED')
