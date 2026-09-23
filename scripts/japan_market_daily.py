"""Build evidence-bound JP/Global daily Japan-market briefs independent of owner trading activity."""
def build_daily_briefs(snapshot):
    if snapshot.get("verified") is not True: raise ValueError("UNVERIFIED_MARKET_SNAPSHOT")
    if snapshot.get("sanitized") is not True: raise ValueError("UNSANITIZED_MARKET_SNAPSHOT")
    required=("date_jst","nikkei","topix","themes","notable_moves","evidence")
    if any(k not in snapshot for k in required): raise ValueError("INCOMPLETE_MARKET_SNAPSHOT")
    base={"date_jst":snapshot["date_jst"],"nikkei":snapshot["nikkei"],"topix":snapshot["topix"],
          "themes":snapshot["themes"],"notable_moves":snapshot["notable_moves"],"evidence":snapshot["evidence"],
          "owner_traded":bool(snapshot.get("owner_traded",False)),"research_only":True,
          "owner_approval_required":True,"external_publish_allowed":False}
    jp=dict(base,locale="ja-JP",audience="JAPAN_AND_GLOBAL_TRADERS",
            framing="日本市場の事実・テーマ・値動きを、本人の売買有無と切り離して整理する")
    gl=dict(base,locale="en",audience="GLOBAL_TRADERS",
            framing="Explain Japan-market facts, themes and notable moves with Japan-specific context; do not translate mechanically")
    return [jp,gl]
