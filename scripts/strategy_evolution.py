"""Evidence-gated strategy evolution. Pure policy: no orders or deployment."""
STATES=("CANDIDATE","REPLAY","SHADOW","PROMOTION_CANDIDATE","DEMOTED")
def evaluate(s):
    required=("name","state","sample_size","expectancy","max_drawdown_pct","evidence_integrity")
    missing=[k for k in required if k not in s]
    if missing:return decision(s.get("name"),"CANDIDATE","HOLD",["MISSING:"+",".join(missing)])
    if s["evidence_integrity"] is not True:return decision(s["name"],"DEMOTED","DEMOTE",["EVIDENCE_INTEGRITY"])
    if s["sample_size"] < 30:return decision(s["name"],s["state"],"HOLD",["INSUFFICIENT_SAMPLE"])
    if s["expectancy"] <= 0:return decision(s["name"],"DEMOTED","DEMOTE",["NON_POSITIVE_EXPECTANCY"])
    if not 0 <= s["max_drawdown_pct"] <= 100:return decision(s["name"],"DEMOTED","DEMOTE",["INVALID_DRAWDOWN"])
    if s["state"]=="CANDIDATE":return decision(s["name"],"REPLAY","PROMOTE",[])
    if s["state"]=="REPLAY" and s.get("out_of_sample_pass") is True:return decision(s["name"],"SHADOW","PROMOTE",[])
    if s["state"]=="SHADOW" and s.get("shadow_pass") is True:return decision(s["name"],"PROMOTION_CANDIDATE","PROMOTE",[])
    return decision(s["name"],s["state"],"HOLD",["NEXT_GATE_NOT_PASSED"])
def decision(name,state,action,reasons):
    return {"name":name,"next_state":state,"action":action,"reasons":reasons,
            "real_submit_allowed":False,"owner_action_required":False}
