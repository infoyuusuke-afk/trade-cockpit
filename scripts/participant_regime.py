#!/usr/bin/env python3
"""Research-only stock/participant regime features.

Uses observable market features. Does not infer investor identity or intent.
"""

REQUIRED=("price","turnover","opening_volume_share","or5_width_pct",
          "or15_width_pct","vwap_reversion_rate","intraday_range_pct")

def build_regime_features(row):
    missing=[k for k in REQUIRED if row.get(k) is None]
    if missing:
        return {"eligible":False,"missing":missing,"research_only":True}
    out={k:float(row[k]) for k in REQUIRED}
    for k in ("avg_trade_size","spread_bps","short_ratio","margin_ratio",
              "afternoon_volume_share","gap_pct","index_contribution"):
        out[k]=None if row.get(k) is None else float(row[k])
    return {"eligible":True,"features":out,"research_only":True}

def descriptive_regime_tags(features):
    """Broad descriptive tags only; thresholds are explicit hypotheses."""
    f=features
    tags=[]
    if f["price"]>=10000: tags.append("HIGH_PRICE")
    if f["turnover"]>=50_000_000_000: tags.append("HIGH_TURNOVER")
    if f["intraday_range_pct"]>=5: tags.append("HIGH_VOL")
    if f["opening_volume_share"]>=0.25: tags.append("OPEN_CONCENTRATED")
    if f.get("index_contribution") is not None and abs(f["index_contribution"])>=1:
        tags.append("INDEX_SENSITIVE")
    return tags or ["UNCLASSIFIED"]

def hierarchical_ev_key(symbol, regime_id, market_regime, time_bucket, setup):
    if not all((symbol,regime_id,market_regime,time_bucket,setup)):
        raise ValueError("complete hierarchy required")
    return {
      "market_key":f"ALL|{market_regime}|{time_bucket}|{setup}",
      "cluster_key":f"REGIME:{regime_id}|{market_regime}|{time_bucket}|{setup}",
      "symbol_key":f"{symbol}|REGIME:{regime_id}|{market_regime}|{time_bucket}|{setup}",
      "research_only":True,
    }
