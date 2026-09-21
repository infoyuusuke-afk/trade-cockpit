#!/usr/bin/env python3
"""Point-in-time contract for pre-open research features."""
from datetime import datetime

ALLOWED_PREOPEN_FIELDS={
 "gap_pct","prior_day_range_pct","prior_day_volume","prior_day_turnover",
 "pts_return_pct","us_market_return_pct","us_semiconductor_return_pct",
 "futures_return_pct","margin_buy_shares","margin_sell_shares","margin_ratio",
 "known_catalyst_score","rumor_state"
}

def validate_preopen_context(context, decision_ts):
    decision=datetime.fromisoformat(str(decision_ts).replace("Z","+00:00"))
    values=context.get("values",{})
    observed=context.get("observed_at",{})
    unknown=set(values)-ALLOWED_PREOPEN_FIELDS
    if unknown:
        raise ValueError("preopen field not allowlisted: "+",".join(sorted(unknown)))
    for key in values:
        if key not in observed:
            raise ValueError("missing observed_at for "+key)
        ts=datetime.fromisoformat(str(observed[key]).replace("Z","+00:00"))
        if ts>decision:
            raise ValueError("future information for "+key)
    return values.copy()
