"""Owner approval queue projection. Does not perform approvals or side effects."""
from __future__ import annotations
from datetime import datetime
APPROVAL_TYPES={"MAIN_MERGE","REAL_MONEY_SUBMIT","EXTERNAL_PUBLISH"}
INPUT_FIELDS={"approval_id","approval_type","created_at","summary"}
def _aware(value,name):
    if not isinstance(value,str) or not value: raise ValueError(f"{name} required")
    d=datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError(f"{name} must be timezone-aware")
    return value
def build_queue(items):
    if not isinstance(items,list): raise ValueError("items must be list")
    out=[]; seen=set()
    for i in items:
        if not isinstance(i,dict) or set(i)!=INPUT_FIELDS: raise ValueError("invalid approval item fields")
        aid=i["approval_id"]
        if not isinstance(aid,str) or not aid.strip(): raise ValueError("approval_id required")
        if aid in seen: raise ValueError("duplicate approval_id")
        seen.add(aid)
        t=i["approval_type"]
        if t not in APPROVAL_TYPES: raise ValueError("invalid approval_type")
        created=_aware(i["created_at"],"created_at")
        out.append({"approval_id":aid,"approval_type":t,"created_at":created,"summary":i["summary"],"status":"PENDING_OWNER","auto_approve":False})
    return sorted(out,key=lambda x:(x["created_at"],x["approval_id"]))
def decide(item,decision,*,decided_at,actor="OWNER"):
    if not isinstance(item,dict) or item.get("status")!="PENDING_OWNER": raise ValueError("approval is not pending")
    if item.get("auto_approve") is not False: raise ValueError("auto approval forbidden")
    if decision not in {"APPROVE","REJECT"}: raise ValueError("invalid decision")
    if actor!="OWNER": raise ValueError("only OWNER may decide")
    decided=_aware(decided_at,"decided_at")
    return {**item,"status":"OWNER_APPROVED" if decision=="APPROVE" else "OWNER_REJECTED","auto_approve":False,"decided_at":decided,"decided_by":"OWNER"}
