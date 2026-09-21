#!/usr/bin/env python3
"""One-command research pipeline for TradingView 15s CSV. Research only.

Multi-day inputs are isolated by trading date: OR/VWAP state resets daily,
EOD exits cannot cross dates, and prior close is context only for the next day.
"""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from scripts.backtest_15s import load_bars, backtest_or_breakout, backtest_or5_vwap
from scripts.analyze_ev_features import analyze

FIELDS=["strategy_key","entry_ts","exit_ts","side","entry","exit","gross_pnl_pct","cost_pct","net_pnl_pct","pnl_pct","exit_reason",
"volume_ratio_20","bar_turnover","vwap_deviation_pct","or5_width_pct","intraday_range_pct","gap_pct",
"nikkei_return_pct","topix_return_pct","futures_return_pct"]

FORMATS=("%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S","%Y/%m/%d %H:%M:%S")

def parse_ts(ts):
    s=str(ts).strip()
    for fmt in FORMATS:
        try:
            return datetime.strptime(s[:19],fmt)
        except ValueError:
            pass
    raise ValueError("unparseable timestamp: "+s)

def validate_input(path):
    p=Path(path)
    if not p.exists(): raise FileNotFoundError(p)
    with p.open(encoding="utf-8-sig",newline="") as fh:
        r=csv.reader(fh); header=next(r,[])
    required={"time","open","high","low","close","volume"}
    missing=required-set(header)
    if missing: raise ValueError("missing columns: "+",".join(sorted(missing)))

def split_sessions(rows):
    if not rows: return []
    stamped=[(parse_ts(r["ts"]),r) for r in rows]
    stamped.sort(key=lambda x:x[0])
    seen=set(); sessions=[]; current=[]; day=None
    for dt,r in stamped:
        if dt in seen: raise ValueError("duplicate timestamp: "+str(r["ts"]))
        seen.add(dt)
        d=dt.date().isoformat()
        if day is not None and d!=day:
            sessions.append((day,current)); current=[]
        day=d; current.append(r)
    if current: sessions.append((day,current))
    return sessions

def run(input_csv,out_dir,cost_pct=0.10,prev_close=None):
    validate_input(input_csv); rows=load_bars(input_csv)
    sessions=split_sessions(rows)
    if not sessions: raise ValueError("no sessions")
    trades=[]; prior_close=prev_close; usable=0
    for day,session in sessions:
        if len(session)>=62:
            usable+=1
            for side in ("LONG","SHORT"):
                trades += backtest_or_breakout(session,side,cost_pct,prev_close=prior_close)
                trades += backtest_or5_vwap(session,side,cost_pct,prev_close=prior_close)
        prior_close=session[-1]["close"] if session else prior_close
    if usable==0: raise ValueError("no session has at least 62 x 15s bars")
    out=Path(out_dir); out.mkdir(parents=True,exist_ok=True)
    trade_csv=out/"trade_results.csv"
    with trade_csv.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS,extrasaction="ignore"); w.writeheader(); w.writerows(trades)
    ev={"schema_version":1,"input_file":Path(input_csv).name,"bar_count":len(rows),"trade_count":len(trades),
        "cost_pct":cost_pct,"session_count":len(sessions),"usable_session_count":usable,"feature_groups":analyze(trade_csv)}
    ev_path=out/"ev_feature_buckets.json"; ev_path.write_text(json.dumps(ev,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return trade_csv,ev_path,ev

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("csv"); ap.add_argument("--out-dir",default="data/research_run")
    ap.add_argument("--cost-pct",type=float,default=0.10); ap.add_argument("--prev-close",type=float); a=ap.parse_args()
    trade,ev,summary=run(a.csv,a.out_dir,a.cost_pct,a.prev_close)
    print(json.dumps({"trade_results":str(trade),"ev_results":str(ev),"bars":summary["bar_count"],"trades":summary["trade_count"]},ensure_ascii=False))
if __name__=="__main__": main()
