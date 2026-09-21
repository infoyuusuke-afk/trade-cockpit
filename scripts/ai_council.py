"""Research-only AI Council aggregation. It never grants execution permission."""
from __future__ import annotations
from datetime import datetime
VALID_STANCES={"OBSERVE","PROPOSE","CHALLENGE","REVIEW","BLOCK"}
MESSAGE_FIELDS={"agent","topic","stance","proposal","evidence","confidence","risk","timestamp"}
def _timestamp(value):
    if not isinstance(value,str) or not value: raise ValueError("timestamp required")
    d=datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("timestamp must be timezone-aware")
    return value
def council_snapshot(messages):
    if not isinstance(messages,list): raise ValueError("messages must be list")
    normalized=[]
    for m in messages:
        if not isinstance(m,dict) or set(m)!=MESSAGE_FIELDS: raise ValueError("invalid message fields")
        if not isinstance(m["agent"],str) or not m["agent"].strip(): raise ValueError("agent required")
        if not isinstance(m["topic"],str) or not m["topic"].strip(): raise ValueError("topic required")
        if m["stance"] not in VALID_STANCES: raise ValueError("invalid stance")
        c=m["confidence"]
        if isinstance(c,bool) or not isinstance(c,(int,float)) or not 0<=c<=1: raise ValueError("confidence must be 0..1")
        if not isinstance(m["evidence"],(list,dict)): raise ValueError("evidence must be structured")
        _timestamp(m["timestamp"])
        normalized.append({k:m[k] for k in ("agent","topic","stance","proposal","evidence","confidence","risk","timestamp")})
    normalized.sort(key=lambda x:(x["timestamp"],x["agent"]))
    blocked=any(x["stance"]=="BLOCK" for x in normalized)
    review=blocked or any(x["stance"] in {"CHALLENGE","REVIEW"} for x in normalized)
    return {"status":"BLOCK" if blocked else ("REVIEW" if review else "OBSERVE"),"messages":normalized,"owner_approval_required":True,"real_submit_allowed":False}
