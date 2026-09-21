"""Pure bridge from local source-health snapshots to Event Bus.
No file, Excel, broker, network, or TTS I/O is performed here.
"""
from __future__ import annotations
from scripts.event_bus import build_event
VALID={"HEALTHY","DEGRADED","STOPPED","UNKNOWN"}
def source_health_event(snapshot):
    if not isinstance(snapshot,dict): raise ValueError("snapshot must be dict")
    state=snapshot.get("state")
    if state not in VALID: raise ValueError("invalid source health state")
    severity={"HEALTHY":"INFO","DEGRADED":"IMPORTANT","STOPPED":"CRITICAL","UNKNOWN":"CRITICAL"}[state]
    return build_event(timestamp=snapshot.get("observed_at"),domain="DATA",event_type="SOURCE_HEALTH",source=snapshot.get("source") or "source_health",severity=severity,symbol=snapshot.get("symbol"),correlation_id=snapshot.get("correlation_id"),payload={"summary":f"{snapshot.get('source')}: {state}","decision":"BLOCK" if state in {"STOPPED","UNKNOWN"} else ("REVIEW" if state=="DEGRADED" else "HEALTHY"),"state":state,"last_data_at":snapshot.get("last_data_at"),"consecutive_failures":snapshot.get("consecutive_failures",0),"reasons":snapshot.get("reasons") or []})
