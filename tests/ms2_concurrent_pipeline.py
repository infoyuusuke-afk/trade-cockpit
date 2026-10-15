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
import sys
import tempfile
import uuid
import threading
import time
from scripts import ms2_nonblocking_handoff as h
from scripts.ms2_ps_python_bridge import start_bridge, stamp_header, SHM_SIZE
from scripts import ms2_ipc_integrity as ipc
from scripts.ms2_bridge_record import pack_capture, unpack_capture
from scripts.ms2_poll_reconciliation import Ledger, canonical, digest, expected_record
from tests.ms2_native_drop_benchmark import stats
from scripts.ms2_native_latency_anatomy import diagnose

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


def _set_suspended(pid, suspended):
    """Synthetic fault: take the spawned Writer worker off-CPU, then resume it."""
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);ntdll=ctypes.WinDLL('ntdll')
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x0800,False,pid)  # PROCESS_SUSPEND_RESUME only
        if not handle:raise OSError('WORKER_SUSPEND_OPEN_FAILED')
        try:
            call=ntdll.NtSuspendProcess if suspended else ntdll.NtResumeProcess
            call.argtypes=[ctypes.c_void_p]
            if call(handle)!=0:raise OSError('WORKER_SUSPEND_FAILED')
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        import signal
        os.kill(pid,signal.SIGSTOP if suspended else signal.SIGCONT)


def _load_index(buf,offset):return struct.unpack_from('<Q',buf,offset)[0]


def _pause_loop(buf, pid, stop, pause_s=0.16, limit=10):
    """Issue #382 repro: pause the worker between two *separate* short gate holds.

    Suspend only inside a producer hold (the worker very likely sampled it
    busy), and resume preferably while a later hold is in progress. Holds stay
    short; only the worker's own scheduling has a gap. The gate itself is never touched here.
    """
    def gate():return struct.unpack_from('<I',buf,ipc.GATE)[0]
    def wait(cond,timeout):
        end=time.perf_counter()+timeout  # monotonic is ~15.6ms on Windows py3.12
        while time.perf_counter()<end:
            if cond():return True
        return False
    log=[]
    while not stop() and len(log)<limit:
        if not wait(lambda:gate()==1,0.2):continue
        # Heartbeat is too coarse to show one worker iteration (Python 3.12 on
        # Windows: monotonic ~15.6ms). Instead pause only inside a producer
        # hold: busy with an empty queue for 1ms without a gap. The worker
        # holds the gate only to claim a queued slot, so it cannot be the holder.
        end=time.perf_counter()+0.001;producer=True
        while time.perf_counter()<end:
            if gate()!=1 or _load_index(buf,h._OFF_WRITE)!=_load_index(buf,h._OFF_READ):producer=False;break
        if not producer:continue
        _set_suspended(pid,True);paused=time.perf_counter()
        try:
            time.sleep(pause_s)
            resumed_busy=wait(lambda:gate()==1,0.3)
        finally:_set_suspended(pid,False)
        log.append(dict(pause_ms=round((time.perf_counter()-paused)*1e3,3),resumed_while_gate_busy=bool(resumed_busy)))
        time.sleep(.05)
    return log


def _stutter_loop(pid, stop, off_s=0.033, on_s=0.002):
    """Issue #382 counterexample: the worker keeps running (heartbeat advances)
    but only gets ~2ms of CPU every ~35ms, so busy samples are 30-40ms apart."""
    cycles=0;ended='STOPPED'
    while not stop():
        try:_set_suspended(pid,True)
        except OSError:ended='WORKER_EXITED';break  # it failed closed and left
        try:time.sleep(off_s)
        finally:
            try:_set_suspended(pid,False)
            except OSError:ended='WORKER_EXITED'
        cycles+=1
        if ended!='STOPPED':break
        end=time.perf_counter()+on_s
        while time.perf_counter()<end:pass
    return [dict(stutter_cycles=cycles,off_ms=off_s*1e3,on_ms=on_s*1e3,ended=ended)]


