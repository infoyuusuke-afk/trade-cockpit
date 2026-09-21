#!/usr/bin/env python3
"""Research-only staged position sizing comparison. Never emits live orders."""

def simulate_staged_long(rows, stages, exit_index=None):
    if not rows: raise ValueError("rows required")
    if not stages: raise ValueError("stages required")
    total=sum(float(s["weight"]) for s in stages)
    if abs(total-1.0)>1e-9: raise ValueError("stage weights must sum to 1")
    fills=[]
    for s in stages:
        i=int(s["index"])
        if i<0 or i>=len(rows): raise ValueError("stage index out of range")
        fills.append((i,float(s["weight"]),float(rows[i]["open"])))
    end=len(rows)-1 if exit_index is None else int(exit_index)
    if end<max(i for i,_,_ in fills): raise ValueError("exit before final stage")
    avg=sum(w*p for _,w,p in fills)
    exit_px=float(rows[end]["close"])
    pnl=(exit_px/avg-1)*100
    path=rows[min(i for i,_,_ in fills):end+1]
    mae=(min(float(r["low"]) for r in path)/avg-1)*100
    mfe=(max(float(r["high"]) for r in path)/avg-1)*100
    return {"avg_entry":avg,"exit":exit_px,"net_pnl_pct_before_cost":pnl,
            "mae_pct":mae,"mfe_pct":mfe,"capital_weight":total,
            "stage_count":len(fills),"research_only":True}

def compare_fixed_vs_staged(rows, add_indices):
    fixed=simulate_staged_long(rows,[{"index":0,"weight":1.0}])
    if len(add_indices)!=3: raise ValueError("25/25/50 requires three indices")
    staged=simulate_staged_long(rows,[
      {"index":add_indices[0],"weight":0.25},
      {"index":add_indices[1],"weight":0.25},
      {"index":add_indices[2],"weight":0.50},
    ])
    return {"FIXED":fixed,"STAGED_25_25_50":staged,"research_only":True}


VALID_LEVELS=("VWAP","OR5_LOW","OR15_LOW","PRIOR_LOW","PIVOT")

def validate_add_signal(signal):
    """Require price-level context; MS2 absorption can strengthen but not be invented."""
    level=signal.get("level")
    if level not in VALID_LEVELS:
        raise ValueError("unsupported add level")
    if not bool(signal.get("level_reaction_confirmed")):
        return {"eligible":False,"reason":"NO_LEVEL_REACTION","evidence_tier":"PRICE_ONLY"}
    absorption=signal.get("sell_absorption_confirmed")
    source=signal.get("absorption_source")
    if absorption is True and source!="MS2":
        raise ValueError("sell absorption requires MS2 evidence")
    tier="MS2_ABSORPTION" if absorption is True else "PRICE_LEVEL_ONLY"
    return {"eligible":True,"reason":"LEVEL_REACTION_CONFIRMED","evidence_tier":tier,
            "research_only":True}

def gated_staged_long(rows, stage_signals):
    if len(stage_signals)!=3:
        raise ValueError("25/25/50 requires three stage signals")
    indices=[]
    audits=[]
    for s in stage_signals:
        gate=validate_add_signal(s)
        audits.append({**gate,"index":s.get("index"),"level":s.get("level")})
        if not gate["eligible"]:
            return {"executed":False,"reason":"ADD_GATE_BLOCKED","audit":audits,
                    "research_only":True}
        indices.append(int(s["index"]))
    result=compare_fixed_vs_staged(rows,indices)
    return {"executed":True,"result":result,"audit":audits,"research_only":True}


