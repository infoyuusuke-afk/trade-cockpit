"""Owner approval queue projection. Pure state transitions; no side effects."""
from __future__ import annotations
from datetime import datetime
APPROVAL_TYPES={"MAIN_MERGE","REAL_MONEY_SUBMIT","EXTERNAL_PUBLISH"}
PENDING_FIELDS={"approval_id","approval_type","created_at","summary","status","auto_approve"}
def _aware(value):
    if not isinstance(value,str) or not value: raise ValueError("timestamp required")
    d=datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("timestamp must be timezone-aware")
    return value
def build_queue(items):
    if not isinstance(items,list): raise ValueError("items must be list")
    out=[]; seen=set()
    for i in items:
        if not isinstance(i,dict): raise ValueError("invalid item")
        allowed={"approval_id","approval_type","created_at","summary"}
        if not set(i).issubset(allowed): raise ValueError("unknown item field")
        aid=i.get("approval_id"); t=i.get("approval_type")
        if not isinstance(aid,str) or not aid: raise ValueError("approval_id required")
        if aid in seen: raise ValueError("duplicate approval_id")
        seen.add(aid)
        if t not in APPROVAL_TYPES: raise ValueError("invalid approval_type")
        created=_aware(i.get("created_at"))
        out.append({"approval_id":aid,"approval_type":t,"created_at":created,"summary":i.get("summary"),"status":"PENDING_OWNER","auto_approve":False})
    return sorted(out,key=lambda x:(x["created_at"],x["approval_id"]))
def decide(item,decision,*,decided_at=None,decided_by=None):
    if not isinstance(item,dict) or set(item)!=PENDING_FIELDS: raise ValueError("invalid pending item")
    if item.get("status")!="PENDING_OWNER" or item.get("auto_approve") is not False: raise ValueError("decision is terminal or unsafe")
    if decision not in {"APPROVE","REJECT"}: raise ValueError("invalid decision")
    result={**item,"status":"OWNER_APPROVED" if decision=="APPROVE" else "OWNER_REJECTED","auto_approve":False}
    if decided_at is None and decided_by is None:
        return result
    if decided_at is None or decided_by is None: raise ValueError("audit fields must be supplied together")
    _aware(decided_at)
    if not isinstance(decided_by,str) or not decided_by.strip(): raise ValueError("decided_by required")
    return {**result,"decided_at":decided_at,"decided_by":decided_by}
