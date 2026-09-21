"""Deterministic cooldown/throttle for commentary candidates."""
from __future__ import annotations
from datetime import datetime

REQUIRED_FIELDS={"event_id","priority","text","speech_text","timestamp","real_submit_allowed"}


def _aware_timestamp(value,field):
    if not isinstance(value,str) or not value:
        raise ValueError(f"{field} required")
    try:
        parsed=datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def schedule(candidates,last_spoken_at=None,cooldown_seconds=20,max_items=1):
    if cooldown_seconds<0 or max_items<1:
        raise ValueError("invalid scheduler limits")
    if not isinstance(candidates,list):
        raise ValueError("candidates must be list")
    last=_aware_timestamp(last_spoken_at,"last_spoken_at") if last_spoken_at else None
    validated=[]
    for candidate in candidates:
        if not isinstance(candidate,dict) or set(candidate)!=REQUIRED_FIELDS:
            raise ValueError("malformed commentary candidate")
        if candidate["real_submit_allowed"] is not False:
            raise ValueError("commentary candidate cannot submit")
        ts=_aware_timestamp(candidate["timestamp"],"candidate timestamp")
        validated.append((candidate,ts))
    validated.sort(key=lambda row:(row[0]["priority"],row[0]["timestamp"],row[0]["event_id"]))
    out=[]
    for candidate,ts in validated:
        if last is not None:
            delta=(ts-last).total_seconds()
            if delta<0:
                raise ValueError("candidate precedes last_spoken_at")
            if delta<cooldown_seconds:
                continue
        out.append(candidate)
        last=ts
        if len(out)>=max_items:
            break
    return out
