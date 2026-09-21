#!/usr/bin/env python3
"""Bridge routed TradingView CORE rows into the existing 15s research pipeline."""
import csv,json
from pathlib import Path
from scripts.run_research_pipeline import run

BT_FIELDS=("time","open","high","low","close","volume")
RESEARCH_READY_STATUSES=("READY","READY_FALLBACK","READY_UNCROSSCHECKED",
                         "READY_FALLBACK_UNCROSSCHECKED","REVIEW_NO_SOURCE_OVERLAP")

def write_backtest_input(rows,path):
    if not rows: raise ValueError("NO_ROUTED_ROWS")
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=BT_FIELDS);w.writeheader()
        for r in rows:
            w.writerow({"time":r["timestamp"],"open":r["open"],"high":r["high"],
                        "low":r["low"],"close":r["close"],"volume":r["volume"]})
    return path

def run_routed_backtest(route_result,out_dir,cost_pct=0.10,prev_close=None):
    status=route_result.get("status")
    if status not in RESEARCH_READY_STATUSES:
        raise ValueError("ROUTED_SOURCE_NOT_READY:"+str(status))
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    bt_input=write_backtest_input(route_result["rows"],out/"routed_15s_input.csv")
    trade,ev,summary=run(bt_input,out,cost_pct,prev_close)
    cross=route_result.get("crosscheck")
    manifest={"selected_source":route_result.get("selected_source"),
              "route_status":status,
              "mcp_error":route_result.get("mcp_error"),
              "replay_error":route_result.get("replay_error"),
              "promotion_eligible":bool(route_result.get("promotion_eligible",False)),
              "crosscheck_status":cross.get("status") if cross else None,
              "crosscheck_overlap_n":cross.get("overlap_n") if cross else None,
              "input_rows":len(route_result["rows"]),
              "trade_results":str(trade),"ev_results":str(ev),
              "research_only":True,"auto_execute":False}
    mp=out/"source_manifest.json"
    mp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return trade,ev,mp,summary
