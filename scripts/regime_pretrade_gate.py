#!/usr/bin/env python3
"""Map empirical participant-regime evidence to pretrade requirements."""
from scripts.pretrade_gate import pretrade_gate

TAG_RULES={
 "HIGH_PRICE":[],
 "HIGH_TURNOVER":[],
 "HIGH_VOL":[],
 "OPEN_CONCENTRATED":[],
 "INDEX_SENSITIVE":["INDEX_SENSITIVE"],
}
CLUSTER_RULES={
 "SEMICON":["SEMICON"],
 "SEMICON_HIGH_VOL":["SEMICON"],
 "INDEX_FLOW":["INDEX_SENSITIVE"],
}

def derive_gate_tags(regime_tags=None, empirical_cluster=None, declared_categories=None):
    out=set()
    for tag in regime_tags or []:
        out.update(TAG_RULES.get(tag,[]))
    if empirical_cluster:
        out.update(CLUSTER_RULES.get(empirical_cluster,[]))
    # Declared categories are context only: they may add safety checks, never remove them.
    for cat in declared_categories or []:
        c=str(cat).upper()
        if "SEMICON" in c or "半導体" in str(cat):
            out.add("SEMICON")
        if "INDEX" in c or "指数" in str(cat):
            out.add("INDEX_SENSITIVE")
    return sorted(out)

def regime_aware_pretrade_gate(signal, completed_checks, regime_context):
    tags=derive_gate_tags(regime_context.get("regime_tags"),
                          regime_context.get("empirical_cluster"),
                          regime_context.get("declared_categories"))
    result=pretrade_gate(signal,completed_checks,tags)
    result["derived_gate_tags"]=tags
    result["empirical_cluster"]=regime_context.get("empirical_cluster")
    result["regime_shift_candidate"]=bool(regime_context.get("regime_shift_candidate",False))
    result["declared_category_is_ground_truth"]=False
    return result
