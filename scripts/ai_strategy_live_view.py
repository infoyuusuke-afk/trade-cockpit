#!/usr/bin/env python3
"""AI Strategy LIVE presentation/data contract (C-112 Phase 1 UI skeleton).

Pure functions turning an AI Strategy LIVE snapshot
(scripts.ai_strategy_live.strategy_live_snapshot) and its Strategy
Router decisions (scripts.strategy_router.route_snapshot) into a
JSON-serializable view model a renderer can consume directly, matching
how this site's other tabs already work (Python writes a data
structure, client-side JS renders it -- see scripts/update.py's
signals.json-fed sections).

This module does not render HTML and is not wired into
scripts/update.py or scripts/weekly_tabs.py yet. Per GPT's Issue #171
Phase 1 directive, live wiring into the production site is Phase 2
(read-only integration), gated behind the still-OFF
scripts.strategy_router.FEATURE_FLAG_LIVE_INFLUENCE_ENABLED. A
standalone visual mockup built from this same shape is provided
separately for design review, not as a production page.

Safety: pure functions only, no I/O. Every card carries
is_entry_trigger=False and real_submit_allowed=False. Direction/state
labels are display strings only; they are never fed back into any
execution path.
"""
from __future__ import annotations

DIRECTION_LABELS = {
    "LONG": {"label": "LONG", "css_class": "long"},
    "LONG_WATCH": {"label": "LONG WATCH", "css_class": "long-watch"},
    "SHORT": {"label": "SHORT", "css_class": "short"},
    "SHORT_WATCH": {"label": "SHORT WATCH", "css_class": "short-watch"},
    "WATCH": {"label": "WATCH", "css_class": "watch"},
    "BLOCK": {"label": "BLOCK", "css_class": "block"},
    "NEUTRAL": {"label": "NEUTRAL", "css_class": "neutral"},
}

ROUTER_STATE_LABELS = {
    "HOLD": {"label": "HOLD", "css_class": "hold"},
    "UNKNOWN": {"label": "UNKNOWN", "css_class": "unknown"},
    "NO_ACTION": {"label": "NO ACTION", "css_class": "no-action"},
}


def build_supervisor_row(state_with_age, stale_after_seconds):
    """One Supervisor's lane row for the card.

    `state_with_age` is one entry of
    strategy_live_snapshot(...)[symbol]["supervisors"] (already carries
    last_update_age_seconds). Carries both the exact `as_of` timestamp
    and `correlation_id` for traceability/audit, even though a renderer
    may choose to keep correlation_id hidden in the visual UI by default.
    """
    direction = state_with_age["direction"]
    age = state_with_age.get("last_update_age_seconds")
    is_stale = age is not None and (age < 0 or age > stale_after_seconds)
    return {
        "supervisor": state_with_age["supervisor"],
        "direction": direction,
        "direction_label": DIRECTION_LABELS.get(direction, {"label": direction, "css_class": "neutral"})["label"],
        "css_class": DIRECTION_LABELS.get(direction, {"label": direction, "css_class": "neutral"})["css_class"],
        "as_of": state_with_age.get("as_of"),
        "correlation_id": state_with_age.get("correlation_id"),
        "trigger": state_with_age.get("trigger"),
        "invalidation": state_with_age.get("invalidation"),
        "entry": state_with_age.get("entry"),
        "stop": state_with_age.get("stop"),
        "target": state_with_age.get("target"),
        "or5_low": state_with_age.get("or5_low"),
        "or5_high": state_with_age.get("or5_high"),
        "or15_low": state_with_age.get("or15_low"),
        "or15_high": state_with_age.get("or15_high"),
        "vwap": state_with_age.get("vwap"),
        "ema9": state_with_age.get("ema9"),
        "ema20": state_with_age.get("ema20"),
        "flow_bias": state_with_age.get("flow_bias"),
        "volume_burst": state_with_age.get("volume_burst"),
        "condition_score": state_with_age.get("condition_score"),
        "historical_ev": state_with_age.get("historical_ev"),
        "historical_pf": state_with_age.get("historical_pf"),
        "historical_dd": state_with_age.get("historical_dd"),
        "historical_n": state_with_age.get("historical_n"),
        "provenance": state_with_age.get("provenance"),
        "last_update_age_seconds": age,
        "is_stale": is_stale,
    }


def build_symbol_card_view(symbol, snapshot_entry, router_decision, stale_after_seconds=300, supervisor_order=None):
    """One symbol's full AI Strategy LIVE card view model.

    `supervisor_order` optionally fixes lane display order (e.g. the
    canonical SCALP/EVENT/REALTIME_DAYTRADE/.../KIOXIA_DEDICATED order);
    unordered/omitted supervisors are appended alphabetically.
    """
    supervisors = snapshot_entry["supervisors"]
    order = list(supervisor_order or [])
    ordered_keys = [k for k in order if k in supervisors] + sorted(k for k in supervisors if k not in order)
    rows = [build_supervisor_row(supervisors[k], stale_after_seconds) for k in ordered_keys]
    router_state = router_decision["state"]
    return {
        "symbol": symbol,
        "rows": rows,
        "conflict_state": snapshot_entry["conflict_state"],
        "router": {
            "state": router_state,
            "state_label": ROUTER_STATE_LABELS.get(router_state, {"label": router_state, "css_class": "unknown"})["label"],
            "css_class": ROUTER_STATE_LABELS.get(router_state, {"label": router_state, "css_class": "unknown"})["css_class"],
            "as_of": router_decision["as_of"],
            "reasons": router_decision["reasons"],
            "stale_supervisors": router_decision["stale_supervisors"],
            "data_quality_ok": router_decision["data_quality_ok"],
            "feature_flag_enabled": router_decision["feature_flag_enabled"],
        },
        "is_entry_trigger": False,
        "real_submit_allowed": False,
    }


def build_live_board_view(snapshot, router_decisions, stale_after_seconds=300, supervisor_order=None):
    """The full AI Strategy LIVE board: every symbol's card, sorted by symbol.

    `snapshot` is scripts.ai_strategy_live.strategy_live_snapshot(...)'s
    return value; `router_decisions` is
    scripts.strategy_router.route_snapshot(...)'s return value for the
    same symbol set.
    """
    return [
        build_symbol_card_view(symbol, snapshot[symbol], router_decisions[symbol], stale_after_seconds, supervisor_order)
        for symbol in sorted(snapshot)
    ]
