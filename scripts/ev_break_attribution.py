#!/usr/bin/env python3
"""Point-in-time expectation-break attribution. Descriptive, not causal."""
from scripts.time_utils import parse_market_ts

VALID_REASONS=("MARKET_REGIME_DOWNSHIFT","KOREA_SEMICON_CONTAGION",
               "US_SEMICON_CONTAGION","SURPRISE_NEGATIVE_CATALYST",
               "TIME_REGIME_SHIFT","EXECUTION_DEGRADATION",
               "SYMBOL_FLOW_REVERSAL","UNKNOWN")

def make_break_event(reason, observed_at, decision_ts, magnitude=None, evidence=None):
    if reason not in VALID_REASONS: raise ValueError("invalid break reason")
    obs=parse_market_ts(observed_at); dec=parse_market_ts(decision_ts)
    if obs<dec: phase="PREEXISTING"
    elif obs==dec: phase="AT_DECISION"
    else: phase="POST_DECISION"
    return {"reason":reason,"observed_at":obs.isoformat(),"decision_ts":dec.isoformat(),
            "phase":phase,"magnitude":magnitude,"evidence":evidence or {},
            "causal_claim":False,"research_only":True}

def attribute_trade_breaks(trade, events):
    dec=trade["decision_ts"]
    normalized=[make_break_event(e["reason"],e["observed_at"],dec,e.get("magnitude"),
                                 e.get("evidence")) for e in events]
    post=[e for e in normalized if e["phase"]=="POST_DECISION"]
    return {"trade_id":trade.get("trade_id"),"decision_ts":parse_market_ts(dec).isoformat(),
            "net_pnl":trade.get("net_pnl"),"break_events":post,
            "break_reasons":sorted({e["reason"] for e in post}) or ["UNKNOWN"],
            "causal_claim":False,"research_only":True}

def summarize_break_reasons(attributions):
    groups={}
    for a in attributions:
        for reason in a["break_reasons"]:
            groups.setdefault(reason,[]).append(float(a["net_pnl"]))
    return [{"reason":r,"N":len(v),"avg_net_pnl":sum(v)/len(v),
             "evidence_status":"INITIAL_EVIDENCE" if len(v)>=30 else "REFERENCE_ONLY",
             "causal_claim":False,"research_only":True} for r,v in sorted(groups.items())]


def audit_preventability(trade, events, required_pretrade_checks=None):
    """Separate missed observable risk from genuinely later shocks."""
    dec=parse_market_ts(trade["decision_ts"])
    checks=set(trade.get("pretrade_checks_completed",[]))
    required=set(required_pretrade_checks or [])
    missed_checks=sorted(required-checks)
    pre=[]; post=[]
    for e in events:
        obs=parse_market_ts(e["observed_at"])
        item={"reason":e["reason"],"observed_at":obs.isoformat(),
              "magnitude":e.get("magnitude"),"evidence":e.get("evidence",{})}
        (pre if obs<=dec else post).append(item)
    if pre:
        classification="MISSED_PRETRADE_RISK"
    elif missed_checks:
        classification="INCOMPLETE_PRETRADE_AUDIT"
    elif post:
        classification="POST_DECISION_SHOCK"
    else:
        classification="NO_IDENTIFIED_BREAK"
    return {"trade_id":trade.get("trade_id"),"classification":classification,
            "preexisting_risks":pre,"post_decision_events":post,
            "missed_required_checks":missed_checks,
            "preventable_claim":False,"research_only":True}

def summarize_preventability(audits):
    out={}
    for a in audits:
        k=a["classification"]; out[k]=out.get(k,0)+1
    n=len(audits)
    return {"N":n,"counts":out,
            "rates":{k:v/n for k,v in out.items()} if n else {},
            "evidence_status":"INITIAL_EVIDENCE" if n>=30 else "REFERENCE_ONLY",
            "research_only":True}
