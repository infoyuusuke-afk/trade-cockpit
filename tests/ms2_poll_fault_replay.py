"""Controlled queue/Writer fault replay; synthetic evidence only, no IPC guarantee.
Exact shapes are induced by pausing a real spawned unchanged Writer after K
published rows. Unconfirmed historical polls from #369 cannot be reconstructed.
"""
import json
from collections import Counter
from datetime import datetime,timezone
from multiprocessing import get_context
from pathlib import Path
import tempfile
import time
from scripts.ms2_poll_reconciliation import Ledger,digest,expected_record
from scripts.ms2_offline_observation_writer import record_captured_observation
from tests.test_ms2_poll_reconciliation import capture

REL='data/private/ms2_sidecar/replay370.jsonl'
def now():return datetime.now(timezone.utc).isoformat()

def worker(root,queue,pause_after,release,conn):
    saved=0
    if pause_after==0:
        conn.send(('PAUSED',0));release.wait(30)
    while True:
        value=queue.get()
        if value is None:break
        report=record_captured_observation(root,REL,value,enabled=True)
        if report['transition']!='APPENDED':
            conn.send(('REFUSED',value['poll_seq'],report['reasons']));return
        saved+=1
        if saved==pause_after:
            conn.send(('PAUSED',saved));release.wait(30)
    conn.send(('EXIT',saved));conn.close()

def replay(accepted,persisted,*,resume=True):
    ctx=get_context('spawn')
    with tempfile.TemporaryDirectory() as root:
        queue=ctx.Queue(maxsize=8 if (accepted,persisted)==(8,0) else 128);release=ctx.Event();a,b=ctx.Pipe()
        p=ctx.Process(target=worker,args=(root,queue,persisted,release,b))
        ledger=Ledger(Path(root)/'ledger','replay',1);expected={}
        try:
            # Successful real Queue.put is queue evidence only; all captured
            # payloads remain synthetic and the worker can be forcibly killed.
            for poll in range(1,accepted+1):
                value=capture(poll);queue.put_nowait(value);expected[poll]=expected_record(value)
                ledger.add(poll_seq=poll,payload_identity=digest(expected[poll]),stage='QUEUED',
                    observed_at=now(),reason_code='SYNTHETIC_QUEUE_PUT',source_digest=digest({'poll':poll,'fixture':'spawned-queue'}))
            queue_full_verified=False
            if (accepted,persisted)==(8,0):
                from queue import Full
                try:queue.put_nowait(capture(9))
                except Full:queue_full_verified=True
                else:raise RuntimeError('QUEUE_NOT_FULL')
            p.start();b.close()
            if not a.poll(30) or a.recv()!=('PAUSED',persisted):raise RuntimeError('PAUSE_NOT_VERIFIED')
            path=Path(root)/REL
            if persisted:
                ledger.verify_readback(path.read_bytes(),expected,now(),source_session='replay',source_generation=1)
            before=ledger.checkpoint(now(),window_ended=True)
            states=dict(Counter(r['evidence_status'] for r in before['polls']))
            assert states.get('PERSISTED_VERIFIED',0)==persisted
            assert states.get('UNKNOWN_TERMINAL',0)==accepted-persisted
            if resume:
                release.set();queue.put(None)
                if not a.poll(30) or a.recv()!=('EXIT',accepted):raise RuntimeError('RESUME_NOT_VERIFIED')
                p.join(5)
                ledger.verify_readback(path.read_bytes(),expected,now(),source_session='replay',source_generation=1)
                after=ledger.checkpoint(now(),window_ended=True)
                assert all(r['evidence_status']=='PERSISTED_VERIFIED' for r in after['polls'])
                assert sum(r['evidence_status']=='PERSISTED_VERIFIED' for r in ledger.reconcile(before['as_of'])['polls'])==persisted
                final=dict(Counter(r['evidence_status'] for r in after['polls']))
            else:
                p.kill();p.join(5)
                final=dict(Counter(r['evidence_status'] for r in ledger.reconcile(now(),window_ended=True)['polls']))
                next_generation=Ledger(Path(root)/'ledger','replay',2)
                try:assert next_generation.reconcile(now())['polls']==[]
                finally:next_generation.close()
            return dict(accepted=accepted,persisted_at_pause=persisted,paused=states,final=final,
                        outcome='RESUMED_SAME_GENERATION' if resume else 'WRITER_KILLED_NEW_GENERATION_NO_REPLAY',
                        close_state='NOT_CLOSED',queue_full_verified=queue_full_verified,historical_missing_poll_recovery='NOT_VERIFIED')
        finally:
            if p.is_alive():p.kill();p.join(5)
            ledger.close();a.close();queue.cancel_join_thread();queue.close()

def main():
    result=[replay(a,p,resume=resume) for a,p in ((83,80),(79,77),(8,0)) for resume in (False,True)]
    print(json.dumps(result))
if __name__=='__main__':main()
