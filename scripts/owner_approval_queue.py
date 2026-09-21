"""Owner approval queue projection. Does not perform approvals or side effects."""
from __future__ import annotations
from datetime import datetime
APPROVAL_TYPES={"MAIN_MERGE","REAL_MONEY_SUBMIT","EXTERNAL_PUBLISH"}
ITEM_FIELDS={"approval_id","approval_type","created_at","summary","status","auto_approve"}
def _aware(ts):
    if not isinstance(ts,str) or not ts: raise ValueError("created_at required")
    d=datetime.fromisoformat(ts)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("created_at must be timezone-aware")
def build_queue(items):
    if not isinstance(items,list): raise ValueError("items must be list")
    out=[]; seen=set()
    for i in items:
        if not isinstance(i,dict): raise ValueError("invalid item")
        t=i.get("approval_type")
        if t not in APPROVAL_TYPES: raise ValueError("invalid approval_type")
        aid=i.get("approval_id")
        if not isinstance(aid,str) or not aid or aid in seen: raise ValueError("invalid or duplicate approval_id")
        seen.add(aid); _aware(i.get("created_at"))
        out.append({"approval_id":aid,"approval_type":t,"created_at":i["created_at"],"summary":i.get("summary"),"status":"PENDING_OWNER","auto_approve":False})
    return sorted(out,key=lambda x:(x["created_at"],x["approval_id"]))
def decide(item,decision):
    if not isinstance(item,dict) or set(item)!=ITEM_FIELDS: raise ValueError("invalid approval item")
    if item["approval_type"] not in APPROVAL_TYPES or item["auto_approve"] is not False: raise ValueError("invalid approval item")
    _aware(item["created_at"])
    if item["status"]!="PENDING_OWNER": raise ValueError("approval decision is terminal")
    if decision not in {"APPROVE","REJECT"}: raise ValueError("invalid decision")
    return {**item,"status":"OWNER_APPROVED" if decision=="APPROVE" else "OWNER_REJECTED","auto_approve":False}
