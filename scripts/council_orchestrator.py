"""Deterministic AI Council orchestration from Event Bus records.
Research/control-plane only. Never grants execution or publishing permission.
"""
from __future__ import annotations
from scripts.ai_council import council_snapshot
from scripts.owner_command_center import build_command_center
BLOCKING={"RISK_DECISION":{"BLOCK"},"EXECUTION_STATE":{"UNKNOWN","BLOCKED","PERMISSION_BLOCKED","RISK_BLOCKED"}}
def event_to_message(event):
    p=event.get("payload") or {}
    decision=p.get("decision")
    blocked=decision in BLOCKING.get(event.get("event_type"),set()) or event.get("severity")=="CRITICAL"
    stance="BLOCK" if blocked else ("REVIEW" if event.get("severity")=="IMPORTANT" else "OBSERVE")
    return {"agent":event.get("source"),"topic":event.get("symbol") or event.get("event_type"),"stance":stance,"proposal":decision,"evidence":p.get("reasons") or [event.get("event_id")],"confidence":1.0 if blocked else 0.5,"risk":decision if blocked else None,"timestamp":event.get("timestamp")}
def orchestrate(events):
    ordered=sorted(events,key=lambda e:(e["timestamp"],e["event_id"]))
    messages=[event_to_message(e) for e in ordered]
    council=council_snapshot(messages)
    command=build_command_center(ordered,council)
    return {"council":council,"command_center":command,"event_count":len(ordered),"owner_approval_required":True,"real_submit_allowed":False,"external_publish_allowed":False}
