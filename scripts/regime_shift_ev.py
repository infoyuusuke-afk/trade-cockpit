#!/usr/bin/env python3
"""Research-only regime-shift EV attribution."""

def summarize_returns(values):
    vals=[float(x) for x in values]
    if not vals:
        return {"N":0,"avg_net_pnl":None,"win_rate":None,"profit_factor":None,
                "evidence_status":"REFERENCE_ONLY"}
    wins=[x for x in vals if x>0]; losses=[x for x in vals if x<0]
    pf=(sum(wins)/abs(sum(losses))) if losses else (float("inf") if wins else None)
    return {"N":len(vals),"avg_net_pnl":sum(vals)/len(vals),
            "win_rate":len(wins)/len(vals),"profit_factor":pf,
            "evidence_status":"INITIAL_EVIDENCE" if len(vals)>=30 else "REFERENCE_ONLY"}

def compare_regime_shift_ev(trades):
    """Compare stable-regime vs shift-candidate observations without causal claims."""
    stable=[t["net_pnl"] for t in trades if not t.get("regime_shift_candidate",False)]
    shifted=[t["net_pnl"] for t in trades if t.get("regime_shift_candidate",False)]
    a=summarize_returns(stable); b=summarize_returns(shifted)
    delta=None
    if a["avg_net_pnl"] is not None and b["avg_net_pnl"] is not None:
        delta=b["avg_net_pnl"]-a["avg_net_pnl"]
    return {"stable":a,"shift_candidate":b,"avg_pnl_delta":delta,
            "causal_claim":False,"research_only":True,"auto_execute":False}

def stratify_shift_ev(trades):
    """Preserve setup/time/cluster context instead of pooling incompatible trades."""
    groups={}
    for t in trades:
        key=(t["setup"],t["time_bucket"],t["empirical_cluster"])
        groups.setdefault(key,[]).append(t)
    out=[]
    for (setup,time_bucket,cluster),rows in sorted(groups.items()):
        x=compare_regime_shift_ev(rows)
        out.append({"setup":setup,"time_bucket":time_bucket,
                    "empirical_cluster":cluster,**x})
    return out
