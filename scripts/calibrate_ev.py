#!/usr/bin/env python3
"""Empirical EV calibration for AI Cockpit.

Input CSV columns:
strategy_key,pnl_pct
Optional: symbol,side,market_regime,entry_ts,exit_ts,cost_pct

Output contains only descriptive realized statistics. EV score is a calibrated
ranking score, not a probability. Small samples remain BLOCKED.
"""
import argparse,csv,json,math
from collections import defaultdict
from pathlib import Path
from datetime import datetime,timezone

MIN_N=30
MIN_PF=1.10

def max_drawdown(xs):
    equity=peak=0.0; mdd=0.0
    for x in xs:
        equity+=x; peak=max(peak,equity); mdd=min(mdd,equity-peak)
    return mdd

def stats(vals):
    n=len(vals); wins=[x for x in vals if x>0]; losses=[x for x in vals if x<0]
    gp=sum(wins); gl=-sum(losses)
    pf=(gp/gl) if gl>0 else (999.0 if gp>0 else 0.0)
    avg=sum(vals)/n if n else 0.0
    win=len(wins)/n if n else 0.0
    mdd=max_drawdown(vals)
    # Conservative score: rewards positive realized expectancy/PF/sample depth,
    # but does not represent a probability.
    sample=min(1.0,n/100.0)
    pf_term=max(0.0,min(1.0,(pf-1.0)/1.0))
    avg_term=max(0.0,min(1.0,avg/0.50))
    score=round(100*(0.35*sample+0.35*pf_term+0.30*avg_term))
    gate="PASS" if n>=MIN_N and pf>=MIN_PF and avg>0 else "BLOCK"
    reason="OK" if gate=="PASS" else ("INSUFFICIENT_SAMPLE" if n<MIN_N else "NON_POSITIVE_EMPIRICAL_EDGE")
    return {"ev_score":score,"sample_size":n,"win_rate":round(win,4),"profit_factor":round(pf,3),"avg_pl_pct":round(avg,4),"max_dd_pct":round(mdd,4),"risk_gate":gate,"risk_reason":reason}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--input",default="data/trade_results.csv");ap.add_argument("--output",default="data/ev_calibration.json");a=ap.parse_args()
    src=Path(a.input); groups=defaultdict(list)
    if src.exists():
        with src.open(encoding="utf-8-sig",newline="") as f:
            for r in csv.DictReader(f):
                try: groups[r["strategy_key"]].append(float(r["pnl_pct"])-float(r.get("cost_pct") or 0))
                except (KeyError,ValueError,TypeError): continue
    out={"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"score_is_probability":False,"minimum_sample":MIN_N,"groups":{k:stats(v) for k,v in groups.items()}}
    dst=Path(a.output);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"calibrated {len(groups)} strategy groups")
if __name__=="__main__": main()
