"""Deterministic external watchdog for local source-health snapshots."""
from __future__ import annotations
from datetime import datetime
from scripts.local_source_health_contract import validate
def evaluate(snapshot, *, now, stale_after_seconds=15):
    if now.tzinfo is None or now.utcoffset() is None: raise ValueError("now must be timezone-aware")
    if stale_after_seconds < 0: raise ValueError("stale_after_seconds must be >= 0")
    if not validate(snapshot):
        return {"state":"UNKNOWN","reason":"INVALID_SNAPSHOT","age_seconds":None,"real_submit_allowed":False}
    observed=datetime.fromisoformat(snapshot["observed_at"])
    age=(now-observed).total_seconds()
    if age < 0:
        return {"state":"UNKNOWN","reason":"FUTURE_SNAPSHOT","age_seconds":age,"real_submit_allowed":False}
    if age > stale_after_seconds:
        return {"state":"STOPPED","reason":"HEARTBEAT_STALE","age_seconds":age,"real_submit_allowed":False}
    return {"state":snapshot["state"],"reason":"FRESH","age_seconds":age,"real_submit_allowed":False}
