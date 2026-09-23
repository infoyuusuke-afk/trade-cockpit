"""Compact single-entry status for Owner/mobile presentation."""
def build_status(orchestration, market_quality_errors=None, publication_packet=None):
    lanes={x["lane"]:x for x in orchestration.get("lanes",[])}
    market=lanes.get("MARKET_DAILY")
    if market is None:
        market_state="NOT_PLANNED"
    elif market.get("reason")=="WAIT_DATA":
        market_state="WAIT_DATA"
    elif market_quality_errors:
        market_state="QUALITY_BLOCKED"
    elif publication_packet and publication_packet.get("status")=="READY_FOR_OWNER_REVIEW":
        market_state="READY_FOR_REVIEW"
    else:
        market_state="PREPARING"
    return {
      "entry":"AI_COCKPIT",
      "market_daily":market_state,
      "owner_traded":bool(orchestration.get("owner_traded",False)),
      "trade_analysis":"ACTIVE" if "TRADE_RESEARCH" in lanes else "NO_PERSONAL_TRADE",
      "entertainment":"CANDIDATE" if "ENTERTAINMENT" in lanes else "IDLE",
      "real_submit_allowed":False,
      "external_publish_allowed":False,
    }
