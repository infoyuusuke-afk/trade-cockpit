"""Read-only adapters from existing safety/execution outputs to the common Event Bus.
No existing contract is modified and no execution side effect is introduced.
"""
from __future__ import annotations
from scripts.event_bus import build_event
def _ts(record):
    return record.get("generated_at") or record.get("created_at")
def risk_event(record):
    decision=record.get("decision")
    severity="CRITICAL" if decision=="BLOCK" else ("IMPORTANT" if decision=="SHADOW_ONLY" else "NOTICE")
    return build_event(timestamp=_ts(record),domain="RISK",event_type="RISK_DECISION",source="risk_gate",severity=severity,symbol=record.get("symbol"),correlation_id=record.get("merge_hash"),payload={"summary":f"Risk Gate: {decision}","decision":decision,"allowed_qty":record.get("allowed_qty"),"reasons":record.get("block_reasons") or []})
def conflict_event(record):
    status=record.get("resolved_status")
    severity="CRITICAL" if status and ("BLOCK" in status or "CONFLICT" in status) else "NOTICE"
    return build_event(timestamp=_ts(record),domain="STRATEGY",event_type="CONFLICT_RESOLUTION",source="conflict_resolver",severity=severity,symbol=record.get("symbol"),correlation_id=record.get("merge_hash"),payload={"summary":f"Conflict Resolver: {status}","decision":status,"reasons":record.get("block_reasons") or record.get("reasons") or []})
def execution_event(record):
    status=record.get("status") or record.get("permission_status") or record.get("reconfirm_status")
    severity="CRITICAL" if status in {"UNKNOWN","BLOCKED","PERMISSION_BLOCKED","RISK_BLOCKED"} else "NOTICE"
    return build_event(timestamp=_ts(record),domain="EXECUTION",event_type="EXECUTION_STATE",source="execution_stack",severity=severity,symbol=record.get("symbol"),correlation_id=record.get("intent_hash"),payload={"summary":f"Execution: {status}","decision":status,"reasons":record.get("block_reasons") or []})
