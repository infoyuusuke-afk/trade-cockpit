"""Deterministic Event Bus intake guard: validation, dedupe and point-in-time freshness."""
from __future__ import annotations
from datetime import datetime
from scripts.event_bus import validate_event
def intake(events,*,now,max_age_seconds=60):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None: raise ValueError("now must be timezone-aware")
    if max_age_seconds<0: raise ValueError("max_age_seconds must be >= 0")
    accepted=[]; rejected=[]; seen=set()
    if not isinstance(events,list): raise ValueError("events must be list")
    safe_events=[e for e in events if isinstance(e,dict)]
    for bad in events:
        if not isinstance(bad,dict): rejected.append({"event_id":None,"reason":"INVALID_EVENT"})
    for e in sorted(safe_events,key=lambda x:(str(x.get("timestamp","")),str(x.get("event_id","")))):
        eid=e.get("event_id")
        if eid in seen:
            rejected.append({"event_id":eid,"reason":"DUPLICATE_EVENT"})
            continue
        seen.add(eid)
        if not validate_event(e):
            rejected.append({"event_id":eid,"reason":"INVALID_EVENT"})
            continue
        ts=datetime.fromisoformat(e["timestamp"])
        age=(now-ts).total_seconds()
        if age<0:
            rejected.append({"event_id":eid,"reason":"FUTURE_EVENT"})
            continue
        if age>max_age_seconds:
            rejected.append({"event_id":eid,"reason":"STALE_EVENT"})
            continue
        accepted.append(e)
    return {"accepted":accepted,"rejected":rejected,"status":"READY" if accepted and not rejected else ("PARTIAL" if accepted else "BLOCK"),"real_submit_allowed":False}
