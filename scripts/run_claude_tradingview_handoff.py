#!/usr/bin/env python3
"""Research-only Claude -> TradingView MCP handoff runner."""
import argparse,csv,hashlib,json
from pathlib import Path
from scripts.tradingview_source_router import route_tradingview_data
from scripts.routed_research_backtest import run_routed_backtest

def run_handoff(payload_path,out_dir,required_timeframe="15S",cost_pct=0.10,prev_close=None,required_symbol="TSE:285A",required_timezone="Asia/Tokyo"):
    src=Path(payload_path);raw=src.read_bytes();payload=json.loads(raw.decode("utf-8-sig"))
    meta=payload.get("meta") or {}
    bars=payload.get("bars") if isinstance(payload.get("bars"),list) else []
    input_sha256=hashlib.sha256(raw).hexdigest()
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    receipt={"input_file":str(src),"input_sha256":input_sha256,"actual_symbol":meta.get("symbol"),
      "actual_timeframe":meta.get("timeframe"),"actual_timezone":meta.get("timezone"),"retrieved_at":meta.get("retrieved_at"),
      "raw_bar_count":len(bars),"first_raw_timestamp":bars[0].get("timestamp") if bars else None,
      "last_raw_timestamp":bars[-1].get("timestamp") if bars else None,
      "required_symbol":required_symbol,"required_timezone":required_timezone,
      "required_timeframe":required_timeframe,"research_only":True,"auto_execute":False}
    rp=out/"claude_handoff_receipt.json"
    if meta.get("symbol")!=required_symbol:
        receipt.update({"handoff_status":"REJECTED_IDENTITY","rejection_reason":"CLAUDE_HANDOFF_SYMBOL_MISMATCH","promotion_eligible":False})
        rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        raise ValueError("CLAUDE_HANDOFF_SYMBOL_MISMATCH:required=%s actual=%s"%(required_symbol,meta.get("symbol")))
    if meta.get("timezone")!=required_timezone:
        receipt.update({"handoff_status":"REJECTED_IDENTITY","rejection_reason":"CLAUDE_HANDOFF_TIMEZONE_MISMATCH","promotion_eligible":False})
        rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
        raise ValueError("CLAUDE_HANDOFF_TIMEZONE_MISMATCH:required=%s actual=%s"%(required_timezone,meta.get("timezone")))
    route=route_tradingview_data(required_timeframe=required_timeframe,mcp_payload=payload)
    receipt.update({"handoff_status":"ROUTED","route_status":route.get("status"),
      "selected_source":route.get("selected_source"),"mcp_error":route.get("mcp_error"),
      "promotion_eligible":bool(route.get("promotion_eligible",False)),"input_rows":len(route.get("rows") or []),
      "research_only":True,"auto_execute":False})
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if not route.get("rows"): raise ValueError("CLAUDE_HANDOFF_NOT_READY:"+str(route.get("status"))+":"+str(route.get("mcp_error")))
    trade,ev,manifest,summary=run_routed_backtest(route,out,cost_pct,prev_close)
    quality_path=Path(summary["session_quality_file"])
    with quality_path.open(encoding="utf-8",newline="") as fh: quality=list(csv.DictReader(fh))
    counts={k:sum(1 for r in quality if r.get("research_status")==k) for k in ("ACCEPT","REVIEW","EXCLUDE")}
    receipt.update({"session_count":len(quality),"session_status_counts":counts,
      "quality_file":str(quality_path),"promotion_session_count":counts["ACCEPT"]})
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return rp,trade,ev,manifest,summary

def main():
    ap=argparse.ArgumentParser();ap.add_argument("payload");ap.add_argument("--out-dir",default="data/claude_research_run")
    ap.add_argument("--timeframe",default="15S");ap.add_argument("--cost-pct",type=float,default=0.10);ap.add_argument("--prev-close",type=float)
    a=ap.parse_args();rp,trade,ev,manifest,summary=run_handoff(a.payload,a.out_dir,a.timeframe,a.cost_pct,a.prev_close)
    print(json.dumps({"receipt":str(rp),"trade_results":str(trade),"ev_results":str(ev),"manifest":str(manifest),
      "bars":summary["bar_count"],"trades":summary["trade_count"],"research_only":True,"auto_execute":False},ensure_ascii=False))
if __name__=="__main__":main()
