"""Convert sanitized incidents into deterministic engineering-learning candidates."""
def learn(incidents):
    groups={}
    for x in incidents:
        if x.get("sanitized") is not True: continue
        code=x.get("code","UNKNOWN")
        g=groups.setdefault(code,{"code":code,"count":0,"recovered":0,"terminal_states":{}})
        g["count"]+=1
        if x.get("recovered") is True:g["recovered"]+=1
        state=x.get("terminal_state","UNKNOWN")
        g["terminal_states"][state]=g["terminal_states"].get(state,0)+1
    out=[]
    for code,g in sorted(groups.items()):
        g["recovery_rate"]=g["recovered"]/g["count"] if g["count"] else 0
        g["engineering_candidate"]=g["count"]>=2 or g["recovery_rate"]<1
        out.append(g)
    return out
