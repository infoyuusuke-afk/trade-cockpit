"""Independent consumer-side lease guard for External Watchdog output."""
from __future__ import annotations
from datetime import datetime
from scripts.local_source_health_contract import validate

def evaluate_watchdog_lease(snapshot, *, now, lease_seconds=15):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if lease_seconds < 0:
        raise ValueError("lease_seconds must be >= 0")
    if not isinstance(snapshot, dict) or not validate(snapshot):
        return _blocked("INVALID_OR_MISSING_WATCHDOG", None)
    observed=datetime.fromisoformat(snapshot["observed_at"])
    age=(now-observed).total_seconds()
    if age < 0:
        return _blocked("FUTURE_WATCHDOG", age)
    if age > lease_seconds:
        return _blocked("STALE_WATCHDOG", age)
    state=snapshot["state"]
    if state in {"STOPPED","UNKNOWN"}:
        return _blocked("WATCHDOG_"+state, age)
    if state=="DEGRADED":
        return {"status":"REVIEW","reason":"WATCHDOG_DEGRADED","age_seconds":age,"promotion_eligible":False,"real_submit_allowed":False}
    return {"status":"READY","reason":"WATCHDOG_HEALTHY","age_seconds":age,"promotion_eligible":False,"real_submit_allowed":False}

def _blocked(reason, age):
    return {"status":"BLOCK","reason":reason,"age_seconds":age,"promotion_eligible":False,"real_submit_allowed":False}
