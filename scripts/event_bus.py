"""Deterministic internal event contract. No broker/network/publish I/O."""
from __future__ import annotations
import hashlib, json
from datetime import datetime
SCHEMA_VERSION="cockpit-event-1.0"
VALID_DOMAINS={"MARKET","DATA","STRATEGY","RISK","EXECUTION","COUNCIL","COMMENTARY","JOURNAL","ENTERTAINMENT","PUBLISHING","SYSTEM"}
VALID_SEVERITIES={"INFO","NOTICE","IMPORTANT","CRITICAL"}
def _aware(ts):
    d=datetime.fromisoformat(ts)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("timestamp must be timezone-aware")
    return d
def build_event(*,timestamp,domain,event_type,source,payload,severity="INFO",symbol=None,correlation_id=None):
    _aware(timestamp)
    if domain not in VALID_DOMAINS: raise ValueError("invalid domain")
    if severity not in VALID_SEVERITIES: raise ValueError("invalid severity")
    if not event_type or not source or not isinstance(payload,dict): raise ValueError("invalid event")
    canonical={"schema_version":SCHEMA_VERSION,"timestamp":timestamp,"domain":domain,"event_type":event_type,"source":source,"severity":severity,"symbol":symbol,"correlation_id":correlation_id,"payload":payload}
    raw=json.dumps(canonical,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
    return {**canonical,"event_id":hashlib.sha256(raw).hexdigest(),"real_submit_allowed":False,"external_publish_allowed":False}
def validate_event(e):
    allowed={"schema_version","timestamp","domain","event_type","source","severity","symbol","correlation_id","payload","event_id","real_submit_allowed","external_publish_allowed"}
    if not isinstance(e,dict) or set(e)!=allowed: return False
    if e["schema_version"]!=SCHEMA_VERSION or e["real_submit_allowed"] is not False or e["external_publish_allowed"] is not False:return False
    try:
        rebuilt=build_event(timestamp=e["timestamp"],domain=e["domain"],event_type=e["event_type"],source=e["source"],payload=e["payload"],severity=e["severity"],symbol=e.get("symbol"),correlation_id=e.get("correlation_id"))
    except (ValueError,TypeError): return False
    return rebuilt["event_id"]==e["event_id"]
