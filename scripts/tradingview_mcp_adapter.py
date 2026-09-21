#!/usr/bin/env python3
"""TradingView MCP payload -> research CORE rows. Never synthesize lower timeframes."""
import math
from scripts.time_utils import parse_market_ts

REQUIRED_META=("symbol","timeframe","retrieved_at","timezone")
REQUIRED_BAR=("timestamp","open","high","low","close","volume")

def adapt_mcp_payload(payload):
    meta=payload.get("meta") or {}
    missing=[k for k in REQUIRED_META if meta.get(k) in (None,"")]
    if missing: raise ValueError("MISSING_MCP_META:"+",".join(missing))
    bars=payload.get("bars")
    if not isinstance(bars,list) or not bars: raise ValueError("EMPTY_MCP_BARS")
    out=[]
    for bar in bars:
        mb=[k for k in REQUIRED_BAR if bar.get(k) in (None,"")]
        if mb: raise ValueError("MISSING_MCP_BAR:"+",".join(mb))
        ts=parse_market_ts(bar["timestamp"])
        o,h,l,c=[float(bar[k]) for k in ("open","high","low","close")]
        v=float(bar["volume"])
        if not all(math.isfinite(x) for x in (o,h,l,c,v)): raise ValueError("NONFINITE_OHLCV")
        if h<max(o,c,l) or l>min(o,c,h): raise ValueError("INVALID_OHLC")
        if v<0: raise ValueError("INVALID_VOLUME")
        out.append({"symbol":meta["symbol"],"market_date":ts.date().isoformat(),
                    "timestamp":ts.isoformat(),"open":o,"high":h,"low":l,"close":c,
                    "volume":v,"source":"TRADINGVIEW_MCP",
                    "source_timeframe":str(meta["timeframe"]),
                    "source_timezone":meta["timezone"],
                    "retrieved_at":parse_market_ts(meta["retrieved_at"]).isoformat(),
                    "synthetic_timeframe":False,"research_only":True})
    for a,b in zip(out,out[1:]):
        if parse_market_ts(b["timestamp"])<=parse_market_ts(a["timestamp"]):
            raise ValueError("NON_INCREASING_TIMESTAMP")
    return out

def require_timeframe(rows,required):
    actual={str(r.get("source_timeframe")) for r in rows}
    if actual!={str(required)}:
        raise ValueError("TIMEFRAME_NOT_AVAILABLE:required=%s actual=%s"%(required,sorted(actual)))
    return rows
