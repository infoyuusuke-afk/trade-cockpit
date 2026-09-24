from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

LIVE = "LIVE"
DELAYED = "DELAYED"
STALE = "STALE"
INVALID = "INVALID"

TTL_SECONDS = {
    "ms2_quote": 15,
    "intraday_market": 60,
    "fx": 60,
    "news": 300,
    "ir": 900,
    "daily_market": 36 * 3600,
    "weekly_supply": 10 * 24 * 3600,
    "policy": 30 * 24 * 3600,
}

@dataclass(frozen=True)
class Freshness:
    status: str
    age_seconds: float | None
    expires_at: str | None
    usable: bool
    reason: str

def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return dt.astimezone(JST)
    except (TypeError, ValueError):
        return None

def assess_freshness(kind: str, observed_at: str | None, now: datetime | None = None,
                     source_ok: bool = True) -> Freshness:
    now = (now or datetime.now(JST)).astimezone(JST)
    observed = _parse(observed_at)
    ttl = TTL_SECONDS.get(kind)
    if not source_ok:
        return Freshness(INVALID, None, None, False, "source verification failed")
    if ttl is None:
        return Freshness(INVALID, None, None, False, f"unknown freshness kind: {kind}")
    if observed is None:
        return Freshness(INVALID, None, None, False, "observed_at missing or invalid")
    age = (now - observed).total_seconds()
    expires = observed + timedelta(seconds=ttl)
    if age < -5:
        return Freshness(INVALID, age, expires.isoformat(), False, "observation is in the future")
    if age <= ttl:
        return Freshness(LIVE, max(age, 0), expires.isoformat(), True, "within ttl")
    if age <= ttl * 2:
        return Freshness(DELAYED, age, expires.isoformat(), False, "past ttl")
    return Freshness(STALE, age, expires.isoformat(), False, "expired")

def gate_payload(payload: dict, kind: str, now: datetime | None = None,
                 observed_key: str = "observed_at", source_ok: bool = True) -> dict:
    result = assess_freshness(kind, payload.get(observed_key), now=now, source_ok=source_ok)
    out = dict(payload)
    out["freshness_status"] = result.status
    out["freshness_age_seconds"] = result.age_seconds
    out["expires_at"] = result.expires_at
    out["freshness_reason"] = result.reason
    out["display_as_current"] = result.usable
    if not result.usable:
        out["current_value"] = None
    return out
