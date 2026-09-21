"""Privacy boundary for content preparation. Never mutates canonical source events."""
from __future__ import annotations
SENSITIVE={"account","account_id","order","order_id","orders","fill","fills","position","positions","board","tape","password","token","cookie","email","phone","address","name"}
ALLOWED_PAYLOAD={"summary","result","lesson","strategy","system_status","reason","symbol","timeframe"}
def _sensitive(key):
    k=str(key).lower()
    return k in SENSITIVE or any(k.startswith(x+"_") or k.endswith("_"+x) for x in SENSITIVE)
def sanitize_event_for_content(event):
    if not isinstance(event,dict): raise ValueError("event must be dict")
    payload=event.get("payload")
    if not isinstance(payload,dict): raise ValueError("payload must be dict")
    clean={}
    for k,v in payload.items():
        if _sensitive(k) or k not in ALLOWED_PAYLOAD: continue
        if isinstance(v,(str,int,float,bool)) or v is None: clean[k]=v
    return {"event_id":event["event_id"],"event_type":event["event_type"],"timestamp":event["timestamp"],"payload":clean,"external_publish_allowed":False}
