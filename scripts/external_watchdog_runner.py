"""Local runner for the external heartbeat watchdog. No broker/order I/O."""
from __future__ import annotations
import argparse,json,time
from datetime import datetime
from pathlib import Path
from scripts.external_health_watchdog import evaluate
from scripts.watchdog_health_projection import project

def run_once(input_path, output_path, *, now, stale_after_seconds=15):
    try:
        snapshot=json.loads(Path(input_path).read_text(encoding="utf-8"))
    except Exception:
        snapshot={}
    decision=evaluate(snapshot,now=now,stale_after_seconds=stale_after_seconds)
    out=project(snapshot,decision,observed_at=now.isoformat())
    p=Path(output_path); p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+".tmp")
    tmp.write_text(json.dumps(out,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(p)
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True); ap.add_argument("--output",required=True)
    ap.add_argument("--interval-seconds",type=float,default=5); ap.add_argument("--stale-after-seconds",type=float,default=15)
    a=ap.parse_args()
    while True:
        run_once(a.input,a.output,now=datetime.now().astimezone(),stale_after_seconds=a.stale_after_seconds)
        time.sleep(a.interval_seconds)
if __name__=="__main__": main()
