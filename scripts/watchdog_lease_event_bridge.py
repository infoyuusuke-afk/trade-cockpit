"""Map watchdog lease decisions into the existing Event Bus/Council safety path."""
from __future__ import annotations
from scripts.event_bus import build_event
def lease_event(decision, *, timestamp, symbol="TSE:285A"):
    status=decision["status"]
    severity="CRITICAL" if status=="BLOCK" else ("IMPORTANT" if status=="REVIEW" else "INFO")
    return build_event(domain="SYSTEM",event_type="WATCHDOG_LEASE",source="WATCHDOG_LEASE_GUARD",timestamp=timestamp,severity=severity,payload={"decision":"BLOCK" if status=="BLOCK" else status,"reasons":[decision["reason"]],"symbol":symbol})
