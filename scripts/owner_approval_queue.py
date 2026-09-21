"""Owner approval queue projection. Does not perform approvals or side effects."""
from __future__ import annotations
from datetime import datetime
APPROVAL_TYPES={"MAIN_MERGE","REAL_MONEY_SUBMIT","EXTERNAL_PUBLISH"}
ITEM_FIELDS={"approval_id","approval_type","created_at","summary"}
def _aware(value):
    if not isinstance(value,str) or not value: raise ValueError("timestamp required")
    d=datetime.fromisoformat(value)
    if d.tzinfo is None or d.utcoffset() is None: raise ValueError("timestamp must be timezone-aware")
def build_queue(items):
    if not isinstance(items,list): raise ValueError("items must be list")
    out=[]; seen=set()
    for i in items:
        if not isinstance(i,dict) or set(i)!=ITEM_FIELDS: raise ValueError("invalid approval item fields")
        if not isinstance(i["approval_id"],str) or not i["approval_id"] or i["approval_id"] in seen: raise ValueError("approval_id must be unique")
        seen.add(i["approval_id"]); _aware(i["created_at"])
        t=i["approval_type"]
        if t not in APPROVAL_TYPES: raise ValueError("invalid approval_type")
        out.append({"approval_id":i["approval_id"],"approval_type":t,"created_at":i["created_at"],"summary":i["summary"],"status":"PENDING_OWNER","auto_approve":False,"decision":None,"decided_at":None,"decided_by":None})
    return sorted(out,key=lambda x:(x["created_at"],x["approval_id"]))
def decide(item,decision,*,decided_at,decided_by):
    if not isinstance(item,dict) or item.get("status")!="PENDING_OWNER": raise ValueError("approval is terminal or invalid")
    if decision not in {"APPROVE","REJECT"}: raise ValueError("invalid decision")
    _aware(decided_at)
    if not isinstance(decided_by,str) or not decided_by.strip(): raise ValueError("decided_by required")
    return {**item,"status":"OWNER_APPROVED" if decision=="APPROVE" else "OWNER_REJECTED","auto_approve":False,"decision":decision,"decided_at":decided_at,"decided_by":decided_by}
