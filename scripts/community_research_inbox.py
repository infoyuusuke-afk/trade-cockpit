"""Quarantine overseas/community feedback as unverified research leads."""
def ingest_lead(item):
    required=("source_type","received_at","claim")
    if any(not item.get(k) for k in required): raise ValueError("INCOMPLETE_LEAD")
    if item.get("contains_private_data") is True: raise ValueError("PRIVATE_DATA_REJECTED")
    return {
      "source_type":item["source_type"],"received_at":item["received_at"],
      "claim":item["claim"],"source_ref":item.get("source_ref"),
      "language":item.get("language","unknown"),
      "status":"UNVERIFIED_RESEARCH_LEAD",
      "may_affect_signal":False,"may_affect_publication_fact":False,
      "requires_independent_verification":True,
      "research_only":True,"real_submit_allowed":False
    }

def promote_verified(lead,evidence_refs):
    if lead.get("status")!="UNVERIFIED_RESEARCH_LEAD": raise ValueError("INVALID_LEAD_STATE")
    if not evidence_refs: raise ValueError("NO_INDEPENDENT_EVIDENCE")
    out=dict(lead);out["status"]="VERIFIED_RESEARCH_INPUT";out["evidence_refs"]=list(evidence_refs)
    return out
