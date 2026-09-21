#!/usr/bin/env python3
"""Validate layered research inputs without inventing unavailable evidence."""
CORE=("symbol","market_date","timestamp","open","high","low","close","volume")
MICRO=("quote_state","bid_depth","ask_depth","aggressive_buy_volume",
       "aggressive_sell_volume","trade_count","avg_trade_size","spread_bps","observed_at")

def validate_research_input(row):
    missing=[k for k in CORE if row.get(k) in (None,"")]
    if missing:
        return {"valid":False,"missing_core":missing,"available_layers":[],
                "research_only":True,"auto_execute":False}
    layers=["CORE"]
    context_keys=("top100_rank","cockpit_tabs","declared_categories","turnover","gap_pct",
                  "market_return_pct","futures_return_pct","us_semiconductor_return_pct",
                  "korea_semiconductor_return_pct","known_catalyst_score","rumor_state")
    if any(row.get(k) is not None for k in context_keys): layers.append("CONTEXT")
    micro_present=[k for k in MICRO if row.get(k) is not None]
    if micro_present:
        if row.get("microstructure_source")!="MS2":
            return {"valid":False,"missing_core":[],"available_layers":layers,
                    "error":"MICROSTRUCTURE_REQUIRES_MS2_SOURCE",
                    "research_only":True,"auto_execute":False}
        if not row.get("observed_at"):
            return {"valid":False,"missing_core":[],"available_layers":layers,
                    "error":"MICROSTRUCTURE_REQUIRES_OBSERVED_AT",
                    "research_only":True,"auto_execute":False}
        layers.append("MICROSTRUCTURE")
    return {"valid":True,"missing_core":[],"available_layers":layers,
            "microstructure_evidence":("MICROSTRUCTURE" in layers),
            "research_only":True,"auto_execute":False}
