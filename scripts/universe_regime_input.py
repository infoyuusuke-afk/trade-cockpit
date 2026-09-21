#!/usr/bin/env python3
"""Normalize Daytrade Top100 + AI Cockpit tab membership for regime research."""

def normalize_universe_row(row):
    required=("as_of","symbol","source")
    missing=[k for k in required if not row.get(k)]
    if missing: raise ValueError("missing: "+",".join(missing))
    source=str(row["source"]).upper()
    if source not in ("DAYTRADE_TOP100","COCKPIT_TAB"):
        raise ValueError("unsupported universe source")
    return {
      "as_of":str(row["as_of"]),
      "symbol":str(row["symbol"]),
      "name":row.get("name"),
      "source":source,
      "source_rank":None if row.get("source_rank") is None else int(row["source_rank"]),
      "cockpit_tab":row.get("cockpit_tab"),
      "declared_category":row.get("declared_category"),
      "research_only":True,
    }

def combine_universes(rows):
    """Keep provenance while combining duplicate symbols for the same snapshot."""
    out={}
    for raw in rows:
        r=normalize_universe_row(raw)
        key=(r["as_of"],r["symbol"])
        x=out.setdefault(key,{"as_of":r["as_of"],"symbol":r["symbol"],"name":r["name"],
                              "sources":[],"top100_rank":None,"cockpit_tabs":[],
                              "declared_categories":[],"research_only":True})
        if r["source"] not in x["sources"]: x["sources"].append(r["source"])
        if r["source"]=="DAYTRADE_TOP100": x["top100_rank"]=r["source_rank"]
        if r["cockpit_tab"] and r["cockpit_tab"] not in x["cockpit_tabs"]:
            x["cockpit_tabs"].append(r["cockpit_tab"])
        if r["declared_category"] and r["declared_category"] not in x["declared_categories"]:
            x["declared_categories"].append(r["declared_category"])
    return list(out.values())

def detect_regime_mismatch(universe_row, empirical_cluster, expected_cluster_map):
    """Declared categories are context, never ground truth."""
    expected={expected_cluster_map[c] for c in universe_row.get("declared_categories",[])
              if c in expected_cluster_map}
    mismatch=bool(expected) and empirical_cluster not in expected
    return {"symbol":universe_row["symbol"],"empirical_cluster":empirical_cluster,
            "expected_clusters":sorted(expected),"regime_shift_candidate":mismatch,
            "research_only":True}
