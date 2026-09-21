#!/usr/bin/env python3
"""Stitch TradingView CORE segments with strict overlap auditing."""
from scripts.time_utils import parse_market_ts

FIELDS=("open","high","low","close","volume")

def _same_bar(a,b):
    return all(float(a[k])==float(b[k]) for k in FIELDS)


def _expected_tse_session_break(ta,tb):
    """Classify expected TSE cash-equity 15s non-execution intervals."""
    if ta.date()!=tb.date(): return None
    a=(ta.hour,ta.minute,ta.second); b=(tb.hour,tb.minute,tb.second)
    if a in {(11,29,45),(11,30,0)} and b==(12,30,0):
        return "LUNCH_RECESS"
    if a in {(15,24,45),(15,25,0)} and b==(15,30,0):
        return "CLOSING_AUCTION"
    return None

def stitch_segments(segments):
    if not segments: raise ValueError("NO_SEGMENTS")
    merged={}; duplicate_count=0; gaps=[]; expected_breaks=[]
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
                reason=_expected_tse_session_break(ta,tb)
                target=expected_breaks if reason else gaps
                item={"after":a["timestamp"],"before":b["timestamp"],"gap_seconds":sec}
                if reason: item["reason"]=reason
                target.append(item)
            elif sec<=0:
                raise ValueError("NON_INCREASING_TIMESTAMP")
    return {"rows":ordered,
            "audit":{"input_segments":len(segments),
                     "output_rows":len(ordered),
                     "duplicate_overlap_rows":duplicate_count,
                     "intraday_gaps":gaps,
                     "gap_count":len(gaps),
                     "expected_session_breaks":expected_breaks,
                     "expected_session_break_count":len(expected_breaks),
                     "overlap_consistent":True,
                     "interpolation_used":False,
                     "research_only":True}}