def _pause_process_main(map_name, pid, stopfile, pattern='pause'):
    """Separate process so the spin is not starved by this harness's GIL."""
    from multiprocessing import shared_memory
    shm=shared_memory.SharedMemory(name=map_name)
    if os.name!='nt':
        from multiprocessing import resource_tracker
        resource_tracker.unregister(shm._name,'shared_memory')  # never unlink owner map
    stop=lambda:os.path.exists(stopfile)
    try:print(json.dumps(_stutter_loop(pid,stop) if pattern=='stutter' else _pause_loop(shm.buf,pid,stop)),flush=True)
    finally:shm.close()


def worker_pause_injector(session, done, log, root, pattern='pause'):
    stopfile=str(Path(root,'pause.'+pattern+'.stop'))
    child=subprocess.Popen([sys.executable,'-m','tests.ms2_concurrent_pipeline','--pause-map',session.map_name,
        '--pause-pid',str(session._process.pid),'--pause-stop',stopfile,'--pause-pattern',pattern],
        cwd=str(ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    done.wait()
    Path(stopfile).touch()
    try:out,err=child.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill();out,err=child.communicate()
    if child.returncode!=0:raise RuntimeError('PAUSE_INJECTOR_FAILED '+err[-500:])
    log.extend(json.loads(out.strip().splitlines()[-1]))


def _out_of_gate_retries(session, done, log, interval_s=0.025):
    """Another in-process submitter (existing HandoffSession.submit) retrying
    every ~25ms on the same mapping. Every try is refused at the busy gate but
    still bumps SUBMIT_COUNT outside the gate."""
    other=h.HandoffSession('STARTED','');other._shm=session._shm;other._generation=session._generation
    other._process=session._process
    seq=0
    while not done.wait(interval_s):
        seq+=1;before=h._load(session._shm.buf,h._OFF_SUBMIT_COUNT)
        r=other.submit(synthetic(10_000+seq,session._generation))
        log.append(dict(status=r['status'],reason=r['reason'],submit_count_moved=h._load(session._shm.buf,h._OFF_SUBMIT_COUNT)>before))


def hold_gate_while_stuttering(session, root, hold_s=0.6, stutter=True, retries=False):
    """A truly stuck gate: one real hold (>=300ms) while the live worker samples
    only every 30-40ms and/or another submitter keeps moving counters outside
    the gate. The worker must fail closed inside the hold."""
    buf=session._shm.buf
    if not ipc.acquire(buf):raise RuntimeError('STUCK_GATE_NOT_ACQUIRED')
    log=[];tries=[];done=threading.Event();held=time.perf_counter();detected_ms=None
    helpers=[]
    if stutter:helpers.append(threading.Thread(target=worker_pause_injector,args=(session,done,log,root,'stutter'),daemon=True))
    if retries:helpers.append(threading.Thread(target=_out_of_gate_retries,args=(session,done,tries),daemon=True))
    for t in helpers:t.start()
    try:
        hb0=h._load(buf,h._OFF_HEARTBEAT)
        while time.perf_counter()-held<hold_s:
            if detected_ms is None and h._read_reason(buf)=='IPC_GATE_ABANDONED':
                detected_ms=round((time.perf_counter()-held)*1e3,3)
            time.sleep(.001)
        heartbeat_advanced=h._load(buf,h._OFF_HEARTBEAT)>hb0 or detected_ms is not None
    finally:
        done.set()
        for t in helpers:t.join(15)
        ipc.release(buf)
    return dict(hold_ms=round((time.perf_counter()-held)*1e3,3),detected_ms=detected_ms,
        reason=h._read_reason(buf),kill=bool(h._load(buf,h._OFF_FLAGS)&h._FLAG_KILL),
        fail_closed=h._load(buf,h._OFF_FAIL_CLOSED),heartbeat_advanced=heartbeat_advanced,stutter=log,
        out_of_gate_retries=dict(Counter(t['reason'] for t in tries)),
        out_of_gate_submit_count_moves=sum(t['submit_count_moved'] for t in tries))


def normal_failure_evidence(states, samples, worker_events, session, producer, native):
    """Bounded, privacy-safe synthetic failure snapshot; no private record fields."""
    buf = session._shm.buf
    heartbeat_ns = h._load(buf, h._OFF_HEARTBEAT)
    heartbeat_age_ns = max(0, time.monotonic_ns() - heartbeat_ns) if heartbeat_ns else None
    holds = [float(e['gate_hold_ms']) for e in samples
             if e['state'] == 'ACCEPTED' and isinstance(e.get('gate_hold_ms'), (int, float))
             and 0 <= float(e['gate_hold_ms']) < 60000]
    return dict(
        boundary='SYNTHETIC_FIXTURE_ONLY',
        failure='NORMAL_RECEIPT_READBACK_MISMATCH',
        native=bool(native),
        accepted=sum(e['state'] == 'ACCEPTED' for e in samples),
        states=states,
        worker_transitions=dict(Counter(e['transition'] for e in worker_events)),
        # Reason codes only (no record fields) for any post-queue Writer refusal.
        worker_refusal_reasons=dict(Counter(r for e in worker_events if e['transition'] not in {'APPENDED','REPLAY'}
                                            for r in e.get('reasons') or [])),
        worker_alive=bool(session._process.is_alive()),
        worker_exitcode=session._process.exitcode,
        producer_exitcode=producer.poll() if producer is not None else None,
        gate_word=struct.unpack_from('<I', buf, ipc.GATE)[0],
        write_index=h._load(buf, h._OFF_WRITE),
        read_index=h._load(buf, h._OFF_READ),
        flags=h._load(buf, h._OFF_FLAGS),
        fail_closed_count=h._load(buf, h._OFF_FAIL_CLOSED),
        heartbeat_age_ms=round(heartbeat_age_ns / 1_000_000, 3) if heartbeat_age_ns is not None else None,
        gate_stall_threshold_ms=h.STALL_AFTER_NS / 1_000_000,
        reason=h._read_reason(buf),
        producer_gate_hold_max_ms=(round(max(holds), 3) if holds else None),
        producer_gate_hold_over_threshold=sum(v > h.STALL_AFTER_NS / 1_000_000 for v in holds),
        producer_gate_hold_measured_n=len(holds),
        mutex_abandonment_proven=False,
        production='P0_BLOCKED',
    )


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
        warm_map=None;warm_gen=gen+1
        pauses=[];pause_done=threading.Event();stuck=None
        injector=threading.Thread(target=worker_pause_injector,args=(s,pause_done,pauses,root),daemon=True)
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
                warm_map=ipc.create_mapping('b'+uuid.uuid4().hex[:11],SHM_SIZE)
                warm_map.buf[:]=b'\0'*SHM_SIZE;stamp_header(warm_map.buf,warm_gen)
                t=time.perf_counter()
                process=subprocess.Popen(['powershell.exe','-NoProfile','-File',str(ROOT/'tests/ms2_concurrent_producer.ps1'),
                    '-MapName',s.map_name,'-WarmMap',warm_map.name,'-Generation',str(gen),'-N',str(n),'-Mode',mode],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
                def drain():
                    try:
                        for line in process.stdout:messages.put(json.loads(line))
                    except Exception as e:err.append(repr(e))
                reader=threading.Thread(target=drain,daemon=True);reader.start()
                ready=messages.get(timeout=30);assert ready['kind']=='ready';cold=[(time.perf_counter()-t)*1000]
                if mode=='gate_busy':struct.pack_into('<I',s._shm.buf,192,1)
                if mode=='worker_pause':injector.start()
                if mode=='gate_stuck':stuck=hold_gate_while_stuttering(s,root)
                if mode=='gate_stuck_submit':stuck=hold_gate_while_stuttering(s,root,stutter=False,retries=True)
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
                if mode=='worker_pause':injector.start()
                if mode=='gate_stuck':stuck=hold_gate_while_stuttering(s,root)
                if mode=='gate_stuck_submit':stuck=hold_gate_while_stuttering(s,root,stutter=False,retries=True)
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
            pause_done.set()
            if injector.is_alive():injector.join(15)
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
            if mode=='gate_stuck_submit' and not stuck['out_of_gate_submit_count_moves']:
                raise AssertionError(json.dumps(dict(failure='NO_OUT_OF_GATE_UPDATE_EXERCISED',stuck=stuck),sort_keys=True))
            if mode in {'gate_stuck','gate_stuck_submit'}:
                # Fail closed inside the stuck hold; nothing after it may be accepted.
                if not(stuck['detected_ms'] is not None and stuck['kill'] and stuck['heartbeat_advanced']
                       and states.get('DROPPED_PRE_QUEUE',0)==len(samples)):
                    raise AssertionError(json.dumps(dict(failure='STUCK_GATE_NOT_FAIL_CLOSED',stuck=stuck,states=states),sort_keys=True))
            if mode in {'normal','worker_pause'}:
                if states.get('PERSISTED_VERIFIED',0)!=sum(e['state']=='ACCEPTED' for e in samples):
                    evidence=normal_failure_evidence(states,samples,worker_events,s,process,native)
                    if mode=='worker_pause':evidence.update(failure='WORKER_PAUSE_RECEIPT_READBACK_MISMATCH',injected_pauses=pauses)
                    raise AssertionError(json.dumps(evidence,sort_keys=True))
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
                assert restarted.status=='STARTED', restarted.reason
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
                prewarm='DISPOSABLE_IPC_NO_WRITER' if native and mode!='cold' else 'NONE',
                cohorts=cohorts,latency_anatomy=diagnose(samples),
                Worker_processing=stats([e['worker_ms'] for e in worker_events]),
                Writer_fsync=stats([v for e in worker_events for v in e['fsync_ms']]),
                receipt_to_verified_readback_upper_bound=stats(latencies),restart_new_generation_no_replay=True,
                verified_readback=stats(readbacks),ledger_checkpoint=stats(checkpoints),
                receipt_tail='NOT_CLOSED',five_ms='NOT_MET',production='P0_BLOCKED',eligible_observed_n=0,
                injected_pauses=pauses,stuck_gate=stuck,gate_hold_max_ms=max([float(e['gate_hold_ms']) for e in samples if isinstance(e.get('gate_hold_ms'),(int,float))],default=None),
                instrumentation='receipt ACK and worker audit fsync add unmeasured pacing; no throughput or WCET guarantee')
        finally:
            pause_done.set()
            if injector.is_alive():injector.join(2)
            if process is not None:
                if process.poll() is None:process.kill();process.wait(timeout=5)
                if reader:reader.join(3)
                for f in (process.stdin,process.stdout,process.stderr):f.close()
            if s._shm is not None:struct.pack_into('<I',s._shm.buf,192,0)
            s.stop(.1);ledger.close()
            if warm_map is not None:
                ipc.close_generation(warm_gen);warm_map.close()
                if os.name!='nt':warm_map.unlink()

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='concurrent372.json')
    p.add_argument('--pause-map');p.add_argument('--pause-pid',type=int);p.add_argument('--pause-stop')
    p.add_argument('--pause-pattern',default='pause');a=p.parse_args()
    if a.pause_map:return _pause_process_main(a.pause_map,a.pause_pid,a.pause_stop,a.pause_pattern)
    modes=('normal','worker_pause','gate_stuck','gate_stuck_submit','delay','queue_full','gate_busy','permission','partial','before_replace','after_replace','worker_kill','kill','stop','duplicate','receipt_loss')
    if os.name=='nt':modes=(*modes,'producer_kill','cold')
    results=[];failed=False
    for m in modes:
        try:r=run(m,n=100 if m in {'normal','worker_pause','delay'} else 16,native=os.name=='nt')
        except Exception as e:
            failed=True;r=dict(mode=m,status='FAIL',error=type(e).__name__,detail=str(e),production='P0_BLOCKED')
        results.append(r)
        Path(a.output).write_text(json.dumps(results,indent=2))
        print('CONCURRENT_CASE='+json.dumps(r),flush=True)
    if failed:raise RuntimeError('CONCURRENT_COHORT_FAILURES_RETAINED')
if __name__=='__main__':main()
