"""Single user-facing AI Cockpit entry router. No external side effects."""
ROUTES={
 "TRADE_RESEARCH":"strategy_lab",
 "MARKET_DAILY":"japan_market_daily",
 "DEVELOPER_GROWTH":"developer_growth_story",
 "ENTERTAINMENT":"entertainment_department",
 "COMMUNITY_LEAD":"community_research_inbox",
 "DIARY":"journal_projection",
}
def route(request):
    kind=request.get("kind")
    if kind not in ROUTES: raise ValueError("UNKNOWN_COCKPIT_REQUEST")
    if request.get("real_submit") is True: raise ValueError("REAL_SUBMIT_FORBIDDEN")
    if request.get("external_publish") is True: raise ValueError("OWNER_APPROVAL_REQUIRED")
    return {"entry":"AI_COCKPIT","kind":kind,"subsystem":ROUTES[kind],
            "research_only":True,"real_submit_allowed":False,
            "external_publish_allowed":False,"owner_approval_required":True}
