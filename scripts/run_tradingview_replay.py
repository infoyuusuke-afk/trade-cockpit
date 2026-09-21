#!/usr/bin/env python3
"""Run a TradingView Replay CSV through the research-only 15s pipeline."""
import argparse,csv,json
from pathlib import Path
from scripts.time_utils import parse_market_ts
from scripts.tradingview_source_router import route_tradingview_data
from scripts.routed_research_backtest import run_routed_backtest

ALIASES={"timestamp":("time","timestamp","datetime","date"),"open":("open",),"high":("high",),"low":("low",),"close":("close",),"volume":("volume","vol")}

def _keymap(fieldnames):
    norm={str(x).strip().lower():x for x in fieldnames or []}; out={}
    for target,aliases in ALIASES.items():
        hit=next((norm[a] for a in aliases if a in norm),None)
        if hit is None: raise ValueError("MISSING_REPLAY_COLUMN:"+target)
        out[target]=hit
    return out

def load_replay_csv(path,symbol="TSE:285A",timeframe="15S"):
    rows=[]
    with Path(path).open(encoding="utf-8-sig",newline="") as fh:
        reader=csv.DictReader(fh); km=_keymap(reader.fieldnames)
        for r in reader:
            ts=parse_market_ts(r[km["timestamp"]])
            o,h,l,c=[float(r[km[k]]) for k in ("open","high","low","close")]
            v=float(r[km["volume"]])
            if h<max(o,c,l) or l>min(o,c,h): raise ValueError("INVALID_OHLC")
            if v<0: raise ValueError("INVALID_VOLUME")
            rows.append({"symbol":symbol,"market_date":ts.date().isoformat(),"timestamp":ts.isoformat(),
              "open":o,"high":h,"low":l,"close":c,"volume":v,"source":"TRADINGVIEW_REPLAY",
              "source_timeframe":timeframe,"source_timezone":"Asia/Tokyo","synthetic_timeframe":False,
              "research_only":True})
    if not rows: raise ValueError("EMPTY_REPLAY_CSV")
    for a,b in zip(rows,rows[1:]):
        if parse_market_ts(b["timestamp"])<=parse_market_ts(a["timestamp"]): raise ValueError("NON_INCREASING_TIMESTAMP")
    return rows

def run_replay(csv_path,out_dir,symbol="TSE:285A",cost_pct=0.10,prev_close=None):
    rows=load_replay_csv(csv_path,symbol)
    route=route_tradingview_data(required_timeframe="15S",replay_rows=rows)
    return run_routed_backtest(route,out_dir,cost_pct,prev_close)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("csv");ap.add_argument("--out-dir",default="data/replay_research_run")
    ap.add_argument("--symbol",default="TSE:285A");ap.add_argument("--cost-pct",type=float,default=0.10);ap.add_argument("--prev-close",type=float)
    a=ap.parse_args();trade,ev,manifest,summary=run_replay(a.csv,a.out_dir,a.symbol,a.cost_pct,a.prev_close)
    print(json.dumps({"trade_results":str(trade),"ev_results":str(ev),"manifest":str(manifest),"bars":summary["bar_count"],"trades":summary["trade_count"]},ensure_ascii=False))
if __name__=="__main__": main()
