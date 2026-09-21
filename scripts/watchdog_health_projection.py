"""Project watchdog decisions into the existing local source-health contract."""
from __future__ import annotations
def project(snapshot, decision, *, observed_at):
    state=decision["state"]
    return {"schema_version":"local-source-health-1.0","source":"EXTERNAL_HEALTH_WATCHDOG","state":state,"observed_at":observed_at,"last_data_at":snapshot.get("observed_at") if isinstance(snapshot,dict) else None,"symbol":snapshot.get("symbol") if isinstance(snapshot,dict) else None,"correlation_id":None,"consecutive_failures":1 if state in {"STOPPED","UNKNOWN"} else 0,"reasons":[decision["reason"]]}
