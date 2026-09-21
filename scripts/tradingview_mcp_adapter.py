#!/usr/bin/env python3
"""TradingView MCP payload -> research CORE rows. Never synthesize lower timeframes."""
import math
from scripts.time_utils import parse_market_ts

REQUIRED_META=("symbol","timeframe","retrieved_at","timezone")
REQUIRED_BAR=("timestamp","open","high","low","close","volume")
ALLOWED_TOP={"meta","bars"};ALLOWED_META=set(REQUIRED_META);ALLOWED_BAR=set(REQUIRED_BAR)\nREQUIRED_SYMBOL="TSE:285A";REQUIRED_TIMEFRAME="15S";REQUIRED_TIMEZONE="Asia/Tokyo"

def _validate_contract_shape(payload):
    if not isinstance(payload,dict): raise ValueError("MCP_PAYLOAD_NOT_OBJECT")
    extra=set(payload)-ALLOWED_TOP
    if extra: raise ValueError("UNKNOWN_MCP_TOP_FIELD:"+",".join(sorted(extra)))
    meta=payload.get("meta")
    if not isinstance(meta,dict): raise ValueError("MCP_META_NOT_OBJECT")
    extra=set(meta)-ALLOWED_META
    if extra: raise ValueError("UNKNOWN_MCP_META_FIELD:"+",".join(sorted(extra)))
    if meta.get("symbol") not in (None,"",REQUIRED_SYMBOL): raise ValueError("MCP_SYMBOL_MISMATCH")
    if meta.get("timeframe") not in (None,"",REQUIRED_TIMEFRAME): raise ValueError("MCP_TIMEFRAME_MISMATCH")
    if meta.get("timezone") not in (None,"",REQUIRED_TIMEZONE): raise ValueError("MCP_TIMEZONE_MISMATCH")
    bars=payload.get("bars")
    if not isinstance(bars,list) or not bars: raise ValueError("EMPTY_MCP_BARS")
    for bar in bars:
        if not isinstance(bar,dict): raise ValueError("MCP_BAR_NOT_OBJECT")
        extra=set(bar)-ALLOWED_BAR
        if extra: raise ValueError("UNKNOWN_MCP_BAR_FIELD:"+",".join(sorted(extra)))
        for k in ("open","high","low","close","volume"):
            if k in bar and (not isinstance(bar[k],(int,float)) or isinstance(bar[k],bool)):
                raise ValueError("MCP_BAR_NOT_NUMERIC:"+k)

def adapt_mcp_payload(payload):
    _validate_contract_shape(payload)
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
