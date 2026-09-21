#!/usr/bin/env python3
"""Point-in-time contract for pre-open research features."""
from scripts.time_utils import parse_market_ts

ALLOWED_PREOPEN_FIELDS={
 "gap_pct","prior_day_range_pct","prior_day_volume","prior_day_turnover",
 "pts_return_pct","us_market_return_pct","us_semiconductor_return_pct",
 "futures_return_pct","margin_buy_shares","margin_sell_shares","margin_ratio",
 "known_catalyst_score","rumor_state"
}

DEFAULT_MAX_AGE_SEC={
 "gap_pct":3600,"prior_day_range_pct":129600,"prior_day_volume":129600,"prior_day_turnover":129600,
 "pts_return_pct":43200,"us_market_return_pct":43200,"us_semiconductor_return_pct":43200,
 "futures_return_pct":900,"margin_buy_shares":259200,"margin_sell_shares":259200,"margin_ratio":259200,
 "known_catalyst_score":604800,"rumor_state":86400
}

def validate_preopen_context(context, decision_ts):
    decision=parse_market_ts(decision_ts)
    values=context.get("values",{})
    observed=context.get("observed_at",{})
    unknown=set(values)-ALLOWED_PREOPEN_FIELDS
    if unknown:
        raise ValueError("preopen field not allowlisted: "+",".join(sorted(unknown)))
    for key in values:
        if key not in observed:
            raise ValueError("missing observed_at for "+key)
        ts=parse_market_ts(observed[key])
        if ts>decision:
            raise ValueError("future information for "+key)
        age=(decision-ts).total_seconds()
        max_age=context.get("max_age_sec",{}).get(key,DEFAULT_MAX_AGE_SEC[key])
        if age>max_age:
            raise ValueError("stale information for "+key)
    return values.copy()
