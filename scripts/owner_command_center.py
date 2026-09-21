"""Owner Command Center projection. Pure read-model; no execution or network I/O."""
from __future__ import annotations
SEV={"CRITICAL":0,"IMPORTANT":1,"NOTICE":2,"INFO":3}
def build_command_center(events,council=None):
    rows=[]
    for e in events:
        p=e.get("payload") or {}
        rows.append({"event_id":e["event_id"],"timestamp":e["timestamp"],"domain":e["domain"],"severity":e["severity"],"symbol":e.get("symbol"),"summary":p.get("summary") or e["event_type"],"requires_owner":bool(p.get("owner_approval_required",False))})
    rows.sort(key=lambda x:(SEV.get(x["severity"],9),x["timestamp"],x["event_id"]))
    critical=sum(r["severity"]=="CRITICAL" for r in rows)
    approvals=sum(r["requires_owner"] for r in rows)
    return {"system_status":"ATTENTION" if critical else "NORMAL","critical_count":critical,"pending_owner_approvals":approvals,"council_status":None if council is None else council.get("status"),"feed":rows,"real_submit_allowed":False}
