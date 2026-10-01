"""Run one NEXT discovery pass from an in-memory universe snapshot."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from scripts.next_foundation.board import (
    attach_rank_velocity,
    build_funnel,
    classify_selection,
    rank_rows,
    select_active100,
)
from scripts.next_foundation.config import load_config
from scripts.next_foundation.log import judgment_record, write_judgments
from scripts.next_foundation.score import apply_velocity, score_market
from scripts.next_foundation.states import assign_state
from scripts.next_foundation.universe import collect_universe

PRIMARY_SKIP = {"FAIL_CLOSED", "SCHEDULED_RESELECT", "TOP_UNIVERSE_SCORE", "HELD"}


def run(payload: dict, config: dict | None = None, previous: dict | None = None, log_path: Path | str | None = None) -> dict:
    config = config or load_config()
    as_of = payload.get("as_of")
    if not isinstance(as_of, str) or not as_of:
        raise ValueError("payload.as_of is required")
    selection = classify_selection(as_of, payload.get("selection_mode"), config)
    universe = collect_universe(payload)
    rows = []
    for candidate in universe["candidates"]:
        scored = score_market(candidate["features"], candidate.get("invalid_features") or [], config)
        row = {
            **candidate,
            **scored,
            "score": None,
            "rank": None,
            "previous_rank": None,
            "rank_velocity": None,
        }
        rows.append(row)
    rank_rows(rows)
    for row in rows:
        attach_rank_velocity(row, as_of)
        if row.get("rank") is not None:
            path = list(row.get("rank_path_prior") or [])
            path.append(row["rank"])
            row["rank_path"] = path
        else:
            row["rank_path"] = list(row.get("rank_path_prior") or [])
        apply_velocity(row, row.get("rank_velocity"), config)

    previous = previous or {}
    previous_members = previous.get("members")
    protected = {
        symbol
        for symbol, state in (previous.get("symbols") or {}).items()
        if (state or {}).get("state") in ("IGNITION", "CONFIRMED")
    }
    active = select_active100(rows, selection, previous_members, config, protected)
    active_ids = {row["symbol"] for row in active}
    for row in rows:
        if row["symbol"] not in active_ids:
            row["funnel"] = None if row.get("fail_closed") else "OUTSIDE"
            row["membership"] = None
    funnel = build_funnel(active, config)
    symbol_state = previous.get("symbols") or {}
    for row in rows:
        if row["symbol"] in active_ids and row.get("funnel") is None:
            row["funnel"] = "ACTIVE100"
        state = assign_state(row, symbol_state.get(row["symbol"]), config)
        row.update(state)
        row["primary_reasons"] = _primary_reasons(row)
        row["rank_change"] = _rank_change(row)

    run_id = uuid.uuid4().hex
    records = [judgment_record(row, as_of, run_id) for row in rows]
    if log_path:
        write_judgments(log_path, records)

    board_fail = bool(universe["fail_closed"])
    return {
        "schema_version": "next-board-1.0",
        "generated_at": as_of,
        "run_id": run_id,
        "source_mode": payload.get("source_mode") or "discovery",
        "selection_kind": selection["selection_kind"],
        "session_open": selection["session_open"],
        "fail_closed": board_fail,
        "fail_closed_reason": universe.get("fail_closed_reason"),
        "funnel_fail_closed": funnel["funnel_fail_closed"],
        "funnel_reason": funnel["funnel_reason"],
        "orders_enabled": False,
        "universe_count": len(rows),
        "active100_count": len(active),
        "discovery_sources": universe["discovery_sources"],
        "monitor_symbols": universe["monitor_symbols"],
        "warnings": universe["warnings"],
        "active100": [_public_row(row) for row in _by_rank(active)],
        "next20": [_public_row(row) for row in funnel["next20"]],
        "next5": [_public_row(row) for row in funnel["next5"]],
        "excluded": [
            {"symbol": row["symbol"], "reason_codes": list(row.get("reason_codes") or [])}
            for row in rows if row.get("fail_closed")
        ],
        "judgments": records,
        "membership_state": {
            "members": [row["symbol"] for row in _by_rank(active)],
            "symbols": {
                row["symbol"]: {
                    "state": row.get("state"),
                    "consecutive_ignition": row.get("consecutive_ignition"),
                    "peak_score": row.get("peak_score"),
                }
                for row in rows
                if row.get("state")
            },
        },
    }


def write_board(path: Path | str, board: dict) -> None:
    public = {key: value for key, value in board.items() if key != "judgments"}
    Path(path).write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _rank_change(row: dict):
    if row.get("previous_rank") is None or row.get("rank") is None:
        return None
    return int(row["previous_rank"]) - int(row["rank"])


def _primary_reasons(row: dict) -> list[str]:
    components = row.get("components") or {}
    feature_order = {
        "PRICE_ACCEL_45S": components.get("price_accel_45s"),
        "VOLUME_SURGE": components.get("volume_surge_ratio"),
        "TURNOVER_ACCEL": components.get("turnover_accel"),
        "RELATIVE_STRENGTH": components.get("relative_strength"),
        "HIGH_UPDATE": components.get("high_update_frequency"),
        "VWAP_SUPPORTIVE": components.get("vwap_position"),
        "SHALLOW_PULLBACK": components.get("pullback_shallowness"),
        "PRICE_CHANGE_15S": components.get("price_change_15s"),
        "LIQUIDITY_OK": components.get("liquidity"),
        "OR5_ABOVE": components.get("or5_state"),
        "OR5_INSIDE": components.get("or5_state"),
        "OR15_ABOVE": components.get("or15_state"),
        "OR15_INSIDE": components.get("or15_state"),
        "RANK_VELOCITY_UP": row.get("rank_velocity_component"),
        "EMERGENCY_PROMOTION": 0.5,
    }
    ranked = []
    for code in row.get("reason_codes") or []:
        if code in PRIMARY_SKIP:
            continue
        score = feature_order.get(code)
        ranked.append((-(score if isinstance(score, (int, float)) else -1), code))
    ranked.sort()
    return [code for _, code in ranked[:3]]


def _by_rank(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (row.get("rank") is None, row.get("rank") or 10**9, row["symbol"]))


def _public_row(row: dict) -> dict:
    return {
        "symbol": row["symbol"],
        "name": row.get("name"),
        "price": row.get("price"),
        "next_rank": row.get("next_rank"),
        "next20_rank": row.get("next20_rank"),
        "score": row.get("score"),
        "market_score": row.get("market_score"),
        "score_status": row.get("score_status"),
        "state": row.get("state"),
        "lifecycle_state": row.get("lifecycle_state"),
        "lifecycle_alias": row.get("lifecycle_alias"),
        "lifecycle_phases": row.get("lifecycle_phases"),
        "rank": row.get("rank"),
        "previous_rank": row.get("previous_rank"),
        "rank_change": row.get("rank_change"),
        "rank_velocity": row.get("rank_velocity"),
        "rank_path": row.get("rank_path") or [],
        "reason_codes": list(row.get("reason_codes") or []),
        "primary_reasons": list(row.get("primary_reasons") or []),
        "features": row.get("features") or {},
        "funnel": row.get("funnel"),
        "membership": row.get("membership"),
        "on_monitor_layer": bool(row.get("on_monitor_layer")),
        "fail_closed": bool(row.get("fail_closed")),
        "sources": list(row.get("sources") or []),
    }
