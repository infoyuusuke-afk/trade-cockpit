"""Pure bridge from validated local source-health snapshots to Event Bus.
No file, Excel, broker, network, or TTS I/O is performed here.
"""
from __future__ import annotations
from scripts.event_bus import build_event
from scripts.local_source_health_contract import validate
VALID={"HEALTHY","DEGRADED","STOPPED","UNKNOWN"}
def source_health_event(snapshot):
    if not validate(snapshot): raise ValueError("invalid local source health snapshot")
    state=snapshot["state"]
    severity={"HEALTHY":"INFO","DEGRADED":"IMPORTANT","STOPPED":"CRITICAL","UNKNOWN":"CRITICAL"}[state]
    return build_event(timestamp=snapshot["observed_at"],domain="DATA",event_type="SOURCE_HEALTH",source=snapshot["source"],severity=severity,symbol=snapshot.get("symbol"),correlation_id=snapshot.get("correlation_id"),payload={"summary":f"{snapshot['source']}: {state}","decision":"BLOCK" if state in {"STOPPED","UNKNOWN"} else ("REVIEW" if state=="DEGRADED" else "HEALTHY"),"state":state,"last_data_at":snapshot.get("last_data_at"),"consecutive_failures":snapshot["consecutive_failures"],"reasons":snapshot["reasons"]})
