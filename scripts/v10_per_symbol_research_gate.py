"""Isolated, synthetic-only V10 per-symbol observation research gate.

Stage A of coordinator D-026 / Issue #282 decision 6286617491. This is a
pure policy library, not a Collector adapter, durable writer, signal, order
permission, or production runtime integration. Never infer exchange ticks
from a Collector heartbeat. The caller must independently establish source
and workbook identity; a dict supplied here is not authentication.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import re

SOURCE_ID = "MS2_RSS_WORKBOOK"
SCHEMA = "v10-per-symbol-research-0.1"
ACQUISITION_TTL = timedelta(seconds=12)
EVIDENCE_TTL = timedelta(seconds=120)
_TICKER = re.compile(r"^[0-9A-Z]{4,5}(?:\.T)?$")


def _instant(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    return stamp.astimezone(timezone.utc)


def _now(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _acquisition_status(receipt, now):
    if not isinstance(receipt, dict):
        return "ACQUISITION_MISSING"
    if (receipt.get("source_id") != SOURCE_ID
            or receipt.get("workbook_identity_verified") is not True
            or receipt.get("data_conflict") is not False
            or receipt.get("real_submit_allowed") is not False
            or not isinstance(receipt.get("session_id"), str)
            or not receipt["session_id"].strip()):
        return "ACQUISITION_IDENTITY_UNVERIFIED"
    observed = _instant(receipt.get("observed_at"))
    available = _instant(receipt.get("available_at"))
    if observed is None or available is None or not observed <= available <= now:
        return "ACQUISITION_PIT_INVALID"
    if now - observed > ACQUISITION_TTL or now - available > ACQUISITION_TTL:
        return "ACQUISITION_STALE"
    return "FRESH"


def _evidence_status(proof, receipt, now):
    if not isinstance(proof, dict):
        return "MISSING"
    if (proof.get("source_id") != SOURCE_ID
            or proof.get("session_id") != receipt.get("session_id")
            or proof.get("source_timestamp_basis") != "COLLECTOR_OBSERVED_CHANGE"):
        return "LINEAGE_UNVERIFIED"
    source = _instant(proof.get("source_at"))
    observed = _instant(proof.get("observed_at"))
    available = _instant(proof.get("available_at"))
    if source is None or observed is None or available is None:
        return "PIT_INVALID"
    if not source <= observed <= available <= now:
        return "PIT_INVALID"
    if now - source > EVIDENCE_TTL or now - available > EVIDENCE_TTL:
        return "STALE"
    price = proof.get("value")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return "VALUE_INVALID"
    if not math.isfinite(price) or price <= 0:
        return "VALUE_INVALID"
    return "FRESH"


def evaluate_universe(universe, acquisition, observations, *, as_of):
    """Return conservative coverage/verdicts, never a trade-ready decision.

    Universe is exactly the externally approved 100 names; this module never
    selects, removes or replaces names. A current Collector receipt cannot
    refresh an unchanged per-symbol trade or quote. Quote-only research may
    proceed when independently verified quote evidence is fresh while the
    last trade is old; trade-dependent research stays blocked.
    """
    now = _now(as_of)
    if (not isinstance(universe, (tuple, list)) or len(universe) != 100
            or any(not isinstance(t, str) or not _TICKER.fullmatch(t) for t in universe)
            or len(set(universe)) != 100):
        raise ValueError("exactly 100 distinct canonical symbols required")
    if not isinstance(observations, list):
        raise ValueError("observations must be a list")
    allowed = set(universe)
    grouped = {}
    unexpected = 0
    for row in observations:
        if not isinstance(row, dict) or row.get("ticker") not in allowed:
            unexpected += 1
            continue
        grouped.setdefault(row["ticker"], []).append(row)
    acq_status = _acquisition_status(acquisition, now)
    verdicts = {}
    quote_count = trade_count = joint_count = 0
    missing_count = duplicate_count = 0
    for ticker in universe:
        matches = grouped.get(ticker, [])
        if not matches:
            missing_count += 1
            q_status = t_status = "MISSING"
        elif len(matches) != 1:
            duplicate_count += 1
            q_status = t_status = "DUPLICATE_SYMBOL"
        elif acq_status != "FRESH":
            q_status = t_status = "ACQUISITION_BLOCKED"
        else:
            q_status = _evidence_status(matches[0].get("quote"), acquisition, now)
            t_status = _evidence_status(matches[0].get("last_trade"), acquisition, now)
        quote_ready = acq_status == "FRESH" and q_status == "FRESH"
        trade_ready = acq_status == "FRESH" and t_status == "FRESH"
        both_ready = quote_ready and trade_ready
        quote_count += int(quote_ready)
        trade_count += int(trade_ready)
        joint_count += int(both_ready)
        verdicts[ticker] = {
            "quote_status": q_status,
            "last_trade_status": t_status,
            "quote_research_eligible": quote_ready,
            "trade_research_eligible": trade_ready,
            "joint_research_eligible": both_ready,
            "reason_codes": tuple(
                code for code in (
                    None if acq_status == "FRESH" else acq_status,
                    None if q_status == "FRESH" else "QUOTE_" + q_status,
                    None if t_status == "FRESH" else "TRADE_" + t_status,
                ) if code is not None
            ),
        }
    return {
        "schema_version": SCHEMA,
        "as_of": now.isoformat(),
        "acquisition_status": acq_status,
        "expected_universe_n": 100,
        "received_unique_n": len(grouped),
        "missing_n": missing_count,
        "duplicate_n": duplicate_count,
        "unexpected_n": unexpected,
        "quote_fresh_n": quote_count,
        "last_trade_fresh_n": trade_count,
        "joint_fresh_n": joint_count,
        "full_universe_quote_aggregate": (
            "READY_RESEARCH_ONLY" if quote_count == 100 and unexpected == 0 else "BLOCKED"
        ),
        "full_universe_joint_aggregate": (
            "READY_RESEARCH_ONLY" if joint_count == 100 and unexpected == 0 else "BLOCKED"
        ),
        "verdicts": verdicts,
        "real_submit_allowed": False,
        "execution_eligible": False,
        "shadow_ev_verified": False,
    }
