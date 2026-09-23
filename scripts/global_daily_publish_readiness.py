"""Prepare, but never execute, publication approval packets."""
def build_packet(brief, quality_errors):
    if quality_errors: return {"status":"BLOCKED","reasons":list(quality_errors),"publish_allowed":False}
    if brief.get("external_publish_allowed") is not False: raise ValueError("UNSAFE_BRIEF_STATE")
    return {
      "status":"READY_FOR_OWNER_REVIEW",
      "locale":brief.get("locale"),
      "date_jst":brief.get("date_jst"),
      "owner_traded":bool(brief.get("owner_traded",False)),
      "publish_allowed":False,
      "owner_approval_required":True,
      "publication_action":None,
      "feedback_route":"UNVERIFIED_RESEARCH_LEAD"
    }

def approve_packet(packet):
    if packet.get("status")!="READY_FOR_OWNER_REVIEW": raise ValueError("NOT_REVIEWABLE")
    out=dict(packet)
    out["status"]="OWNER_APPROVED_FOR_FUTURE_PUBLISHER"
    out["publish_allowed"]=False
    out["publication_action"]=None
    return out
