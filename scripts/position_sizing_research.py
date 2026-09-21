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
