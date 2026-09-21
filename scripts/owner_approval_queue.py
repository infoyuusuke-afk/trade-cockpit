"""Owner approval queue projection. Does not perform approvals or side effects."""
from __future__ import annotations
from datetime import datetime
APPROVAL_TYPES={"MAIN_MERGE","REAL_MONEY_SUBMIT","EXTERNAL_PUBLISH"}
REQUIRED_INPUT_FIELDS={"approval_id","approval_type","created_at"}
OPTIONAL_INPUT_FIELDS={"summary"}
INPUT_FIELDS=REQUIRED_INPUT_FIELDS|OPTIONAL_INPUT_FIELDS
QUEUE_FIELDS=INPUT_FIELDS|{"status","auto_approve"}
def _created_at(value):
    if not isinstance(value,str) or not value: raise ValueError("created_at required")
    d=datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("created_at must be timezone-aware")
def build_queue(items):
    if not isinstance(items,list): raise ValueError("items must be list")
    out=[]; seen=set()
    for i in items:
        if not isinstance(i,dict) or not REQUIRED_INPUT_FIELDS.issubset(i) or not set(i).issubset(INPUT_FIELDS): raise ValueError("invalid approval item")
        t=i["approval_type"]
        if t not in APPROVAL_TYPES: raise ValueError("invalid approval_type")
        aid=i["approval_id"]
        if not isinstance(aid,str) or not aid.strip() or aid in seen: raise ValueError("invalid or duplicate approval_id")
        seen.add(aid); _created_at(i["created_at"])
        out.append({"approval_id":aid,"approval_type":t,"created_at":i["created_at"],"summary":i.get("summary"),"status":"PENDING_OWNER","auto_approve":False})
    return sorted(out,key=lambda x:(x["created_at"],x["approval_id"]))
def decide(item,decision):
    if not isinstance(item,dict) or set(item)!=QUEUE_FIELDS: raise ValueError("invalid queue item")
    if item["status"]!="PENDING_OWNER" or item["auto_approve"] is not False: raise ValueError("approval is not pending")
    if decision not in {"APPROVE","REJECT"}: raise ValueError("invalid decision")
    return {**item,"status":"OWNER_APPROVED" if decision=="APPROVE" else "OWNER_REJECTED","auto_approve":False}
