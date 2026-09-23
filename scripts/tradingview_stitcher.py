#!/usr/bin/env python3
"""Stitch TradingView CORE segments with strict overlap auditing."""
from datetime import datetime
from scripts.time_utils import parse_market_ts, JST

FIELDS=("open","high","low","close","volume")
TSE_SESSION_OPEN=(9,0,0)

# Issue #169: an absent 15s clock bucket is never assumed to be a verified
# acquisition gap and never assumed to be legitimate no-trade. It stays
# UNRESOLVED_NO_BAR_INTERVAL unless an independently acquired evidence
# source proves bars exist in that interval (VERIFIED_ACQUISITION_GAP), or
# the interval matches a known non-execution window (EXPECTED_SESSION_BREAK).
UNRESOLVED_NO_BAR_INTERVAL="UNRESOLVED_NO_BAR_INTERVAL"
VERIFIED_ACQUISITION_GAP="VERIFIED_ACQUISITION_GAP"
EXPECTED_SESSION_BREAK="EXPECTED_SESSION_BREAK"

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

def _independent_evidence_index(independent_evidence):
    index={}
    for row in (independent_evidence or []):
        index.setdefault(row["market_date"],[]).append(parse_market_ts(row["timestamp"]))
    return index

def _verified_by_independent_evidence(evidence_index,market_date,after,before):
    """True only if an independently acquired source has an observed bar
    strictly inside (after, before) that the primary source is missing."""
    return any(after<ts<before for ts in evidence_index.get(market_date,()))

def stitch_segments(segments,independent_evidence=None):
    if not segments: raise ValueError("NO_SEGMENTS")
    merged={}; duplicate_count=0; gaps=[]; expected_breaks=[]
    evidence_index=_independent_evidence_index(independent_evidence)
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
                item={"after":a["timestamp"],"before":b["timestamp"],"gap_seconds":sec}
                if reason:
                    item["reason"]=reason
                    item["status"]=EXPECTED_SESSION_BREAK
                    expected_breaks.append(item)
                else:
                    verified=_verified_by_independent_evidence(evidence_index,a["market_date"],ta,tb)
                    item["status"]=VERIFIED_ACQUISITION_GAP if verified else UNRESOLVED_NO_BAR_INTERVAL
                    gaps.append(item)
            elif sec<=0:
                raise ValueError("NON_INCREASING_TIMESTAMP")
    # Issue #169: a delayed first observed print for a session date (e.g. a
    # gap from the 09:00:00 JST TSE open to the first stitched bar) is a
    # distinct case the interior-gap loop above never inspects. Flag it
    # explicitly rather than silently treating opening coverage as complete.
    opening_absences=[]
    first_by_date={}
    for row in ordered:
        first_by_date.setdefault(row["market_date"],row)
    for market_date,first_row in sorted(first_by_date.items()):
        first_ts=parse_market_ts(first_row["timestamp"])
        y,m,d=(int(x) for x in market_date.split("-"))
        session_open=datetime(y,m,d,*TSE_SESSION_OPEN,tzinfo=JST)
        sec=(first_ts-session_open).total_seconds()
        if sec>15:
            verified=_verified_by_independent_evidence(evidence_index,market_date,session_open,first_ts)
            opening_absences.append({
                "market_date":market_date,
                "session_open":session_open.isoformat(),
                "first_observed":first_row["timestamp"],
                "gap_seconds":sec,
                "status":VERIFIED_ACQUISITION_GAP if verified else UNRESOLVED_NO_BAR_INTERVAL,
            })
    unresolved_opening_dates=sorted(a["market_date"] for a in opening_absences if a["status"]==UNRESOLVED_NO_BAR_INTERVAL)
    or_promotion_blocked_dates=sorted({a["market_date"] for a in opening_absences})
    return {"rows":ordered,
            "audit":{"input_segments":len(segments),
                     "output_rows":len(ordered),
                     "duplicate_overlap_rows":duplicate_count,
                     "intraday_gaps":gaps,
                     "gap_count":len(gaps),
                     "expected_session_breaks":expected_breaks,
                     "expected_session_break_count":len(expected_breaks),
                     "opening_absences":opening_absences,
                     "opening_absence_count":len(opening_absences),
                     "unresolved_opening_dates":unresolved_opening_dates,
                     "or_promotion_blocked_dates":or_promotion_blocked_dates,
                     "overlap_consistent":True,
                     "interpolation_used":False,
                     "synthesized_bars":False,
                     "research_only":True}}
