"""Deterministic fail-safe recovery planner. No side effects or order submission."""
RECOVERY={
 "STALE_DATA":["RETRY_PRIMARY","CHECK_APPROVED_SECONDARY","WAIT_DATA"],
 "SOURCE_DISAGREEMENT":["QUARANTINE_INPUT","RECHECK_SOURCES","WAIT_DATA"],
 "STRATEGY_REGRESSION":["DEMOTE_STRATEGY","FALLBACK_SHADOW"],
 "EXECUTION_ANOMALY":["FREEZE_NEW_ORDERS","RECONCILE_STATE","SAFE"],
 "PUBLISH_FAILURE":["RETRY_WITH_BACKOFF","HOLD_DRAFT"],
 "AI_DISAGREEMENT":["COMPARE_EVIDENCE","CHOOSE_SAFER_STATE"],
}
def recovery_plan(event):
    code=event.get("code")
    if code not in RECOVERY: return {"code":code,"state":"SAFE","steps":["QUARANTINE_UNKNOWN","RECORD_INCIDENT"],"owner_action_required":False}
    return {"code":code,"state":"RECOVERING","steps":RECOVERY[code]+["RECORD_INCIDENT"],
            "owner_action_required":False,"real_submit_allowed":False,"external_publish_allowed":False}

def terminal_state(plan,recovered):
    if recovered: return "RECOVERED"
    if plan["code"] in ("STRATEGY_REGRESSION",): return "SHADOW"
    if plan["code"] in ("STALE_DATA","SOURCE_DISAGREEMENT"): return "WAIT_DATA"
    return "SAFE"
