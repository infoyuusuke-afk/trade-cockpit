"""Rest/no-trade day policy: keep market work alive without inventing personal activity."""
def apply_rest_day(plan, owner_available=True):
    out=dict(plan)
    out["owner_available"]=bool(owner_available)
    out["personal_trade_expected"]=False
    out["personal_trade_penalty"]=False
    out["market_daily_should_continue"]=True
    out["developer_review_optional"]=True
    out["entertainment_may_use_existing_sanitized_sources"]=True
    out["owner_action_required_only_for"]=["EXTERNAL_PUBLICATION","REAL_SUBMIT"]
    out["real_submit_allowed"]=False
    out["external_publish_allowed"]=False
    return out
