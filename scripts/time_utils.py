#!/usr/bin/env python3
"""Fail-closed timestamp normalization for Japanese-market research."""
from datetime import datetime, timezone, timedelta

JST=timezone(timedelta(hours=9))

def parse_market_ts(value, naive_timezone=JST):
    s=str(value).strip()
    if not s:
        raise ValueError("empty timestamp")
    try:
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
    except ValueError as e:
        raise ValueError("unparseable timestamp: "+s) from e
    if dt.tzinfo is None:
        if naive_timezone is None:
            raise ValueError("naive timestamp without declared timezone")
        dt=dt.replace(tzinfo=naive_timezone)
    return dt.astimezone(JST)

def assert_observed_by(observed_at, decision_ts):
    obs=parse_market_ts(observed_at)
    dec=parse_market_ts(decision_ts)
    if obs>dec:
        raise ValueError("future information")
    return obs,dec