def evaluate_long_exit_policies(rows, avg_entry, start_index, tick_size, vwap_values=None, cost_pct=0.0):
    """Compare fixed research exits without selecting a winner."""
    if tick_size<=0: raise ValueError("tick_size must be positive")
    if start_index<0 or start_index>=len(rows): raise ValueError("bad start_index")
    candidates={}
    target=avg_entry+tick_size
    tick_i=next((i for i in range(start_index,len(rows)) if float(rows[i]["high"])>=target),None)
    if tick_i is not None:
        candidates["ONE_TICK"]=(tick_i,target)
    if vwap_values is not None:
        if len(vwap_values)!=len(rows): raise ValueError("vwap length mismatch")
        vi=next((i for i in range(start_index,len(rows))
                 if vwap_values[i] is not None and float(rows[i]["high"])>=float(vwap_values[i])),None)
        if vi is not None:
            candidates["VWAP_REVERSION"]=(vi,float(vwap_values[vi]))
    candidates["EOD"]=(len(rows)-1,float(rows[-1]["close"]))
    out=[]
    for policy,(i,px) in candidates.items():
        gross=(px/avg_entry-1)*100
        path=rows[start_index:i+1]
        out.append({"exit_policy":policy,"exit_index":i,"exit_price":px,
                    "gross_pnl_pct":gross,"cost_pct":cost_pct,
                    "net_pnl_pct":gross-cost_pct,
                    "mae_pct":(min(float(r["low"]) for r in path)/avg_entry-1)*100,
                    "research_only":True})
    return out


def sizing_kill_switch(state, limits):
    """Fail-closed research risk gate. Any breach blocks further adds."""
    reasons=[]
    if not bool(state.get("data_fresh",False)):
        reasons.append("DATA_STALE_OR_UNKNOWN")
    if bool(state.get("support_broken",False)):
        reasons.append("SUPPORT_BROKEN")
    trade_loss=float(state.get("trade_pnl_pct",0))
    day_loss=float(state.get("day_pnl_pct",0))
    max_trade_loss=abs(float(limits.get("max_trade_loss_pct",0)))
    max_day_loss=abs(float(limits.get("max_day_loss_pct",0)))
    if max_trade_loss<=0 or max_day_loss<=0:
        reasons.append("INVALID_RISK_LIMITS")
    else:
        if trade_loss<=-max_trade_loss:
            reasons.append("MAX_TRADE_LOSS")
        if day_loss<=-max_day_loss:
            reasons.append("MAX_DAY_LOSS")
    return {"kill":bool(reasons),"allow_add":not reasons,"reasons":reasons,
            "research_only":True,"auto_execute":False}

def gated_add_with_risk(signal, state, limits):
    risk=sizing_kill_switch(state,limits)
    if risk["kill"]:
        return {"eligible":False,"reason":"RISK_KILL_SWITCH","risk":risk,
                "research_only":True,"auto_execute":False}
    gate=validate_add_signal(signal)
    return {**gate,"risk":risk,"auto_execute":False}


def risk_response(state, limits):
    """Map risk evidence to a research response; never submits an order."""
    risk=sizing_kill_switch(state,limits)
    reasons=set(risk["reasons"])
    exit_reasons={"SUPPORT_BROKEN","MAX_TRADE_LOSS","MAX_DAY_LOSS"}
    if reasons & exit_reasons:
        response="EXIT_REQUIRED"
    elif "DATA_STALE_OR_UNKNOWN" in reasons or "INVALID_RISK_LIMITS" in reasons:
        response="FREEZE_NO_NEW_RISK"
    else:
        response="CONTINUE"
    return {"risk_response":response,"reasons":risk["reasons"],
            "allow_add":response=="CONTINUE","research_only":True,
            "auto_execute":False}

def evaluate_kill_switch_impact(rows, trigger_index, avg_entry, hypothetical_exit_index=None):
    """Measure trigger exit versus holding longer; descriptive counterfactual only."""
    if trigger_index<0 or trigger_index>=len(rows): raise ValueError("bad trigger_index")
    hold_i=len(rows)-1 if hypothetical_exit_index is None else int(hypothetical_exit_index)
    if hold_i<trigger_index or hold_i>=len(rows): raise ValueError("bad hypothetical_exit_index")
    trigger_px=float(rows[trigger_index]["close"])
    hold_px=float(rows[hold_i]["close"])
    trigger_pnl=(trigger_px/avg_entry-1)*100
    hold_pnl=(hold_px/avg_entry-1)*100
    return {"trigger_exit_pnl_pct":trigger_pnl,"hold_pnl_pct":hold_pnl,
            "loss_avoided_pct":trigger_pnl-hold_pnl,
            "trigger_index":trigger_index,"hold_index":hold_i,
            "research_only":True}
