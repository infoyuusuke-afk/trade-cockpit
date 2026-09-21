"""Validate the local-only source health handoff contract."""
from __future__ import annotations
from datetime import datetime
ALLOWED={"schema_version","source","state","observed_at","last_data_at","symbol","correlation_id","consecutive_failures","reasons"}
REQUIRED={"schema_version","source","state","observed_at","consecutive_failures","reasons"}
STATES={"HEALTHY","DEGRADED","STOPPED","UNKNOWN"}
def _text_or_none(v): return v is None or isinstance(v,str)
def validate(snapshot):
    if not isinstance(snapshot,dict) or set(snapshot)-ALLOWED or not REQUIRED.issubset(snapshot): return False
    if snapshot.get("schema_version")!="local-source-health-1.0" or not isinstance(snapshot.get("source"),str) or not snapshot["source"] or snapshot.get("state") not in STATES: return False
    if not _text_or_none(snapshot.get("symbol")) or not _text_or_none(snapshot.get("correlation_id")): return False
    if isinstance(snapshot.get("consecutive_failures"),bool) or not isinstance(snapshot.get("consecutive_failures"),int) or snapshot["consecutive_failures"]<0: return False
    if not isinstance(snapshot.get("reasons"),list) or not all(isinstance(x,str) for x in snapshot["reasons"]): return False
    try:
        ts=datetime.fromisoformat(snapshot["observed_at"])
        if ts.tzinfo is None or ts.utcoffset() is None: return False
        if snapshot.get("last_data_at") is not None:
            d=datetime.fromisoformat(snapshot["last_data_at"])
            if d.tzinfo is None or d.utcoffset() is None: return False
    except (TypeError,ValueError): return False
    return True
