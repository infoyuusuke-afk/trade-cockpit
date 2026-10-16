"""Fail-closed read-only multi-source observation evidence, not market authentication.

No broker, no runtime mutation. This module NEVER infers a tick from a
source's health status, and no source alone proves full data coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone
from scripts.local_source_health_contract import validate

EXPECTED = frozenset({"collector", "watcher", "gateway", "brain"})
MAX_AGE_SECONDS = 60
MAX_CLOCK_SKEW_SECONDS = 15


def _datetime(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("NAIVE_DATETIME")
        return stamp.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("UNVERIFIED_TIMESTAMP") from exc


def evaluate_source_evidence(snapshots, now, required_sources=EXPECTED):
    """Validate 4 source-health receipts and enforce cross-source consistency.

    The result never marks source_authenticated or order allowed. All output
    contains only allowlisted status codes and timing evidence, not raw rows.
    """
    if not isinstance(snapshots, list):
        raise ValueError("SNAPSHOTS_NOT_LIST")
    if isinstance(required_sources, (str, bytes)) or not set(required_sources) <= EXPECTED:
        raise ValueError("INVALID_REQUIRED_SOURCES")
    decision_time = _datetime(now)
    receipts = {}
    reasons = []
    for entry in snapshots:
        if not validate(entry):
            reasons.append("SOURCE_HEALTH_SCHEMA_INVALID")
            continue
        source = entry["source"].lower()
        if source not in EXPECTED or source in receipts:
            reasons.append("UNKNOWN_OR_DUPLICATE_SOURCE")
            continue
        receipts[source] = entry
    missing = sorted(set(required_sources) - set(receipts))
    if missing:
        reasons.append("REQUIRED_SOURCE_MISSING")
    details = {}
    stamps = []
    for source, receipt in sorted(receipts.items()):
        observed = _datetime(receipt["observed_at"])
        last = _datetime(receipt.get("last_data_at")) if receipt.get("last_data_at") else None
        obs_age = (decision_time - observed).total_seconds()
        last_age = (decision_time - last).total_seconds() if last else None
        status = "OK"
        if obs_age < 0 or obs_age > MAX_AGE_SECONDS:
            status = "HEALTH_RECEIPT_STALE_OR_FUTURE"
        elif last is None or last_age < 0 or last_age > MAX_AGE_SECONDS:
            status = "SOURCE_DATA_STALE_OR_UNKNOWN"
        elif last > observed:
            status = "LAST_DATA_AFTER_HEALTH_RECEIPT"
        elif receipt["state"] != "HEALTHY" or receipt["consecutive_failures"] != 0:
            status = "SOURCE_NOT_HEALTHY"
        if status != "OK":
            reasons.append(status)
        else:
            stamps.append(last)
        details[source] = {
            "status": status,
            "observed_age_seconds": round(obs_age, 3),
            "last_data_age_seconds": round(last_age, 3) if last_age is not None else None,
        }
    if len(stamps) > 1 and (max(stamps)-min(stamps)).total_seconds() > MAX_CLOCK_SKEW_SECONDS:
        reasons.append("CROSS_SOURCE_TIME_DISAGREEMENT")
    if len(receipts) != len(EXPECTED):
        reasons.append("UNVERIFIED_SOURCE_SET")
    unique = sorted(set(reasons))
    return {
        "status": "OBSERVATION_CANDIDATE_ONLY" if not unique else "BLOCKED",
        "reasons": unique,
        "source_status": details,
        "required_sources": sorted(required_sources),
        "missing_sources": missing,
        "cross_source_join_allowed": False,
        "source_authenticated": False,
        "promotion_eligible": False,
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
    }
