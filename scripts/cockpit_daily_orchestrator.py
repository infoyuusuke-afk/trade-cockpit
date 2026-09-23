"""Plan one AI Cockpit daily cycle without external side effects."""
def plan_day(ctx):
    market_verified=ctx.get("market_verified") is True
    owner_traded=ctx.get("owner_traded") is True
    development_events=int(ctx.get("development_events",0))
    diary_available=ctx.get("diary_available") is True
    plan=[]
    if market_verified:
        plan.append({"lane":"MARKET_DAILY","required":True,"reason":"verified_market_day"})
    else:
        plan.append({"lane":"MARKET_DAILY","required":False,"reason":"WAIT_DATA"})
    if owner_traded:
        plan.append({"lane":"TRADE_RESEARCH","required":True,"reason":"owner_trade_evidence"})
    if development_events>0:
        plan.append({"lane":"DEVELOPER_GROWTH","required":True,"reason":"verified_development_evidence"})
    if diary_available:
        plan.append({"lane":"DIARY","required":False,"reason":"sanitized_diary_available"})
    if any(x["lane"] in ("TRADE_RESEARCH","DEVELOPER_GROWTH","DIARY") for x in plan):
        plan.append({"lane":"ENTERTAINMENT","required":False,"reason":"story_source_available"})
    return {"entry":"AI_COCKPIT","owner_traded":owner_traded,"lanes":plan,
            "real_submit_allowed":False,"external_publish_allowed":False}

def completion_summary(plan):
    names=[x["lane"] for x in plan["lanes"]]
    return {"market_daily_planned":"MARKET_DAILY" in names,
            "personal_trade_required":"TRADE_RESEARCH" in names,
            "entertainment_candidate":"ENTERTAINMENT" in names}
