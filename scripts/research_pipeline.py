#!/usr/bin/env python3
"""Integrated research pipeline: regime -> transition -> gate -> outcome attribution."""
from scripts.regime_transition import detect_regime_transition
from scripts.regime_pretrade_gate import regime_aware_pretrade_gate
from scripts.ev_break_attribution import attribute_trade_breaks,audit_preventability

def evaluate_research_trade(signal,completed_checks,regime_context,history,
                            today_features,transition_features,break_events=None,
                            required_pretrade_checks=None):
    transition=detect_regime_transition(
        history,today_features,transition_features,
        min_history=regime_context.get("min_history",5),
        distance_threshold=regime_context.get("distance_threshold",2.0),
        min_persistence=regime_context.get("min_persistence",2))
    ctx=dict(regime_context)
    ctx["regime_shift_candidate"]=transition.get("status")=="TRANSITION_CANDIDATE"
    gate=regime_aware_pretrade_gate(signal,completed_checks,ctx)
    result={"trade_id":signal.get("trade_id"),
            "decision_ts":signal.get("decision_ts"),
            "transition":transition,"pretrade_gate":gate,
            "research_only":True,"auto_execute":False}
    if not gate["gate_pass"]:
        result["pipeline_status"]="BLOCKED_PRETRADE"
        result["promotion_eligible"]=False
        return result
    result["pipeline_status"]="RESEARCH_SIGNAL_ACCEPTED"
    result["promotion_eligible"]=False
    if signal.get("net_pnl") is not None and signal.get("decision_ts"):
        trade={"trade_id":signal.get("trade_id"),"decision_ts":signal["decision_ts"],
               "net_pnl":signal["net_pnl"],
               "pretrade_checks_completed":completed_checks}
        events=break_events or []
        result["break_attribution"]=attribute_trade_breaks(trade,events)
        result["preventability"]=audit_preventability(
            trade,events,required_pretrade_checks or gate["required_checks"])
    return result
