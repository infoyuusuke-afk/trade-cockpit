"""Native PS5.1 synthetic micro cohorts + unchanged Writer completion/readback.
No live process. Raw synthetic payload is consumed privately, never reported.
IPC fixture drains records without disk; Writer is benchmarked off the poll path.
This is NOT a native Watcher-to-production pipeline or a 5ms guarantee.
"""
import argparse
import base64
from collections import Counter
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time
from scripts import ms2_ipc_integrity as ipc
from scripts.ms2_ps_python_bridge import stamp_header,SHM_SIZE,SLOT_BASE,RECORD_SIZE
from scripts.ms2_bridge_record import unpack_capture
from scripts.ms2_offline_observation_writer import record_captured_observation
from scripts.ms2_poll_reconciliation import Ledger,digest,expected_record
from tests.ms2_native_drop_benchmark import stats

ROOT=Path(__file__).resolve().parents[1]
def now():return datetime.now(timezone.utc).isoformat()

def run(mode,n=100,contention=False):
    if os.name!='nt':return dict(native_ps51='NOT_VERIFIED',five_ms='NOT_MET',production='P0_BLOCKED')
    import uuid,sys
    generation=time.time_ns()//1000
    shm=ipc.create_mapping('b'+uuid.uuid4().hex[:11],SHM_SIZE)
    cpu=[];process=None;stop=threading.Event();reader=None;received=[];output=[];drain_errors=[]
    try:
        shm.buf[:]=b'\0'*SHM_SIZE;stamp_header(shm.buf,generation)
        def drain():
            while not stop.is_set():
                if mode=='accepted' and ipc.acquire(shm.buf):
                    try:
                        write,read=ipc.validate_header(shm.buf,generation)
                        while read<write:
                            blob=ipc.read_slot(shm.buf,generation,read)
                            if unpack_capture(blob)['observation_id']!='latency-warm':received.append(blob)
                            read+=1
                            struct.pack_into('<Q',shm.buf,8,read)
                    except Exception as e:drain_errors.append(type(e).__name__);return
                    finally:ipc.release(shm.buf)
                time.sleep(.001)
        drainer=threading.Thread(target=drain,daemon=True);drainer.start()
        if contention:
            for _ in range(2):cpu.append(subprocess.Popen([sys.executable,'-c','while True: pass']))
        cold=time.perf_counter()
        process=subprocess.Popen(['powershell.exe','-NoProfile','-File',str(ROOT/'tests/ms2_poll_latency_producer.ps1'),
            '-MapName',shm.name,'-Mode',mode,'-N',str(n)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        reader=threading.Thread(target=lambda:output.append(process.communicate()),daemon=True);reader.start()
        deadline=time.monotonic()+40
        while struct.unpack_from('<Q',shm.buf,120)[0]!=1:
            if process.poll() is not None:
                reader.join(3)
                raise RuntimeError('NATIVE_START_FAILED: '+(output[0][1] if output else 'NO_OUTPUT'))
            if time.monotonic()>deadline:raise RuntimeError('NATIVE_START_DEADLINE')
            time.sleep(.001)
        cold_ms=(time.perf_counter()-cold)*1000
        warm_deadline=time.monotonic()+3
        while struct.unpack_from('<Q',shm.buf,8)[0] < struct.unpack_from('<Q',shm.buf,0)[0]:
            if mode!='accepted':
                # Consume the single warmup record for DROP/GATE fixtures.
                if ipc.acquire(shm.buf):
                    try:struct.pack_into('<Q',shm.buf,8,struct.unpack_from('<Q',shm.buf,0)[0])
                    finally:ipc.release(shm.buf)
            if time.monotonic()>warm_deadline:raise RuntimeError('WARMUP_DRAIN')
            time.sleep(.001)
        # Reset fixture indices only after both producers are quiescent.
        struct.pack_into('<QQ',shm.buf,0,0,0)
        struct.pack_into('<Q',shm.buf,120,2)
        reader.join(40)
        if reader.is_alive():raise RuntimeError('NATIVE_DEADLINE')
        stdout,stderr=output[0]
        if process.returncode:raise RuntimeError(stderr)
        aggregate=json.loads(stdout);time.sleep(.02);stop.set();drainer.join(3)
        if drain_errors:raise RuntimeError(str(drain_errors))
        samples=aggregate['samples'];assert len(samples)==n
        accepted=[s for s in samples if s['state']=='ACCEPTED']
        drops=[s for s in samples if s['state']!='ACCEPTED']
        if mode=='gate_busy':assert all(s['reason']=='PRODUCER_BUSY' for s in samples)
        if mode=='drop':assert all(s['reason']=='DROP_NEWEST' for s in samples)
        assert len(received)==len(accepted)
        writer_times=[];checkpoint_times=[];expected={};states=[]
        with tempfile.TemporaryDirectory() as tmp:
            ledger=Ledger(Path(tmp)/'audit','native',generation)
            try:
                for s in samples:
                    row=expected_record(unpack_capture(base64.b64decode(s['record'])))
                    expected[s['poll_seq']]=row
                    ledger.add(poll_seq=s['poll_seq'],payload_identity=digest(row),
                        stage='QUEUED' if s['state']=='ACCEPTED' else 'DROPPED_PRE_QUEUE',
                        observed_at=s['observed_at'],reason_code=s['reason'],source_digest=digest({k:v for k,v in s.items() if k!='record'}))
                for blob in received:
                    capture=unpack_capture(blob);start=time.perf_counter()
                    report=record_captured_observation(tmp,'data/private/ms2_sidecar/native370.jsonl',capture,enabled=True)
                    if report['transition']!='APPENDED':raise RuntimeError('WRITER_NOT_APPENDED')
                    raw=Path(tmp,'data/private/ms2_sidecar/native370.jsonl').read_bytes()
                    ledger.verify_readback(raw,expected,now(),source_session='native',source_generation=generation)
                    writer_times.append((time.perf_counter()-start)*1000)
                for _ in range(10):
                    start=time.perf_counter();r=ledger.checkpoint(now(),window_ended=True)
                    checkpoint_times.append((time.perf_counter()-start)*1000)
                states=dict(Counter(p['evidence_status'] for p in r['polls']))
                assert states.get('PERSISTED_VERIFIED',0)==len(accepted)
            finally:ledger.close()
        cohorts={}
        for name,group in [('steady_ACCEPTED',accepted),('steady_DROP',drops if mode!='gate_busy' else []),('GATE_BUSY',drops if mode=='gate_busy' else [])]:
            cohorts[name]={key:stats([s[key] for s in group]) for key in ('mock_ms','capture_ms','packing_ms','submit_ms','full_ms')}
        return dict(mode=mode,contention=contention,cpu_processes=len(cpu),cpu_saturation='NOT_VERIFIED',ps=aggregate['ps'],
            cold_start=stats([cold_ms]),first_warmup=stats([aggregate['first_warmup_ms']]),cohorts=cohorts,
            Writer_save_and_verified_readback=stats(writer_times),ledger_checkpoint=stats(checkpoint_times),
            reconciliation=states,close_state='NOT_CLOSED',mock_counts=aggregate['mock_counts'],
            five_ms='NOT_MET',production='P0_BLOCKED',native_pipeline='MICRO_FIXTURE_NOT_LIVE',
            same_user_auth='SAME_USER_AUTH_UNRESOLVED',eligible_observed_n=0)
    finally:
        stop.set()
        if process is not None and process.poll() is None:process.kill();process.wait(timeout=5)
        if reader is not None:reader.join(5)
        for p in cpu:p.kill();p.wait(timeout=5)
        ipc.close_generation(generation);shm.close()
        if os.name!='nt':shm.unlink()

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='poll-latency.json');args=p.parse_args()
    results=[run(mode,contention=busy) for busy in (False,True) for mode in ('accepted','drop','gate_busy')] if os.name=='nt' else [run('accepted')]
    Path(args.output).write_text(json.dumps(results,indent=2));print(json.dumps(results))
if __name__=='__main__':main()
