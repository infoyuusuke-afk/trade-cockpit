"""Deterministic cooldown/throttle for commentary candidates."""
from __future__ import annotations
from datetime import datetime
def schedule(candidates,last_spoken_at=None,cooldown_seconds=20,max_items=1):
    if cooldown_seconds<0 or max_items<1: raise ValueError("invalid scheduler limits")
    if not isinstance(candidates,list) or any(not isinstance(x,dict) or not {"priority","timestamp","event_id"}.issubset(x) for x in candidates): raise ValueError("invalid candidates")
    ordered=sorted(candidates,key=lambda x:(x["priority"],x["timestamp"],x["event_id"]))
    out=[]; last=datetime.fromisoformat(last_spoken_at) if last_spoken_at else None
    if last is not None and (last.tzinfo is None or last.utcoffset() is None): raise ValueError("last_spoken_at must be timezone-aware")
    for c in ordered:
        ts=datetime.fromisoformat(c["timestamp"])
        if ts.tzinfo is None or ts.utcoffset() is None: raise ValueError("candidate timestamp must be timezone-aware")
        if last is not None and ts < last: continue
        if last is not None and (ts-last).total_seconds()<cooldown_seconds: continue
        out.append(c); last=ts
        if len(out)>=max_items: break
    return out
