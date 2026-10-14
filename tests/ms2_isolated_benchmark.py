"""Synthetic condition-specific Python ingress latency, optionally PS5.1 launched.
No source data printed. Prepacking, drain waits, control and startup excluded
from offer timings and reported separately. No PS-native producer/WCET claim.
"""
import argparse
import json
import math
import os
import time
import tempfile
from multiprocessing import get_context
from scripts.ms2_bridge_record import pack_capture
from scripts.ms2_isolated_observation import OfflineLane, Ingress, READY, contract
from tests.test_ms2_ps_python_bridge import _board, RELATIVE


def stats(values):
    s=sorted(values)
    return dict(N=len(s), **({k:s[min(len(s)-1,math.ceil(len(s)*q)-1)]
                for k,q in [('p50_ms',.5),('p95_ms',.95),('p99_ms',.99),('max_ms',1)]} if s else {}))


def busy(stop):
    x=1
    while not stop.is_set():
        for _ in range(10000): x=(x*1664525+1013904223)&0xffffffff


def measure(ingress, fixtures, *, drain=False, lane=None):
    samples={'ACCEPTED':[], 'DROP':[]}; reasons={}; critical=[0,0,0]
    for poll,record in fixtures:
        for n in range(3): critical[n]+=1
        t=time.perf_counter_ns()
        status,reason=ingress.offer(record,poll,time.monotonic_ns())
        elapsed=(time.perf_counter_ns()-t)/1e6
        samples[status].append(elapsed); reasons[reason]=reasons.get(reason,0)+1
        if drain and status=='ACCEPTED':
            end=time.monotonic()+3
            while ingress.meta[0]!=ingress.meta[1] and time.monotonic()<end: time.sleep(.001)
            if ingress.meta[0]!=ingress.meta[1]: raise RuntimeError('DRAIN_NOT_PROVEN')
            # Outside timed section; avoid saturating downstream writer.
            if lane is not None:
                end=time.monotonic()+3
                while time.monotonic()<end:
                    m=lane.control('metrics'); w=m['writer']
                    finished=sum(w.get(k,0) for k in ('durable','duplicates','failures','fail_closed'))
                    if finished>=m['forwarded']: break
                    time.sleep(.001)
                else: raise RuntimeError('WRITER_COMPLETION_NOT_PROVEN '+str(m))
    return dict(accepted=stats(samples['ACCEPTED']),drop=stats(samples['DROP']),
                reasons=reasons,critical_mock_counts=critical,drop_audit=ingress.audit())


def run():
    report=dict(contract=contract(),runtime='Python fixed-copy ingress',
                ps_native_producer='NOT_VERIFIED',timer='perf_counter_ns incl call overhead',
                preparation='immutable canonical fixtures prepacked outside lane A',
                CPU_busy_processes=2,CPU_count=os.cpu_count(),CPU_saturation='NOT_VERIFIED',conditions={})
    ctx=get_context('spawn'); load=[]; stop=ctx.Event()
    with tempfile.TemporaryDirectory() as root:
        fixtures=[(n,pack_capture(_board(poll_seq=n))['record']) for n in range(1,301)]
        cold=[]
        for _ in range(3):
            t=time.perf_counter_ns();lane=OfflineLane(root,RELATIVE,enabled=True,require_authentication=False)
            cold.append((time.perf_counter_ns()-t)/1e6)
            if lane.status!='READY': raise RuntimeError(lane.status)
            report['priority']=lane.start_report
            lane.stop()
        report['cold_start']=stats(cold)
        lane=OfflineLane(root,RELATIVE,enabled=True,require_authentication=False)
        try:
            report['conditions']['steady']=measure(lane.ingress,fixtures,drain=True,lane=lane)
            report['steady_consumer']=lane.control('metrics')
            lane.stop()
            lane=OfflineLane(root,RELATIVE,enabled=True,require_authentication=False)
            for _ in range(2):
                p=ctx.Process(target=busy,args=(stop,));p.start();load.append(p)
            report['conditions']['CPU_contention']=measure(lane.ingress,fixtures,drain=True,lane=lane)
            stop.set()
            for p in load:p.join(5)
            lane.stop()
            lane=OfflineLane(root,RELATIVE,enabled=True,require_authentication=False)
            lane.control('hold');lane.control('metrics')
            report['conditions']['queue_full']=measure(lane.ingress,fixtures)
            lane.stop()
            lane=OfflineLane(root,RELATIVE,enabled=True,require_authentication=False)
            lane.control('kill_writer');lane.control('metrics')
            report['conditions']['writer_stopped']=measure(lane.ingress,fixtures)
            lane.stop()
            lane=OfflineLane(root,RELATIVE,enabled=True,require_authentication=False)
            report['conditions']['recovery']=measure(lane.ingress,fixtures,drain=True,lane=lane)
            lane.stop()
            # Controlled stale-consumer model, no foreign resource deletion.
            ingress=Ingress(ctx,777);ingress.meta[2]=READY;ingress.meta[3]=0
            report['conditions']['consumer_stale']=measure(ingress,fixtures)
        finally:
            lane.stop();stop.set()
            for p in load:
                p.join(3)
                if p.is_alive():p.kill();p.join(3)
    report['five_ms_max_guarantee']='NOT_ESTABLISHED'
    # Handle names/PIDs are not needed as public performance evidence.
    report['priority']={k:v for k,v in report['priority'].items() if k in ('priority','writer_priority')}
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    result=run();text=json.dumps(result,sort_keys=True)
    print('ISOLATED_LATENCY='+text)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(text+'\n',encoding='utf-8')
