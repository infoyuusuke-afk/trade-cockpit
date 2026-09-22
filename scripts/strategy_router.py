#!/usr/bin/env python3
"""Strategy Router (Master Spec / C-112 Phase 1, GPT priority directive 2026-09-22).

A pure deterministic router that consumes an already-built AI Strategy
LIVE snapshot (scripts.ai_strategy_live.strategy_live_snapshot) and
returns an advisory-only Router Decision (data/router_decision.schema.json).

Phase 1's output vocabulary is a CLOSED set of three non-actionable
states: HOLD, UNKNOWN, NO_ACTION. There is no BUY/SHORT/CANDIDATE state
at this layer -- this is a fail-closed eligibility/gating skeleton, not
a signal generator. Missing/stale/conflicting input always resolves to
UNKNOWN or HOLD rather than an inferred repair.

FEATURE_FLAG_LIVE_INFLUENCE_ENABLED is a module-level constant, not a
per-call parameter, and is always False in Phase 1. The router still
preserves UNKNOWN/HOLD/NO_ACTION as its advisory observation state so
the LIVE board can distinguish missing/stale/conflicting evidence from
a healthy no-action state. Nothing in this repository reads a RouterDecision to affect an existing formal signal,
Shadow order, or execution path -- Phase 2 wiring (read-only
integration) and any later live-influence gate are separate, later
work per Issue #171. test_feature_flag_is_off_in_phase1() below is a
tripwire: it fails loudly if this constant is ever flipped without a
deliberate, reviewed change.

Safety: pure functions only, no I/O, no broker/RssOrder/real_submit
code. Every RouterDecision carries is_entry_trigger=False and
real_submit_allowed=False, and feature_flag_enabled always mirrors the
constant above (False), matching router_decision.schema.json's
schema_version-pinned `const: false`.
"""
from __future__ import annotations

SCHEMA_VERSION = "router-decision-1.0"
STATES = {"HOLD", "UNKNOWN", "NO_ACTION"}
DEFAULT_STALE_AFTER_SECONDS = 300

# Phase 1 master gate. See module docstring. Do not flip without a
# reviewed Phase 2 change to this file and its tests.
FEATURE_FLAG_LIVE_INFLUENCE_ENABLED = False


def _stale_threshold_for(supervisor, stale_after_seconds):
    """Resolve the freshness window for one Supervisor's lane.

    `stale_after_seconds` may be a single number (applied to every
    Supervisor, the original Phase 1 behaviour) or a dict mapping
    supervisor -> seconds with a required "default" key for any
    Supervisor not explicitly listed. Different lanes legitimately have
    different natural cadences (an intraday SCALP candidate goes stale
    far sooner than a multi-week VALUE_LONG_CATALYST one); a single
    global threshold cannot honestly represent both.
    """
    if isinstance(stale_after_seconds, dict):
        return stale_after_seconds.get(supervisor, stale_after_seconds["default"])
    return stale_after_seconds


def route_symbol(symbol, snapshot_entry, *, now, data_quality_ok=None,
                  stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS):
    """Route one symbol's AI Strategy LIVE snapshot entry to a RouterDecision.

    `snapshot_entry` is strategy_live_snapshot(states, now)[symbol], or
    None if no Supervisor has reported for this symbol yet.
    `data_quality_ok` is the DATA_QUALITY Supervisor's own read
    (True/False/None-for-not-yet-known), passed explicitly since Phase 1
    does not implicitly look anything up -- callers own that wiring.
    `stale_after_seconds` is a single number or a per-supervisor dict;
    see _stale_threshold_for().
    """
    reasons = []
    supervisor_directions = {}
    conflict = False
    stale_supervisors = []

    if snapshot_entry is None:
        reasons.append("NO_SUPERVISOR_DATA")
        state = "UNKNOWN"
    else:
        supervisor_directions = {
            sup: st["direction"] for sup, st in snapshot_entry["supervisors"].items()
        }
        conflict = snapshot_entry["conflict"]
        stale_supervisors = sorted(
            sup for sup, st in snapshot_entry["supervisors"].items()
            if st["last_update_age_seconds"] < 0
            or st["last_update_age_seconds"] > _stale_threshold_for(sup, stale_after_seconds)
        )
        if stale_supervisors:
            reasons.append("STALE_SUPERVISOR_DATA")
            state = "UNKNOWN"
        elif data_quality_ok is False:
            reasons.append("DATA_QUALITY_SUPERVISOR_NOT_OK")
            state = "HOLD"
        elif data_quality_ok is None:
            reasons.append("DATA_QUALITY_UNKNOWN")
            state = "UNKNOWN"
        elif conflict:
            reasons.append("CROSS_HORIZON_CONFLICT")
            state = "HOLD"
        else:
            state = "NO_ACTION"

    if not FEATURE_FLAG_LIVE_INFLUENCE_ENABLED:
        # Preserve the advisory observation state (UNKNOWN/HOLD/NO_ACTION)
        # for the LIVE board. The feature flag gates downstream influence;
        # it must not erase evidence-quality/conflict state.
        reasons.append("PHASE1_FEATURE_FLAG_OFF")

    if state not in STATES:
        raise AssertionError("router produced a state outside the Phase 1 vocabulary: " + str(state))

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "horizon": None,
        "as_of": now,
        "state": state,
        "reasons": reasons,
        "supervisor_directions": supervisor_directions,
        "stale_supervisors": stale_supervisors,
        "data_quality_ok": data_quality_ok,
        "conflict": conflict,
        "feature_flag_enabled": FEATURE_FLAG_LIVE_INFLUENCE_ENABLED,
        "is_entry_trigger": False,
        "real_submit_allowed": False,
    }


def route_snapshot(snapshot, now, *, data_quality_ok_by_symbol=None, stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS):
    """Route every symbol in an AI Strategy LIVE snapshot.

    `snapshot` is scripts.ai_strategy_live.strategy_live_snapshot(...)'s
    return value. `data_quality_ok_by_symbol` optionally maps symbol to
    the DATA_QUALITY Supervisor's read for it; symbols absent from the
    map are treated as data_quality_ok=None (unknown), which fails
    closed to UNKNOWN.
    """
    data_quality_ok_by_symbol = data_quality_ok_by_symbol or {}
    return {
        symbol: route_symbol(
            symbol, entry, now=now,
            data_quality_ok=data_quality_ok_by_symbol.get(symbol),
            stale_after_seconds=stale_after_seconds,
        )
        for symbol, entry in snapshot.items()
    }
