#!/usr/bin/env python3
"""TradingView CSV -> research CORE rows. Fail closed on unknown schema."""
import csv
from pathlib import Path
from scripts.time_utils import parse_market_ts

ALIASES={
 "timestamp":("time","timestamp","date","datetime"),
 "open":("open",),"high":("high",),"low":("low",),"close":("close",),
 "volume":("volume","vol"),
}
def _norm(s): return str(s).strip().lower().replace(" ","_")

def resolve_columns(fieldnames):
    norm={_norm(x):x for x in (fieldnames or [])}
    out={}
    for target,aliases in ALIASES.items():
        hit=next((norm[a] for a in aliases if a in norm),None)
        if hit is None: raise ValueError("UNKNOWN_TRADINGVIEW_SCHEMA:"+target)
        out[target]=hit
    return out

def adapt_row(row,cols,symbol):
    ts=parse_market_ts(row[cols["timestamp"]])
    o,h,l,c=[float(row[cols[x]]) for x in ("open","high","low","close")]
    v=float(row[cols["volume"]])
    if h<max(o,c,l) or l>min(o,c,h): raise ValueError("INVALID_OHLC")
    if v<0: raise ValueError("INVALID_VOLUME")
    return {"symbol":symbol,"market_date":ts.date().isoformat(),
            "timestamp":ts.isoformat(),"open":o,"high":h,"low":l,"close":c,
            "volume":v,"source":"TRADINGVIEW_15S","research_only":True}

def adapt_csv(path,symbol):
    path=Path(path)
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f); cols=resolve_columns(reader.fieldnames)
        rows=[adapt_row(r,cols,symbol) for r in reader]
    if not rows: raise ValueError("EMPTY_TRADINGVIEW_CSV")
    for a,b in zip(rows,rows[1:]):
        if parse_market_ts(b["timestamp"])<=parse_market_ts(a["timestamp"]):
            raise ValueError("NON_INCREASING_TIMESTAMP")
    return rows
