"""Research-only AI Council aggregation. It never grants execution permission."""
from __future__ import annotations
VALID_STANCES={"OBSERVE","PROPOSE","CHALLENGE","REVIEW","BLOCK"}
def council_snapshot(messages):
    if not isinstance(messages,list): raise ValueError("messages must be list")
    normalized=[]
    for m in messages:
        if m.get("stance") not in VALID_STANCES: raise ValueError("invalid stance")
        c=m.get("confidence")
        if isinstance(c,bool) or not isinstance(c,(int,float)) or not 0<=c<=1: raise ValueError("confidence must be 0..1")
        normalized.append({k:m.get(k) for k in ("agent","topic","stance","proposal","evidence","confidence","risk","timestamp")})
    normalized.sort(key=lambda x:(x["timestamp"] or "",x["agent"] or ""))
    blocked=any(x["stance"]=="BLOCK" for x in normalized)
    review=blocked or any(x["stance"] in {"CHALLENGE","REVIEW"} for x in normalized)
    return {"status":"BLOCK" if blocked else ("REVIEW" if review else "OBSERVE"),"messages":normalized,"owner_approval_required":True,"real_submit_allowed":False}
