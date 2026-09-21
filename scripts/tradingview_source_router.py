#!/usr/bin/env python3
"""Research-only TradingView source router with fail-closed provenance."""
from scripts.tradingview_mcp_adapter import adapt_mcp_payload,require_timeframe
from scripts.tradingview_source_crosscheck import crosscheck_sources
from scripts.time_utils import parse_market_ts

def _validate_replay(rows,required_timeframe):
    if not rows:return []
    out=[]
    for r in rows:
        if str(r.get("source_timeframe"))!=str(required_timeframe): raise ValueError("REPLAY_TIMEFRAME_MISMATCH")
        if r.get("source")!="TRADINGVIEW_REPLAY": raise ValueError("REPLAY_PROVENANCE_MISSING")
        ts=parse_market_ts(r["timestamp"])
        for k in ("open","high","low","close","volume"):
            if r.get(k) in (None,""): raise ValueError("REPLAY_MISSING_"+k.upper())
        o,h,l,c,v=[float(r[k]) for k in ("open","high","low","close","volume")]
        if h<max(o,c,l) or l>min(o,c,h): raise ValueError("REPLAY_INVALID_OHLC")
        if v<0: raise ValueError("REPLAY_INVALID_VOLUME")
        q=dict(r);q["timestamp"]=ts.isoformat();out.append(q)
    for a,b in zip(out,out[1:]):
        if parse_market_ts(b["timestamp"])<=parse_market_ts(a["timestamp"]): raise ValueError("REPLAY_NON_INCREASING_TIMESTAMP")
    return out

def route_tradingview_data(required_timeframe="15S",mcp_payload=None,replay_rows=None):
    replay_error=None
    try: replay_rows=_validate_replay(replay_rows or [],required_timeframe)
    except (ValueError,KeyError,TypeError) as e: replay_rows=[];replay_error=str(e)
    mcp_rows=[];mcp_error=None
    if mcp_payload is not None:
        try:mcp_rows=require_timeframe(adapt_mcp_payload(mcp_payload),required_timeframe)
        except ValueError as e:mcp_error=str(e)
    base={"mcp_error":mcp_error,"replay_error":replay_error,"research_only":True,"auto_execute":False}
    if mcp_rows and replay_rows:
        audit=crosscheck_sources(mcp_rows,replay_rows,required_timeframe)
        if audit["status"]=="MISMATCH":
            return {"status":"BLOCKED_SOURCE_MISMATCH","rows":[],"selected_source":None,"crosscheck":audit,**base}
        if audit["status"]=="NO_OVERLAP":
            return {"status":"REVIEW_NO_SOURCE_OVERLAP","rows":mcp_rows,"selected_source":"TRADINGVIEW_MCP","crosscheck":audit,"promotion_eligible":False,**base}
        return {"status":"READY","rows":mcp_rows,"selected_source":"TRADINGVIEW_MCP","crosscheck":audit,"promotion_eligible":True,**base}
    if mcp_rows:
        return {"status":"READY_UNCROSSCHECKED","rows":mcp_rows,"selected_source":"TRADINGVIEW_MCP","crosscheck":None,"promotion_eligible":False,**base}
    if replay_rows:
        return {"status":"READY_FALLBACK_UNCROSSCHECKED","rows":replay_rows,"selected_source":"TRADINGVIEW_REPLAY","crosscheck":None,"promotion_eligible":False,**base}
    return {"status":"NO_USABLE_SOURCE","rows":[],"selected_source":None,"crosscheck":None,"promotion_eligible":False,**base}
