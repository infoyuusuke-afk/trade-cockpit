#!/usr/bin/env python3
"""Dependency-light research clustering for stock/day regimes."""
from math import sqrt

DEFAULT_FEATURES=("price","turnover","opening_volume_share","or5_width_pct",
                  "or15_width_pct","vwap_reversion_rate","intraday_range_pct")

def zscore_rows(rows, keys=DEFAULT_FEATURES):
    if len(rows)<2: raise ValueError("at least two rows required")
    means={k:sum(float(r[k]) for r in rows)/len(rows) for k in keys}
    std={}
    for k in keys:
        var=sum((float(r[k])-means[k])**2 for r in rows)/len(rows)
        std[k]=sqrt(var)
    out=[]
    for r in rows:
        vals={k:(float(r[k])-means[k])/std[k] if std[k]>0 else 0.0 for k in keys}
        out.append({"id":r["id"],"z":vals})
    return out

def euclidean(a,b,keys=DEFAULT_FEATURES):
    return sqrt(sum((a[k]-b[k])**2 for k in keys))

def nearest_neighbors(rows, target_id, k=5, keys=DEFAULT_FEATURES):
    z=zscore_rows(rows,keys)
    by_id={r["id"]:r["z"] for r in z}
    if target_id not in by_id: raise ValueError("target not found")
    target=by_id[target_id]
    ranked=sorted(((r["id"],euclidean(target,r["z"],keys)) for r in z if r["id"]!=target_id),
                  key=lambda x:x[1])
    return [{"id":i,"distance":d} for i,d in ranked[:k]]

def assign_fixed_k(rows, seed_ids, keys=DEFAULT_FEATURES):
    """Deterministic nearest-seed baseline; seeds must be declared before evaluation."""
    z=zscore_rows(rows,keys); by_id={r["id"]:r["z"] for r in z}
    if not seed_ids or any(s not in by_id for s in seed_ids): raise ValueError("invalid seeds")
    assignments=[]
    for r in z:
        ranked=sorted((euclidean(r["z"],by_id[s],keys),s) for s in seed_ids)
        assignments.append({"id":r["id"],"cluster_seed":ranked[0][1],
                            "distance":ranked[0][0],"research_only":True})
    return assignments
