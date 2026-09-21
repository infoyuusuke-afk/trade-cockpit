"""Safe Council entry point: Event Intake Guard must pass before orchestration."""
from __future__ import annotations
from scripts.event_intake_guard import intake
from scripts.council_orchestrator import orchestrate
def guarded_orchestrate(events,*,now,max_age_seconds=60):
    gate=intake(events,now=now,max_age_seconds=max_age_seconds)
    if gate["status"]!="READY":
        return {"status":"BLOCK","gate":gate,"council":None,"command_center":None,"owner_approval_required":True,"real_submit_allowed":False,"external_publish_allowed":False}
    result=orchestrate(gate["accepted"])
    return {"status":"READY","gate":gate,**result}
