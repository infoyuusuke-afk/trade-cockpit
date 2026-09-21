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
