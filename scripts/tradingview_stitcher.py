#!/usr/bin/env python3
"""Stitch TradingView CORE segments with strict overlap auditing."""
from scripts.time_utils import parse_market_ts

FIELDS=("open","high","low","close","volume")

def _same_bar(a,b):
    return all(float(a[k])==float(b[k]) for k in FIELDS)

def stitch_segments(segments):
    if not segments: raise ValueError("NO_SEGMENTS")
    merged={}; duplicate_count=0; gaps=[]
    for rows in segments:
        for row in rows:
            ts=row["timestamp"]
            if ts in merged:
                if not _same_bar(merged[ts],row):
                    raise ValueError("OVERLAP_MISMATCH:"+ts)
                duplicate_count+=1
            else:
                merged[ts]=row
    ordered=sorted(merged.values(),key=lambda r:parse_market_ts(r["timestamp"]))
    for a,b in zip(ordered,ordered[1:]):
        ta,tb=parse_market_ts(a["timestamp"]),parse_market_ts(b["timestamp"])
        # Audit only within same market date; overnight/session gaps are expected.
        if a["market_date"]==b["market_date"]:
            sec=(tb-ta).total_seconds()
            if sec>15:
                gaps.append({"after":a["timestamp"],"before":b["timestamp"],
                             "gap_seconds":sec})
            elif sec<=0:
                raise ValueError("NON_INCREASING_TIMESTAMP")
    return {"rows":ordered,
            "audit":{"input_segments":len(segments),
                     "output_rows":len(ordered),
                     "duplicate_overlap_rows":duplicate_count,
                     "intraday_gaps":gaps,
                     "gap_count":len(gaps),
                     "overlap_consistent":True,
                     "interpolation_used":False,
                     "research_only":True}}
