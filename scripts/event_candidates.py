"""Normalization contract for EVENT 5 candidate handoffs.

This module does not scrape or score markets by itself. It normalizes evidence from
PTS, disclosures, earnings, prior limit states and NEXT THEME into one fail-closed
shape that EVENT 5 can consume.

Important:
- stale evidence never carries a current actionable price;
- previous limit-up/down is an upstream observed state, not guessed here;
- NEXT THEME remains research-only unless the upstream handoff is explicitly qualified;
- expectation_score is accepted only as supplied evidence, not fabricated.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

SCHEMA_VERSION = "event-candidates-1.0"

VALID_SOURCES = {
    "PTS",
    "IR",
    "EARNINGS",
    "PREV_LIMIT_UP",
    "PREV_LIMIT_DOWN",
    "NEXT_THEME",
    "MULTI_SOURCE",
}

VALID_LIMIT_STATES = {"LIMIT_UP", "LIMIT_DOWN", "NONE", "UNKNOWN"}
VALID_LIVE_CONFIRMATION = {
    "NOT_STARTED",
    "PREOPEN_CONFIRMED",
    "LIVE_CONFIRMED",
    "BLOCKED",
    "UNKNOWN",
}


def _num(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _source_set(
    *,
    pts: Mapping,
    disclosure: Mapping,
    earnings: Mapping,
    previous_limit_state: str,
    next_theme: Mapping,
) -> list[str]:
    sources = []

    if any(
        pts.get(key) is not None
        for key in ("price", "gap_pct", "turnover_yen", "liquidity_pass")
    ):
        sources.append("PTS")

    if disclosure:
        sources.append("IR")

    if earnings:
        sources.append("EARNINGS")

    if previous_limit_state == "LIMIT_UP":
        sources.append("PREV_LIMIT_UP")
    elif previous_limit_state == "LIMIT_DOWN":
        sources.append("PREV_LIMIT_DOWN")

    if next_theme:
        sources.append("NEXT_THEME")

    if len(sources) >= 2:
        sources.append("MULTI_SOURCE")

    return sources


def build_candidate(
    *,
    ticker: str,
    name: Optional[str] = None,
    pts: Optional[Mapping] = None,
    disclosure: Optional[Mapping] = None,
    earnings: Optional[Mapping] = None,
    previous_limit_state: str = "UNKNOWN",
    next_theme: Optional[Mapping] = None,
    live_confirmation: str = "NOT_STARTED",
    expectation_score: Optional[float] = None,
    evidence: Optional[Iterable[dict]] = None,
    qualified_for_event5: bool = False,
    stale: bool = False,
    fail_closed: bool = False,
) -> dict:
    pts = _mapping(pts)
    disclosure = _mapping(disclosure)
    earnings = _mapping(earnings)
    next_theme = _mapping(next_theme)

    if previous_limit_state not in VALID_LIMIT_STATES:
        raise ValueError(f"invalid previous_limit_state: {previous_limit_state}")
    if live_confirmation not in VALID_LIVE_CONFIRMATION:
        raise ValueError(f"invalid live_confirmation: {live_confirmation}")

    score = _num(expectation_score)
    if score is not None and not 0.0 <= score <= 100.0:
        raise ValueError("expectation_score must be within 0..100")

    sources = _source_set(
        pts=pts,
        disclosure=disclosure,
        earnings=earnings,
        previous_limit_state=previous_limit_state,
        next_theme=next_theme,
    )

    hard_block = bool(stale or fail_closed or live_confirmation == "BLOCKED")
    event_handoff = bool(qualified_for_event5 and not hard_block)

    # Never expose stale PTS price as a current value.
    pts_price = None if hard_block else _num(pts.get("price"))
    pts_gap = None if hard_block else _num(pts.get("gap_pct"))

    return {
        "ticker": ticker,
        "name": name,
        "event_sources": sources,
        "pts": {
            "price": pts_price,
            "gap_pct": pts_gap,
            "turnover_yen": _num(pts.get("turnover_yen")),
            "liquidity_pass": pts.get("liquidity_pass"),
            "asof": pts.get("asof"),
        },
        "previous_limit_state": previous_limit_state,
        "disclosure": dict(disclosure),
        "earnings": dict(earnings),
        "next_theme": dict(next_theme),
        "live_confirmation": live_confirmation,
        "expectation_score": score,
        "expectation_score_status": (
            "AVAILABLE" if score is not None else "INSUFFICIENT_EVIDENCE"
        ),
        "qualified_for_event5": event_handoff,
        "handoff_target": "event-hot" if event_handoff else None,
        "evidence": list(evidence or []),
        "stale": bool(stale),
        "fail_closed": bool(fail_closed or hard_block),
    }


def build_report(candidates: Iterable[dict], *, updated_at: Optional[str] = None) -> dict:
    rows = list(candidates)
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": updated_at,
        "candidates": rows,
    }
