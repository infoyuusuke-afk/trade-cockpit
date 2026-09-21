#!/usr/bin/env python3
"""Research-only dynamic participant-regime transition detector."""
import math

def _distance(a,b,features):
    vals=[]
    for f in features:
        if a.get(f) is None or b.get(f) is None: continue
        vals.append((float(a[f])-float(b[f]))**2)
    return math.sqrt(sum(vals)) if vals else None

def detect_regime_transition(history,today,features,min_history=5,
                             distance_threshold=2.0,min_persistence=2):
    """History should contain already-normalized comparable feature rows."""
    if len(history)<min_history:
        return {"status":"INSUFFICIENT_HISTORY","history_n":len(history),
                "research_only":True,"auto_execute":False}
    recent=history[-min_history:]
    centroid={}
    for f in features:
        xs=[float(r[f]) for r in recent if r.get(f) is not None]
        centroid[f]=sum(xs)/len(xs) if xs else None
    distance=_distance(today,centroid,features)
    prior_cluster=recent[-1].get("empirical_cluster")
    today_cluster=today.get("empirical_cluster")
    cluster_changed=bool(prior_cluster and today_cluster and prior_cluster!=today_cluster)
    distant=distance is not None and distance>=distance_threshold
    prior_candidates=sum(1 for r in recent[-min_persistence:]
                         if r.get("transition_watch",False))
    persistent=(prior_candidates+int(distant and cluster_changed))>=min_persistence
    if distant and cluster_changed and persistent:
        status="TRANSITION_CANDIDATE"
    elif distant or cluster_changed:
        status="WATCH"
    else:
        status="STABLE"
    return {"status":status,"history_n":len(history),"distance":distance,
            "distance_threshold":distance_threshold,
            "prior_cluster":prior_cluster,"today_cluster":today_cluster,
            "cluster_changed":cluster_changed,"persistent":persistent,
            "causal_claim":False,"research_only":True,"auto_execute":False}
