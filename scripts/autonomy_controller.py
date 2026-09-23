"""Top-level deterministic controller for AI Cockpit autonomous operation.

Pure orchestration: no broker, scheduler, restart, credential or publisher side effects.
"""
from scripts.autonomy_health import health
from scripts.self_healing_supervisor import recovery_plan
from scripts.autonomous_daily_loop import plan_day

def control(snapshot):
    h=health(snapshot.get("health",{}))
    if h["overall"]=="SAFE":
        blocked=[k for k,v in h["components"].items() if v=="BLOCKED"]
        incident={"code":snapshot.get("incident_code","UNKNOWN_BLOCK"),"blocked_components":blocked}
        return envelope("RECOVERY", h, recovery_plan(incident))
    if h["overall"]=="DEGRADED":
        return envelope("RECOVERY", h, recovery_plan({"code":snapshot.get("incident_code","STALE_DATA")}))
    daily=plan_day({
        "market_open":bool(snapshot.get("market_open",False)),
        "data_ready":snapshot.get("health",{}).get("data")=="OK",
    })
    return envelope("DAILY_LOOP",h,daily)

def envelope(mode,h,payload):
    return {"entry":"AI_COCKPIT","mode":mode,"health":h,"payload":payload,
            "owner_action_required":False,"real_submit_allowed":False,
            "external_publish_allowed":False}
