"""Validate the local-only source health handoff contract."""
from __future__ import annotations
from datetime import datetime
ALLOWED={"schema_version","source","state","observed_at","last_data_at","symbol","correlation_id","consecutive_failures","reasons"}
STATES={"HEALTHY","DEGRADED","STOPPED","UNKNOWN"}
def validate(snapshot):
    if not isinstance(snapshot,dict) or set(snapshot)-ALLOWED: return False
    if snapshot.get("schema_version")!="local-source-health-1.0" or not snapshot.get("source") or snapshot.get("state") not in STATES: return False
    if not isinstance(snapshot.get("consecutive_failures"),int) or snapshot["consecutive_failures"]<0 or not isinstance(snapshot.get("reasons"),list): return False
    try:
        ts=datetime.fromisoformat(snapshot["observed_at"])
        if ts.tzinfo is None or ts.utcoffset() is None: return False
        if snapshot.get("last_data_at") is not None:
            d=datetime.fromisoformat(snapshot["last_data_at"])
            if d.tzinfo is None or d.utcoffset() is None: return False
    except (TypeError,ValueError): return False
    return True
