"""Public-content boundary. Converts validated internal events to minimal sanitized story facts."""
from __future__ import annotations
from scripts.event_bus import validate_event
SENSITIVE={"order","orders","order_id","fill","fills","position","positions","account","account_id","board","order_book","tape","ayumine","歩み値"}
ALLOWED={"event_id","timestamp","event_type","domain","severity","symbol","summary","content_visibility","external_publish_allowed"}
def _has_sensitive(value):
    if isinstance(value,dict):
        for k,v in value.items():
            if str(k).lower() in SENSITIVE or _has_sensitive(v): return True
    elif isinstance(value,list):
        return any(_has_sensitive(v) for v in value)
    return False
def sanitize_event(event):
    if not validate_event(event): raise ValueError("invalid event")
    if _has_sensitive(event.get("payload")): raise ValueError("sensitive payload")
    p=event["payload"]
    summary=p.get("summary")
    if summary is not None and not isinstance(summary,str): raise ValueError("summary must be string")
    return {"event_id":event["event_id"],"timestamp":event["timestamp"],"event_type":event["event_type"],"domain":event["domain"],"severity":event["severity"],"symbol":event.get("symbol"),"summary":summary,"content_visibility":"SANITIZED_INTERNAL","external_publish_allowed":False}
def validate_sanitized(event):
    return isinstance(event,dict) and set(event)==ALLOWED and event.get("content_visibility")=="SANITIZED_INTERNAL" and event.get("external_publish_allowed") is False
