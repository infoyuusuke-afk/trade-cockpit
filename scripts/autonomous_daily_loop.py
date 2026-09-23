"""Side-effect-free planner for an Owner-independent AI Cockpit daily loop."""
PHASES=("ACQUIRE","VALIDATE","ANALYZE","DECIDE","EVALUATE","REPORT","LEARN")
def plan_day(state):
    market_open=bool(state.get("market_open",False))
    data_ready=bool(state.get("data_ready",False))
    tasks=[{"phase":"ACQUIRE","action":"COLLECT_APPROVED_SOURCES"}]
    if not data_ready:
        tasks += [{"phase":"VALIDATE","action":"RECOVER_OR_WAIT_DATA"},
                  {"phase":"REPORT","action":"UPDATE_COCKPIT_STATUS"}]
        return envelope(tasks,"WAIT_DATA")
    tasks += [{"phase":"VALIDATE","action":"VERIFY_FRESHNESS_AND_INTEGRITY"},
              {"phase":"ANALYZE","action":"RUN_STRATEGY_LAB"}]
    if market_open:
        tasks.append({"phase":"DECIDE","action":"SHADOW_OR_ELIGIBLE_DECISION"})
    else:
        tasks.append({"phase":"DECIDE","action":"NO_MARKET_ORDER_DECISION"})
    tasks += [{"phase":"EVALUATE","action":"MEASURE_EXPECTATION_VS_RESULT"},
              {"phase":"REPORT","action":"BUILD_JP_GLOBAL_INTERNAL_BRIEFS"},
              {"phase":"LEARN","action":"UPDATE_INCIDENT_AND_STRATEGY_CANDIDATES"}]
    return envelope(tasks,"PLANNED")
def envelope(tasks,status):
    return {"entry":"AI_COCKPIT","status":status,"tasks":tasks,"owner_action_required":False,
            "real_submit_allowed":False,"external_publish_allowed":False}
