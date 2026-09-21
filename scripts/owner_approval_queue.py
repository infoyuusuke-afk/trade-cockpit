"""Owner approval queue projection. Does not perform approvals or side effects."""
from __future__ import annotations
APPROVAL_TYPES={"MAIN_MERGE","REAL_MONEY_SUBMIT","EXTERNAL_PUBLISH"}
def build_queue(items):
    out=[]
    for i in items:
        t=i.get("approval_type")
        if t not in APPROVAL_TYPES: raise ValueError("invalid approval_type")
        out.append({"approval_id":i["approval_id"],"approval_type":t,"created_at":i["created_at"],"summary":i.get("summary"),"status":"PENDING_OWNER","auto_approve":False})
    return sorted(out,key=lambda x:(x["created_at"],x["approval_id"]))
def decide(item,decision):
    if decision not in {"APPROVE","REJECT"}: raise ValueError("invalid decision")
    return {**item,"status":"OWNER_APPROVED" if decision=="APPROVE" else "OWNER_REJECTED","auto_approve":False}
