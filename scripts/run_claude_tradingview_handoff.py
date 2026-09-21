#!/usr/bin/env python3
"""Research-only Claude -> TradingView MCP handoff runner."""
import argparse,json
from pathlib import Path
from scripts.tradingview_source_router import route_tradingview_data
from scripts.routed_research_backtest import run_routed_backtest

def run_handoff(payload_path,out_dir,required_timeframe="15S",cost_pct=0.10,prev_close=None,required_symbol="TSE:285A",required_timezone="Asia/Tokyo"):
    src=Path(payload_path);payload=json.loads(src.read_text(encoding="utf-8-sig"))
    meta=payload.get("meta") or {}
    if meta.get("symbol")!=required_symbol: raise ValueError("CLAUDE_HANDOFF_SYMBOL_MISMATCH:required=%s actual=%s"%(required_symbol,meta.get("symbol")))
    if meta.get("timezone")!=required_timezone: raise ValueError("CLAUDE_HANDOFF_TIMEZONE_MISMATCH:required=%s actual=%s"%(required_timezone,meta.get("timezone")))
    route=route_tradingview_data(required_timeframe=required_timeframe,mcp_payload=payload)
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    receipt={"input_file":str(src),"required_symbol":required_symbol,"required_timezone":required_timezone,
      "required_timeframe":required_timeframe,"route_status":route.get("status"),
      "selected_source":route.get("selected_source"),"mcp_error":route.get("mcp_error"),
      "promotion_eligible":bool(route.get("promotion_eligible",False)),"input_rows":len(route.get("rows") or []),
      "research_only":True,"auto_execute":False}
    rp=out/"claude_handoff_receipt.json";rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not route.get("rows"): raise ValueError("CLAUDE_HANDOFF_NOT_READY:"+str(route.get("status"))+":"+str(route.get("mcp_error")))
    trade,ev,manifest,summary=run_routed_backtest(route,out,cost_pct,prev_close)
    return rp,trade,ev,manifest,summary

def main():
    ap=argparse.ArgumentParser();ap.add_argument("payload");ap.add_argument("--out-dir",default="data/claude_research_run")
    ap.add_argument("--timeframe",default="15S");ap.add_argument("--cost-pct",type=float,default=0.10);ap.add_argument("--prev-close",type=float)
    a=ap.parse_args();rp,trade,ev,manifest,summary=run_handoff(a.payload,a.out_dir,a.timeframe,a.cost_pct,a.prev_close)
    print(json.dumps({"receipt":str(rp),"trade_results":str(trade),"ev_results":str(ev),"manifest":str(manifest),
      "bars":summary["bar_count"],"trades":summary["trade_count"],"research_only":True,"auto_execute":False},ensure_ascii=False))
if __name__=="__main__":main()
