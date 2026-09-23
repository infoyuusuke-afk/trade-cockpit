"""Reduce Owner interaction to material exceptions and approvals."""
SEVERITY={"INFO":0,"ATTENTION":1,"BLOCKING":2,"CRITICAL":3}
def build_inbox(events):
    out=[]
    for e in events:
        sev=e.get("severity","INFO")
        if sev not in SEVERITY: raise ValueError("INVALID_SEVERITY")
        requires=bool(e.get("owner_authority_required",False))
        if SEVERITY[sev] >= 2 or requires:
            out.append({"code":e.get("code"),"severity":sev,"summary":e.get("summary",""),
                        "owner_authority_required":requires,
                        "suggested_action":e.get("suggested_action","REVIEW")})
    return sorted(out,key=lambda x:(-SEVERITY[x["severity"]],str(x["code"])))
