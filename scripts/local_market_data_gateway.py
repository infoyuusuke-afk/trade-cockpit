#!/usr/bin/env python3
"""C-115 Local Market Data Gateway.

Pure normalization/validation boundary for already-observed local MS2 or
TradingView-derived snapshots. Research/advisory only: no broker, order,
credential, or submit fields are accepted or emitted.
"""
from copy import deepcopy
from scripts.time_utils import assert_observed_by

ALLOWED_FIELDS = {
    "symbol","observed_at","generated_at","source","stale",
    "current","open","previous_close","volume","turnover","vwap",
    "or5_high","or5_mid","or5_low","or5_complete",
    "or15_high","or15_mid","or15_low","or15_complete",
    "ema9","ema20","flow_state",
}
PRIVATE_TOKENS = ("account","broker","credential","holding","order","password","position","token")
NUMERIC_FIELDS = {
    "current","open","previous_close","volume","turnover","vwap",
    "or5_high","or5_mid","or5_low","or15_high","or15_mid","or15_low","ema9","ema20",
}

def _reject_private_or_unknown(record):
    if not isinstance(record, dict):
        raise ValueError("SNAPSHOT_NOT_OBJECT")
    for key in record:
        low=str(key).lower()
        if any(t in low for t in PRIVATE_TOKENS):
            raise ValueError("PRIVATE_OR_ORDER_FIELD:"+str(key))
        if key not in ALLOWED_FIELDS:
            raise ValueError("UNKNOWN_FIELD:"+str(key))

def normalize_snapshot(record, now, freshness_max_age_seconds=60):
    _reject_private_or_unknown(record)
    r=deepcopy(record)
    required=("symbol","observed_at","generated_at","source")
    if any(not isinstance(r.get(k),str) or not r[k].strip() for k in required):
        raise ValueError("MISSING_REQUIRED_FIELD")
    try:
        observed,decision=assert_observed_by(r["observed_at"],now)
        generated,_=assert_observed_by(r["generated_at"],now)
    except ValueError as e:
        raise ValueError("FUTURE_OR_INVALID_TIMESTAMP") from e
    if generated < observed:
        raise ValueError("GENERATED_BEFORE_OBSERVED")
    for k in NUMERIC_FIELDS:
        if k in r and r[k] is not None and (not isinstance(r[k],(int,float)) or isinstance(r[k],bool)):
            raise ValueError("INVALID_NUMERIC_FIELD:"+k)
    for k in ("or5_complete","or15_complete","stale"):
        if k in r and not isinstance(r[k],bool):
            raise ValueError("INVALID_BOOLEAN_FIELD:"+k)
    age=(decision-observed).total_seconds()
    fail_reason=None
    if r.get("stale") is True or age>freshness_max_age_seconds:
        fail_reason="STALE_DATA"
    elif not r.get("or5_complete",False):
        fail_reason="OR5_INCOMPLETE"
    out={k:r.get(k) for k in ALLOWED_FIELDS if k in r}
    out.update({
        "freshness_age_seconds":age,
        "status":"WAIT_DATA" if fail_reason else "READY",
        "fail_reason":fail_reason,
        "flow_observed":r.get("flow_state") is not None,
        "or5_breakout_eligible":bool(r.get("or5_complete",False)) and fail_reason is None,
        "or15_breakout_eligible":bool(r.get("or15_complete",False)) and fail_reason is None,
        "research_only":True,
        "real_submit_allowed":False,
    })
    return out

def normalize_sources(records, now, freshness_max_age_seconds=60):
    """Normalize each source independently; disagreement is preserved."""
    if not isinstance(records,list) or not records:
        raise ValueError("NO_SNAPSHOTS")
    return {
        "snapshots":[normalize_snapshot(r,now,freshness_max_age_seconds) for r in records],
        "source_disagreement_preserved":True,
        "research_only":True,
        "real_submit_allowed":False,
    }
