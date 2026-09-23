"""Track market-publication continuity without pressuring the Owner to trade."""
def continuity(days):
    ordered=sorted(days,key=lambda x:x["date_jst"])
    published_ready=sum(1 for x in ordered if x.get("market_brief_ready") is True)
    traded=sum(1 for x in ordered if x.get("owner_traded") is True)
    missed=[x["date_jst"] for x in ordered if x.get("market_expected") is True and x.get("market_brief_ready") is not True]
    return {"days_observed":len(ordered),"market_briefs_ready":published_ready,
            "owner_trade_days":traded,"missing_market_brief_dates":missed,
            "trade_activity_affects_market_continuity":False}
