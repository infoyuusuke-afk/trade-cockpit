"""Compact health projection for autonomous operation."""
def health(signals):
    states=[]
    for name in ("data","strategy","execution","reporting","learning"):
        value=signals.get(name,"UNKNOWN")
        if value not in ("OK","DEGRADED","BLOCKED","UNKNOWN"): raise ValueError("INVALID_STATE")
        states.append((name,value))
    if any(v=="BLOCKED" for _,v in states): overall="SAFE"
    elif any(v in ("DEGRADED","UNKNOWN") for _,v in states): overall="DEGRADED"
    else: overall="HEALTHY"
    return {"overall":overall,"components":dict(states),"owner_action_required":False,
            "real_submit_allowed":False,"external_publish_allowed":False}
