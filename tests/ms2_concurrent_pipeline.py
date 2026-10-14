"""Offline synthetic native receipt -> unchanged Bridge/Worker/Writer -> ledger.
The wrapper instruments only this spawned fixture; never a live import path.
Receipt stdout acknowledgements and audit fsync can add pacing/backpressure.
No bound, authentication, power-loss or live eligibility claim is made.
"""
import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import tempfile
import threading
import time
from scripts import ms2_nonblocking_handoff as h
from scripts.ms2_ps_python_bridge import start_bridge
from scripts.ms2_bridge_record import pack_capture, unpack_capture
from scripts.ms2_poll_reconciliation import Ledger, canonical, digest, expected_record
from tests.ms2_native_drop_benchmark import stats

ROOT=Path(__file__).resolve().parents[1]
REL='data/private/ms2_sidecar/concurrent372.jsonl'
ORIGINAL_ENTRY=h._worker_entry
ORIGINAL_WRITER=h.record_captured_observation

def now():return datetime.now(timezone.utc).isoformat()

def instrumented_entry(name, root, relative, generation):
    """Spawn-safe delegate; no changes to the canonical writer implementation."""
    def measured(repo, rel, capture, *, enabled=False, hooks=None):
        begun=time.perf_counter(); fsync=[]; supplied=dict(hooks or {})
        original_fsync=supplied.get('fsync',os.fsync)
        def sync(fd):
            t=time.perf_counter()
            try:return original_fsync(fd)
            finally:fsync.append((time.perf_counter()-t)*1000)
        supplied['fsync']=sync
        if Path(root,'delay.flag').exists():time.sleep(.03)
        report=ORIGINAL_WRITER(repo,rel,capture,enabled=enabled,hooks=supplied)
        body=dict(session_id='native-'+str(generation),generation=generation,poll_seq=capture['poll_seq'],
            payload_identity=digest(expected_record(capture)),observed_at=now(),
            transition=report['transition'],reasons=report.get('reasons',[]),
            worker_ms=(time.perf_counter()-begun)*1000,fsync_ms=fsync)
        # One writer, append-only audit stream. Loss/partial tail never proves rejection.
        with open(Path(root,'worker-evidence.jsonl'),'ab') as f:
            f.write(canonical(body)+b'\n');f.flush();os.fsync(f.fileno())
        return report
    h.record_captured_observation=measured
    try:ORIGINAL_ENTRY(name,root,relative,generation)
    finally:h.record_captured_observation=ORIGINAL_WRITER

def start(root,fault=0):
    h._worker_entry=instrumented_entry
    try:return start_bridge(root,REL,enabled=True,fault=fault)
    finally:h._worker_entry=ORIGINAL_ENTRY

def complete_lines(path):
    if not path.exists():return []
    raw=path.read_bytes();parts=raw.split(b'\n')
    return [json.loads(p) for p in parts[:-1] if p]

def synthetic(poll,generation,duplicate=False):
    stamp='2026-10-14T00:00:00+00:00' if duplicate else datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    return dict(symbol='285A.T',market='TSE',source='synthetic-372',poll_seq=poll,
        observation_id='s'+str(generation)+'-'+str(poll),watcher_observed_at=stamp,
        read_started_at=stamp,read_finished_at=stamp,sequence_basis='POLL',snapshot_atomic=False,
        levels=[dict(Level=1,AskPrice=101,BidPrice=100,AskQty=0,BidQty=None,read_at=stamp)])

