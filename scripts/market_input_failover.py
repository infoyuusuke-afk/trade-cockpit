"""Select an approved sanitized market input without silently mixing disagreeing sources."""
def choose(candidates):
    usable=[x for x in candidates if x.get("health")=="OK" and x.get("verified") is True]
    if not usable:
        return {"status":"WAIT_DATA","selected":None,"incident_code":"NO_HEALTHY_SOURCE","owner_action_required":False}
    usable=sorted(usable,key=lambda x:(x.get("priority",999),x.get("source","")))
    best=usable[0]
    peers=[x for x in usable if x.get("priority",999)==best.get("priority",999)]
    values={x.get("fingerprint") for x in peers if x.get("fingerprint")}
    if len(values)>1:
        return {"status":"SAFE","selected":None,"incident_code":"SOURCE_DISAGREEMENT","owner_action_required":False}
    return {"status":"READY","selected":best.get("source"),"incident_code":None,
            "owner_action_required":False,"real_submit_allowed":False}
