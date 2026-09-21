#!/usr/bin/env python3
"""Research-only EV comparison across dynamic regime-transition states."""
VALID_STATES=("STABLE","WATCH","TRANSITION_CANDIDATE","INSUFFICIENT_HISTORY")

def _stats(rows):
    pnl=[float(r["net_pnl"]) for r in rows]
    n=len(pnl)
    wins=[x for x in pnl if x>0]; losses=[x for x in pnl if x<0]
    pf=(sum(wins)/abs(sum(losses))) if losses else (float("inf") if wins else None)
    return {"N":n,"avg_net_pnl":sum(pnl)/n if n else None,
            "win_rate":len(wins)/n if n else None,"profit_factor":pf,
            "evidence_status":"INITIAL_EVIDENCE" if n>=30 else "REFERENCE_ONLY"}

def transition_strategy_ev(trades):
    """Keep setup/time/transition state separate; no winner selection."""
    groups={}
    for t in trades:
        state=t.get("transition_status","INSUFFICIENT_HISTORY")
        if state not in VALID_STATES: raise ValueError("invalid transition status")
        key=(t["setup"],t["time_bucket"],state)
        groups.setdefault(key,[]).append(t)
    return [{"setup":k[0],"time_bucket":k[1],"transition_status":k[2],
             **_stats(v),"research_only":True,"auto_execute":False}
            for k,v in sorted(groups.items())]

def compare_stable_to_transition(trades):
    """Descriptive delta only; deliberately avoids causal or superiority claims."""
    grouped={}
    for t in trades:
        key=(t["setup"],t["time_bucket"])
        grouped.setdefault(key,{}).setdefault(t.get("transition_status"),[]).append(t)
    out=[]
    for (setup,tb),states in sorted(grouped.items()):
        stable=_stats(states.get("STABLE",[]))
        trans=_stats(states.get("TRANSITION_CANDIDATE",[]))
        delta=None
        if stable["avg_net_pnl"] is not None and trans["avg_net_pnl"] is not None:
            delta=trans["avg_net_pnl"]-stable["avg_net_pnl"]
        enough=stable["N"]>=30 and trans["N"]>=30
        out.append({"setup":setup,"time_bucket":tb,"stable":stable,
                    "transition":trans,"avg_net_pnl_delta":delta,
                    "comparison_status":"INITIAL_EVIDENCE" if enough else "REFERENCE_ONLY",
                    "causal_claim":False,"winner_selected":False,
                    "research_only":True,"auto_execute":False})
    return out