def run(mode='normal',n=24,native=False):
    if native and os.name!='nt':return dict(native_ps51='NOT_VERIFIED',production='P0_BLOCKED')
    faults={'queue_full':h.FAULT_HOLD,'partial':h.FAULT_WRITE_INFLIGHT,
        'before_replace':h.FAULT_BEFORE_REPLACE,'after_replace':h.FAULT_AFTER_REPLACE,
        'permission':h.FAULT_PERMISSION}
    with tempfile.TemporaryDirectory() as root:
        if mode=='delay':Path(root,'delay.flag').touch()
        s=start(root,faults.get(mode,0))
        if s.status!='STARTED':raise RuntimeError(s.reason)
        gen=s._generation;sid='native-'+str(gen);ledger=Ledger(Path(root,'ledger'),sid,gen)
        expected={};samples=[];timings=[];readbacks=[];latencies=[];first_readback=set();process=None;reader=None;err=[];messages=queue.Queue()
        consumed=set();worker_events=[];overlap=False;ready={};cold=[];checkpoints=[];partial_killed=False
        path=Path(root,REL);audit=Path(root,'worker-evidence.jsonl')
        def import_worker():
            nonlocal overlap
            for e in complete_lines(audit):
                identity=digest(e)
                if identity in consumed:continue
                poll=e['poll_seq']
                if poll not in expected:continue # Receipt missing: never invent QUEUED.
                if e['session_id']!=sid or e['generation']!=gen or e['payload_identity']!=digest(expected[poll]):
                    raise ValueError('WORKER_EVIDENCE_CONFLICT')
                consumed.add(identity);worker_events.append(e)
                if len(samples)<n:overlap=True
                # Only an actual negative Writer result certifies post-queue refusal.
                if e['transition'] not in {'APPENDED','REPLAY'}:
                    ledger.add(poll_seq=poll,payload_identity=e['payload_identity'],stage='REJECTED_POST_QUEUE',
                        observed_at=now(),reason_code='WRITER_'+e['transition'],source_digest=identity)
        def verify():
            if not path.exists():return
            raw=path.read_bytes()
            if not raw.endswith(b'\n'):raise ValueError('PARTIAL_PUBLISHED_JSONL')
            rows=[json.loads(l) for l in raw.splitlines()]
            # A persisted row without receipt is retained as orphan evidence, not fabricated acceptance.
            if any(r['poll_seq'] not in expected for r in rows):return
            t=time.perf_counter()
            observed=now()
            try:ledger.verify_readback(raw,expected,observed,source_session=sid,source_generation=gen)
            except ValueError as e:
                if mode=='receipt_loss' and str(e)=='QUEUE_EVIDENCE_REQUIRED':return
                raise
            for row in rows:
                poll=row['poll_seq']
                if poll in first_readback:continue
                receipt=next(e for e in samples if e['poll_seq']==poll and e['state']=='ACCEPTED')
                elapsed=(datetime.fromisoformat(observed)-datetime.fromisoformat(receipt['observed_at'])).total_seconds()*1000
                latencies.append(elapsed);first_readback.add(poll)
            readbacks.append((time.perf_counter()-t)*1000)
        def receive(e):
            nonlocal partial_killed
            blob=base64.b64decode(e['record']);assert len(blob)==2048
            row=expected_record(unpack_capture(blob));poll=e['poll_seq'];expected[poll]=row
            if e['generation']!=gen or e['session_id']!=sid:raise ValueError('RECEIPT_GENERATION')
            samples.append(e)
            ledger.add(poll_seq=poll,payload_identity=digest(row),stage='UNKNOWN_PENDING' if mode=='receipt_loss' and len(samples)==1 else 'QUEUED' if e['state']=='ACCEPTED' else 'DROPPED_PRE_QUEUE',
                observed_at=e['observed_at'],reason_code=e['reason'],source_digest=digest(e))
            if mode=='receipt_loss' and len(samples)==1:
                assert not any(x['stage']=='QUEUED' for x in ledger.events())
            if mode in {'partial','before_replace','after_replace'} and not partial_killed:
                deadline=time.monotonic()+3
                wanted={'partial':'IO_INFLIGHT','before_replace':'BEFORE_REPLACE','after_replace':'AFTER_REPLACE'}[mode]
                while h._read_reason(s._shm.buf)!=wanted and time.monotonic()<deadline:time.sleep(.002)
                if h._read_reason(s._shm.buf)!=wanted:raise RuntimeError('FAULT_NOT_REACHED')
                s._process.kill();s._process.join(3);partial_killed=True
            if mode=='worker_kill' and len(samples)==2:s._process.kill();s._process.join(3)
            if mode=='kill' and len(samples)==2:s.trip_kill_switch()
            if mode=='stop' and len(samples)==2:
                h._store(s._shm.buf,h._OFF_FLAGS,h._load(s._shm.buf,h._OFF_FLAGS)|h._FLAG_STOP)
            import_worker();verify()
        try:
            if native:
                t=time.perf_counter()
                process=subprocess.Popen(['powershell.exe','-NoProfile','-File',str(ROOT/'tests/ms2_concurrent_producer.ps1'),
                    '-MapName',s.map_name,'-Generation',str(gen),'-N',str(n),'-Mode',mode],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
                def drain():
                    try:
                        for line in process.stdout:messages.put(json.loads(line))
                    except Exception as e:err.append(repr(e))
                reader=threading.Thread(target=drain,daemon=True);reader.start()
                ready=messages.get(timeout=30);assert ready['kind']=='ready';cold=[(time.perf_counter()-t)*1000]
                if mode=='gate_busy':struct.pack_into('<I',s._shm.buf,192,1)
                process.stdin.write('GO\n');process.stdin.flush()
                while True:
                    e=messages.get(timeout=30)
                    if e['kind']=='done':break
                    receive(e)
                    if mode=='producer_kill' and len(samples)==2:
                        process.kill();break
                    if mode=='gate_busy':struct.pack_into('<I',s._shm.buf,192,0)
                    process.stdin.write('NEXT\n');process.stdin.flush()
                process.wait(timeout=5)
                if (process.returncode and mode!='producer_kill') or err:raise RuntimeError(str(err)+process.stderr.read())
            else:
                if mode=='gate_busy':struct.pack_into('<I',s._shm.buf,192,1)
                for i in range(1,n+1):
                    poll=1 if mode=='duplicate' else i;t=time.perf_counter();c=synthetic(poll,gen,mode=='duplicate')
                    capture_ms=(time.perf_counter()-t)*1000;t1=time.perf_counter();packed=pack_capture(c)
                    packing_ms=(time.perf_counter()-t1)*1000
                    if not packed['ok']:raise ValueError(packed['reason'])
                    t1=time.perf_counter();r=s.publish_bytes(packed['record'])
                    submit_ms=(time.perf_counter()-t1)*1000
                    receive(dict(kind='receipt',session_id=sid,generation=gen,poll_seq=poll,attempt=i,
                        state=r['status'],reason=r['reason'],observed_at=now(),record=base64.b64encode(packed['record']).decode(),
                        capture_ms=capture_ms,packing_ms=packing_ms,submit_ms=submit_ms,full_ms=(time.perf_counter()-t)*1000))
                    if mode=='gate_busy':struct.pack_into('<I',s._shm.buf,192,0)
                    if mode!='queue_full':time.sleep(.005)
            # Bounded observation window; missing reports retain UNKNOWN, never DROP.
            end=time.monotonic()+3
            while time.monotonic()<end:
                import_worker();verify()
                accepted=sum(e['state']=='ACCEPTED' for e in samples)
                if len(worker_events)>=accepted or not s._process.is_alive() or mode=='queue_full':break
                time.sleep(.01)
            import_worker();verify()
            t=time.perf_counter();report=ledger.checkpoint(now(),window_ended=True);checkpoints.append((time.perf_counter()-t)*1000)
            states=dict(Counter(p['evidence_status'] for p in report['polls']))
            pending=ledger.reconcile(report['as_of'])
            assert all(p['close_state']=='NOT_CLOSED' for p in report['polls'])
            if mode=='normal':
                assert states.get('PERSISTED_VERIFIED',0)==sum(e['state']=='ACCEPTED' for e in samples), json.dumps(dict(states=states,worker=[{k:e[k] for k in ('poll_seq','transition','reasons')} for e in worker_events],metrics=s.metrics(),reason=h._read_reason(s._shm.buf)))
                assert overlap,'NO_CONCURRENT_COMPLETION'
            if mode in {'partial','before_replace'}:assert states.get('PERSISTED_VERIFIED',0)==0
            if mode=='after_replace':assert states.get('PERSISTED_VERIFIED',0)==1
            if mode=='receipt_loss':assert report['polls'][0]['evidence_status']=='UNKNOWN_TERMINAL'
            if mode=='permission':assert states.get('REJECTED_POST_QUEUE',0)>0
            if mode=='queue_full':assert states.get('UNKNOWN_TERMINAL',0)>0 and states.get('DROPPED_PRE_QUEUE',0)>0
            if mode=='duplicate':assert states.get('PERSISTED_VERIFIED',0)==1
            # Actual Bridge restart creates a new generation and never replays old IPC.
            prior_bytes=path.read_bytes() if path.exists() else None
            stopped=s.stop(.1)
            assert stopped['worker_exit_verified']
            restarted=start(root)
            try:
                assert restarted.status=='STARTED'
                assert restarted._generation!=gen
                time.sleep(.02)
                assert restarted.metrics()['queued']==0 and restarted.metrics()['durable']==0
                assert (path.read_bytes() if path.exists() else None)==prior_bytes
            finally:restarted.stop(.1)
            # Replay immutable checkpoint deterministically; corruption of cache cannot rewrite evidence.
            checkpoint=ledger.path.with_suffix('.checkpoint.json');checkpoint.write_bytes(b'{broken')
            assert ledger.checkpoint(report['as_of'],window_ended=True)==report
            # Different generation cannot import this source even if poll number matches.
            other=Ledger(Path(root,'ledger'),'next',gen+1)
            try:
                if path.exists():
                    try:other.verify_readback(path.read_bytes(),expected,now(),source_session=sid,source_generation=gen)
                    except ValueError as e:assert str(e)=='STALE_GENERATION'
                    else:raise AssertionError('STALE_REPLAY_ACCEPTED')
                assert other.reconcile(now())['polls']==[]
            finally:other.close()
            cohorts={}
            for label,group in [('steady_ACCEPTED',[e for e in samples[1:] if e['state']=='ACCEPTED']),
                ('steady_DROP',[e for e in samples[1:] if e['state']!='ACCEPTED']),
                ('GATE_BUSY',[e for e in samples if e['reason']=='PRODUCER_BUSY']),('first_submit',samples[:1])]:
                cohorts[label]={key:stats([e[key] for e in group]) for key in ('capture_ms','packing_ms','submit_ms','full_ms')}
            return dict(mode=mode,producer='Native_PS5.1' if native else 'Python_protocol_fixture',ps=ready.get('ps'),
                attempts=len(samples),queued=sum(e['state']=='ACCEPTED' for e in samples),
                drops=sum(e['state']!='ACCEPTED' for e in samples),states=states,concurrent_completion_observed=overlap,
                close_state='NOT_CLOSED',cold_start=stats(cold),first_warmup=stats([ready['warmup_ms']] if ready else []),
                cohorts=cohorts,Worker_processing=stats([e['worker_ms'] for e in worker_events]),
                Writer_fsync=stats([v for e in worker_events for v in e['fsync_ms']]),
                receipt_to_verified_readback_upper_bound=stats(latencies),restart_new_generation_no_replay=True,
                verified_readback=stats(readbacks),ledger_checkpoint=stats(checkpoints),
                receipt_tail='NOT_CLOSED',five_ms='NOT_MET',production='P0_BLOCKED',eligible_observed_n=0,
                instrumentation='receipt ACK and worker audit fsync add unmeasured pacing; no throughput or WCET guarantee')
        finally:
            if process is not None:
                if process.poll() is None:process.kill();process.wait(timeout=5)
                if reader:reader.join(3)
                for f in (process.stdin,process.stdout,process.stderr):f.close()
            if s._shm is not None:struct.pack_into('<I',s._shm.buf,192,0)
            s.stop(.1);ledger.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='concurrent372.json');a=p.parse_args()
    modes=('normal','delay','queue_full','gate_busy','permission','partial','before_replace','after_replace','worker_kill','kill','stop','duplicate','receipt_loss')
    if os.name=='nt':modes=(*modes,'producer_kill')
    results=[run(m,n=100 if m in {'normal','delay'} else 16,native=os.name=='nt') for m in modes]
    Path(a.output).write_text(json.dumps(results,indent=2));print(json.dumps(results))
if __name__=='__main__':main()
