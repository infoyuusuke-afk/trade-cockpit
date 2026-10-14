"""Synthetic PS5.1 boundary, supervised evidence and separate existing Writer.
No market records are emitted; temporary private JSONL is inspected locally.
"""
import argparse
import ctypes
import json
import math
import os
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from scripts.ms2_drop_evidence import Evidence, recover
from scripts.ms2_ps_python_bridge import start_bridge
from scripts import ms2_nonblocking_handoff as h

ROOT=Path(__file__).resolve().parents[1]
REL='data/private/ms2_sidecar/native.jsonl'


def stats(values):
    values=sorted(values)
    if not values: return {'N':0}
    return dict(N=len(values),p50_ms=values[math.ceil(len(values)*.5)-1],
        p95_ms=values[math.ceil(len(values)*.95)-1],p99_ms=values[math.ceil(len(values)*.99)-1],max_ms=max(values))


def lower_worker(pid):
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.restype=ctypes.c_void_p
    k.SetPriorityClass.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=k.OpenProcess(0x200,False,pid)
    try: return 'LOWERED' if handle and k.SetPriorityClass(handle,0x4000) else 'NOT_VERIFIED'
    finally:
        if handle: k.CloseHandle(handle)


def run_case(mode='normal',n=100,pause='none'):
    if os.name!='nt': return {'native_ps51':'NOT_VERIFIED'}
    with tempfile.TemporaryDirectory() as tmp:
        cold=time.perf_counter()
        session=start_bridge(tmp,REL,enabled=True,fault=h.FAULT_HOLD if mode=='queue_full' else 0)
        cold_ms=(time.perf_counter()-cold)*1000
        if session.status!='STARTED': raise RuntimeError(session.reason)
        e=Evidence(tmp,session._generation)
        cpu=[]; process=None; native_cold_ms=None
        try:
            priority=lower_worker(session._process.pid)
            if mode=='cpu':
                for _ in range(2):
                    cpu.append(subprocess.Popen([__import__('sys').executable,'-c','while True: pass']))
            command=['powershell.exe','-NoProfile','-File',str(ROOT/'tests/ms2_native_drop_producer.ps1'),
                '-MapName',session.map_name,'-EvidenceName',e.shm.name,'-Generation',str(e.generation),
                '-N',str(n),'-Mode',mode,'-PauseAt',pause]
            ps_start=time.perf_counter()
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            # Drain stdout concurrently: Windows pipe capacity must not make
            # aggregate-only output block process exit after 100 samples.
            output=[]
            reader=threading.Thread(target=lambda:output.append(process.communicate()),daemon=True)
            reader.start()
            deadline=time.monotonic()+40; killed=False; checkpoint_times=[]
            while process.poll() is None:
                if struct.unpack_from('<q',e.shm.buf,40)[0]==1:
                    native_cold_ms=(time.perf_counter()-ps_start)*1000
                    if mode=='kill': struct.pack_into('<Q',session._shm.buf,32,1)
                    if mode=='gate_busy': struct.pack_into('<I',session._shm.buf,192,1)
                    if mode=='old_generation': struct.pack_into('<Q',session._shm.buf,112,session._generation+1)
                    if mode=='corrupt': session._shm.buf[180]=99
                    if mode=='writer_stopped': session._process.kill(); session._process.join(2)
                    struct.pack_into('<q',e.shm.buf,40,2)
                started=time.perf_counter(); e.checkpoint(); checkpoint_times.append((time.perf_counter()-started)*1000)
                # The second poll is in-flight, including after queue acceptance.
                target_version=4 if pause=='after_drop' else 3
                if pause!='none' and struct.unpack_from('<q',e.shm.buf,0)[0]==target_version:
                    process.kill(); killed=True
                if time.monotonic()>deadline:
                    process.kill(); raise RuntimeError('PS_DEADLINE')
                time.sleep(.01)
            reader.join(3)
            if reader.is_alive() or not output:raise RuntimeError('OUTPUT_DRAIN_DEADLINE')
            stdout,stderr=output[0]
            evidence=e.checkpoint('PRODUCER_CRASH' if killed else 'EXIT_0' if process.returncode==0 else 'PRODUCER_ERROR')
            if not killed and process.returncode: raise RuntimeError(stderr)
            aggregate=json.loads(stdout) if not killed else {}
            # This wait belongs to the supervisor, never the producer boundary.
            disk_wait=time.perf_counter(); end=time.monotonic()+3
            expected=evidence.get('snapshot',{}).get('counters',{}).get('ACCEPTED',{}).get('count',0)
            while session._process.is_alive() and session.metrics()['durable']<expected and time.monotonic()<end:
                time.sleep(.01)
            persisted=session.metrics()['durable']
            path=Path(tmp)/REL
            rows=[json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []
            for row in rows:
                assert row['snapshot_atomic'] is False and row['sequence_basis']=='POLL'
                assert row['available_at'] is None and row['levels'][0]['bid_qty'] is None
                assert row['levels'][0]['ask_qty']==0
            evidence=e.checkpoint(evidence['outcome'],downstream=dict(
                state='PERSISTED' if persisted else 'NOT_CLOSED', persisted=persisted,
                jsonl_reread=len(rows), accepted_lower_bound=expected,
                accepted_not_persisted=max(0,expected-persisted),
                gap_status='GAP_EVIDENCE' if expected!=persisted else 'NOT_CLOSED',
                tail='UNKNOWN' if killed else evidence['tail']))
            assert recover(e.path)==evidence
            result=dict(mode=mode,priority=priority,cold_start_ms=cold_ms,
                native_cold_start_ms=native_cold_ms,CPU_busy_processes=len(cpu),
                CPU_count=os.cpu_count(),CPU_saturation='NOT_VERIFIED',
                evidence=evidence,persisted=persisted,jsonl_reread=len(rows),
                persistence_wait_ms=(time.perf_counter()-disk_wait)*1000,
                checkpoint_disk=stats(checkpoint_times),ps=aggregate.get('ps'),
                attach=stats([aggregate['attach_ms']]) if aggregate else {'N':0},
                loop_spacing=stats(aggregate.get('loop_spacing_ms',[])),mock_counts=aggregate.get('mock_counts'),
                five_ms='NOT_MET',same_user_auth='SAME_USER_AUTH_UNRESOLVED',
                actual_market_n=0,production='P0_BLOCKED')
            for state in ('ACCEPTED','DROP'):
                samples=[s for s in aggregate.get('samples',[]) if s['state']==state]
                result[state]={key:stats([s[key] for s in samples]) for key in ('capture_ms','packing_ms','submit_ms','full_ms')}
            return result
        finally:
            if process is not None and process.poll() is None:
                process.kill();process.wait(timeout=3)
            for p in cpu: p.kill(); p.wait(timeout=3)
            struct.pack_into('<I',session._shm.buf,192,0)
            session.stop(.1); e.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='native-drop-latency.json');args=parser.parse_args()
    if os.name=='nt':
        results=[run_case(mode) for mode in ('normal','cpu','queue_full','gate_busy','not_ready','stale','invalid','stop','kill','writer_stopped')]
        for r in results:
            assert r['evidence']['snapshot']['total']==100
            assert r['mock_counts']==[100,100,100]
            assert r['ACCEPTED']['full_ms']['N']+r['DROP']['full_ms']['N']==100
            assert r['jsonl_reread']==r['persisted']
        print('NATIVE_COLD_START='+json.dumps(stats([r['native_cold_start_ms'] for r in results])))
    else: results=[dict(native_ps51='NOT_VERIFIED',production='P0_BLOCKED')]
    Path(args.output).write_text(json.dumps(results,indent=2))
    # Only aggregates; no payload, map names, paths, secrets or raw observations.
    print(json.dumps(results))

if __name__=='__main__':main()
