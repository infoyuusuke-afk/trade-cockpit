"""Pure helpers for the V10 earnings watchlist contract.

The module intentionally avoids inventing surprise/priced-in scores. It joins
already-collected calendar/evidence/reaction inputs, computes deterministic
time-to-event stages, and preserves missing evidence as null/unknown.

This makes the T-30 research lane testable before network/source integration.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Mapping, Optional

SCHEMA_VERSION = "earnings-watchlist-1.0"


def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def days_to_event(event_date, *, asof: date) -> Optional[int]:
    parsed = _parse_date(event_date)
    if parsed is None:
        return None
    return (parsed - asof).days


def stage_for_days(days: Optional[int], *, result_available: bool = False) -> str:
    if result_available:
        return "RESULT"
    if days is None:
        return "UNKNOWN"
    if days < 0:
        return "PAST_DUE"
    if days <= 1:
        return "T1"
    if days <= 7:
        return "T7"
    if days <= 14:
        return "T14"
    if days <= 30:
        return "T30"
    return "FUTURE"


def _num(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_post_earnings_reactions(records: Iterable[dict]) -> dict:
    """Summarize realized post-earnings reactions without forecasting them."""
    rows = list(records)
    keys = ("gap_pct", "ret_1d_pct", "ret_5d_pct", "ret_20d_pct")
    summary = {"sample_n": len(rows)}

    for key in keys:
        values = [_num(row.get(key)) for row in rows]
        values = [value for value in values if value is not None]
        summary[key.replace("_pct", "_avg_pct")] = (
            sum(values) / len(values) if values else None
        )
        summary[key.replace("_pct", "_median_pct")] = (
            sorted(values)[len(values) // 2] if values else None
        )

    positive_1d = [
        _num(row.get("ret_1d_pct"))
        for row in rows
        if _num(row.get("ret_1d_pct")) is not None
    ]
    summary["positive_1d_rate_pct"] = (
        sum(1 for value in positive_1d if value > 0) / len(positive_1d) * 100.0
        if positive_1d
        else None
    )
    return summary


def _safe_map(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def build_watch_item(
    event: dict,
    *,
    asof: date,
    company_features: Optional[Mapping] = None,
    reaction_records: Optional[Iterable[dict]] = None,
) -> dict:
    features = _safe_map(company_features)
    reactions = list(reaction_records or [])

    code = str(event.get("code") or "").strip()
    event_date = _parse_date(event.get("date"))
    days = days_to_event(event_date, asof=asof) if event_date else None

    result_available = bool(features.get("result_available"))

    return {
        "code": code or None,
        "name": event.get("name"),
        "earnings_date": event_date.isoformat() if event_date else None,
        "days_to_event": days,
        "stage": stage_for_days(days, result_available=result_available),
        "watched": bool(event.get("watched")),
        "source": event.get("source"),
        "source_url": event.get("source_url"),
        "calendar_status": event.get("status"),
        "guidance": features.get("guidance"),
        "consensus": features.get("consensus"),
        "progress_rate_pct": _num(features.get("progress_rate_pct")),
        "revision_history": features.get("revision_history"),
        "segments": features.get("segments"),
        "seasonality": features.get("seasonality"),
        "fx_sensitivity": features.get("fx_sensitivity"),
        "peer_readthrough": features.get("peer_readthrough"),
        "pre_event_price": {
            "runup_5d_pct": _num(features.get("runup_5d_pct")),
            "runup_20d_pct": _num(features.get("runup_20d_pct")),
            "relative_volume": _num(features.get("relative_volume")),
        },
        "surprise_score": _num(features.get("surprise_score")),
        "priced_in_score": _num(features.get("priced_in_score")),
        "score_status": features.get("score_status") or (
            "AVAILABLE"
            if _num(features.get("surprise_score")) is not None
            and _num(features.get("priced_in_score")) is not None
            else "INSUFFICIENT_EVIDENCE"
        ),
        "historical_reaction": summarize_post_earnings_reactions(reactions),
        "evidence": list(features.get("evidence") or []),
    }


def build_watchlist(
    calendar_events: Iterable[dict],
    *,
    asof: date,
    company_features_by_code: Optional[Mapping[str, Mapping]] = None,
    reaction_history_by_code: Optional[Mapping[str, Iterable[dict]]] = None,
    max_days: int = 30,
) -> dict:
    feature_map = company_features_by_code or {}
    reaction_map = reaction_history_by_code or {}

    items = []
    for event in calendar_events:
        code = str(event.get("code") or "").strip()
        item = build_watch_item(
            event,
            asof=asof,
            company_features=feature_map.get(code),
            reaction_records=reaction_map.get(code),
        )
        days = item["days_to_event"]

        if item["stage"] == "RESULT":
            items.append(item)
            continue

        # T-30 research lane: include today through max_days, plus watched
        # names even if their date is farther out so the UI can show that
        # they are tracked but not yet in the active window.
        if days is not None and 0 <= days <= max_days:
            items.append(item)
        elif item["watched"]:
            items.append(item)

    items.sort(
        key=lambda item: (
            item["earnings_date"] is None,
            item["earnings_date"] or "9999-12-31",
            item["code"] or "",
        )
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "asof": asof.isoformat(),
        "max_days": max_days,
        "items": items,
    }
