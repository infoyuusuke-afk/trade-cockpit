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
