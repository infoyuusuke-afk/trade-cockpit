#!/usr/bin/env python3
"""One-command research pipeline for TradingView 15s CSV. Research only."""
import argparse,csv,json
from pathlib import Path
from scripts.backtest_15s import load_bars,backtest_or_breakout,backtest_or5_vwap
from scripts.analyze_ev_features import analyze

FIELDS=["strategy_key","entry_ts","exit_ts","side","entry","exit","pnl_pct","cost_pct","exit_reason",
"volume_ratio_20","bar_turnover","vwap_deviation_pct","or5_width_pct","intraday_range_pct","gap_pct",
"nikkei_return_pct","topix_return_pct","futures_return_pct"]

def validate_input(path):
    p=Path(path)
    if not p.exists(): raise FileNotFoundError(p)
    with p.open(encoding="utf-8-sig",newline="") as fh:
        r=csv.reader(fh); header=next(r,[])
    required={"time","open","high","low","close","volume"}
    missing=required-set(header)
    if missing: raise ValueError("missing columns: "+",".join(sorted(missing)))

def run(input_csv,out_dir,cost_pct=0.10,prev_close=None):
    validate_input(input_csv); rows=load_bars(input_csv)
    if len(rows)<62: raise ValueError("need at least 62 x 15s bars")
    trades=[]
    for side in ("LONG","SHORT"):
        trades += backtest_or_breakout(rows,side,cost_pct,prev_close=prev_close)
        trades += backtest_or5_vwap(rows,side,cost_pct,prev_close=prev_close)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    trade_csv=out/"trade_results.csv"
    with trade_csv.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=FIELDS,extrasaction="ignore");w.writeheader();w.writerows(trades)
    ev={"schema_version":1,"input_file":Path(input_csv).name,"bar_count":len(rows),"trade_count":len(trades),
        "cost_pct":cost_pct,"feature_groups":analyze(trade_csv)}
    ev_path=out/"ev_feature_buckets.json";ev_path.write_text(json.dumps(ev,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return trade_csv,ev_path,ev

def main():
    ap=argparse.ArgumentParser();ap.add_argument("csv");ap.add_argument("--out-dir",default="data/research_run")
    ap.add_argument("--cost-pct",type=float,default=0.10);ap.add_argument("--prev-close",type=float);a=ap.parse_args()
    trade,ev,summary=run(a.csv,a.out_dir,a.cost_pct,a.prev_close)
    print(json.dumps({"trade_results":str(trade),"ev_results":str(ev),"bars":summary["bar_count"],"trades":summary["trade_count"]},ensure_ascii=False))
if __name__=="__main__":main()
