"""Deterministic Event Bus intake guard: validation, dedupe and point-in-time freshness."""
from __future__ import annotations
from datetime import datetime
from scripts.event_bus import validate_event


def intake(events,*,now,max_age_seconds=60):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not isinstance(events,list):
        raise ValueError("events must be list")
    if max_age_seconds<0:
        raise ValueError("max_age_seconds must be >= 0")

    validated=[]
    rejected=[]
    for event in events:
        if not isinstance(event,dict):
            rejected.append({"event_id":None,"reason":"INVALID_EVENT"})
            continue
        event_id=event.get("event_id")
        if not validate_event(event):
            rejected.append({"event_id":event_id,"reason":"INVALID_EVENT"})
            continue
        validated.append(event)

    accepted=[]
    seen=set()
    for event in sorted(validated,key=lambda x:(x["timestamp"],x["event_id"])):
        event_id=event["event_id"]
        if event_id in seen:
            rejected.append({"event_id":event_id,"reason":"DUPLICATE_EVENT"})
            continue
        seen.add(event_id)
        ts=datetime.fromisoformat(event["timestamp"])
        age=(now-ts).total_seconds()
        if age<0:
            rejected.append({"event_id":event_id,"reason":"FUTURE_EVENT"})
            continue
        if age>max_age_seconds:
            rejected.append({"event_id":event_id,"reason":"STALE_EVENT"})
            continue
        accepted.append(event)
    return {"accepted":accepted,"rejected":rejected,"status":"READY" if accepted and not rejected else ("PARTIAL" if accepted else "BLOCK"),"real_submit_allowed":False}
