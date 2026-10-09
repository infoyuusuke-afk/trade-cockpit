#!/usr/bin/env python3
"""AI Strategy LIVE / リアルタイムAI戦略LIVE (Master Spec 4.7.1/4.7.2, C-112).

A cross-horizon Supervisor state board. Each Supervisor reports its own
point-in-time judgment for a symbol; this module never collapses those
into one BUY/SELL verdict (SCALP=LONG candidate, OVERNIGHT=BLOCK, and
SWING=LONG WATCH may legitimately coexist for the same symbol).

State-change events are emitted through the existing Event Bus
(scripts.event_bus.build_event, domain="STRATEGY") using exactly the
event_type vocabulary C-112 specifies (SUPERVISOR_STATE_CHANGED,
STRATEGY_CANDIDATE_ACTIVATED, STRATEGY_INVALIDATED, CONFLICT_DETECTED,
DAILY_STRATEGY_SUMMARY). Because scripts/journal_projection.py already
projects STRATEGY-domain events and scripts/public_event_sanitizer.py
already strips anything private, those events reach the Journal/Content
pipeline (scripts/council_cycle_projection.py) with no changes to that
already-built machinery.

RISK_GATE_BLOCKED and SHADOW_POSITION_OPENED/CLOSED are intentionally
NOT emitted here: they belong to the existing Risk Gate
(scripts/execution_permission.py) and Shadow Execution
(scripts/shadow_position.py, scripts/shadow_execution.py) modules,
which this file does not call or modify.

Naming note: this module's "conflict" is a *display* concept (do
independent Supervisor judgments diverge for a symbol?). It is not
scripts/conflict_resolver.py's same-named but unrelated concept (merging
same-side signals into one real *execution* position). Neither module
calls the other.

Safety: pure functions only, no I/O, no broker/RssOrder/real_submit
code. Output never sets real_submit_allowed=True and never bypasses
Risk Gate, Permission Gate, Conflict Resolver (execution sense) or
Owner approval.
"""
from __future__ import annotations
from datetime import datetime, timedelta

SUPERVISORS = {
    "CHIEF_AI_STRATEGY": "Chief AI Strategy Supervisor",
    "DATA_QUALITY": "Data Quality Supervisor",
    "MARKET_REGIME": "Market Regime Supervisor",
    "SCALP": "SCALP Supervisor",
    "EVENT": "Momentum / 急騰 Supervisor",
    "REALTIME_DAYTRADE": "Realtime Daytrade Supervisor",
    "OVERNIGHT": "Overnight Supervisor",
    "SWING": "Swing Supervisor",
    "VALUE_LONG_CATALYST": "Value / Long Catalyst Supervisor",
    "TOB_MA": "TOB / M&A Supervisor",
    "KIOXIA_DEDICATED": "KIOXIA Dedicated Supervisor",
    "GLOBAL_MACRO": "Global Macro Supervisor",
    "RISK_SAFETY": "Risk & Safety Supervisor",
    "SHADOW_EXECUTION": "Shadow Execution Supervisor",
    "RECONCILIATION": "Reconciliation Supervisor",
    "CALIBRATION": "Calibration Supervisor",
    "JOURNAL_CONTENT_EXPORT": "Journal / Content Export Supervisor",
}

# Supervisors that report a per-symbol strategy-horizon candidate/state,
# as distinct from system-wide oversight roles (DATA_QUALITY, MARKET_REGIME,
# GLOBAL_MACRO, RISK_SAFETY, RECONCILIATION, CALIBRATION,
# JOURNAL_CONTENT_EXPORT, SHADOW_EXECUTION and CHIEF_AI_STRATEGY itself,
# which aggregate/contextualize rather than originate a trading candidate).
# GLOBAL_MACRO is intentionally excluded here: per Master Spec 4.7.3 (C-113)
# its output is a Regime Modifier and must never itself become an entry
# trigger or count toward cross-horizon conflict detection below.
HORIZON_SUPERVISORS = {
    "SCALP", "EVENT", "REALTIME_DAYTRADE", "OVERNIGHT", "SWING",
    "VALUE_LONG_CATALYST", "TOB_MA", "KIOXIA_DEDICATED",
}

DIRECTIONS = {"LONG", "LONG_WATCH", "SHORT", "SHORT_WATCH", "WATCH", "BLOCK", "NEUTRAL"}
LONG_LIKE = {"LONG", "LONG_WATCH"}
SHORT_LIKE = {"SHORT", "SHORT_WATCH"}
# A direction that represents an active strategy candidate (as opposed to
# a purely observational state) for STRATEGY_CANDIDATE_ACTIVATED/INVALIDATED.
CANDIDATE_DIRECTIONS = {"LONG", "SHORT"}

STATE_FIELDS = {
    "supervisor", "symbol", "as_of", "direction", "provenance", "correlation_id",
    "trigger", "invalidation",
    "entry", "stop", "target", "or5_low", "or5_high", "or15_low", "or15_high",
    "vwap", "ema9", "ema20", "flow_bias", "volume_burst", "condition_score",
    "historical_ev", "historical_pf", "historical_dd", "historical_n",
}
REQUIRED_STATE_FIELDS = {"supervisor", "symbol", "as_of", "direction"}


def _text_or_none(v):
    return v is None or isinstance(v, str)


def _aware(ts):
    if not isinstance(ts, str) or not ts:
        raise ValueError("as_of must be a non-empty ISO8601 string")
    d = datetime.fromisoformat(ts)
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return d


def build_supervisor_state(**fields):
    """Validate and normalize one Supervisor's point-in-time state for one symbol.

    Unknown fields are rejected (fail-closed). Optional numeric fields
    default to None rather than being guessed. This never decides
    real_submit_allowed and never includes such a field at all.
    """
    if set(fields) - STATE_FIELDS:
        raise ValueError("unknown state field(s): " + ",".join(sorted(set(fields) - STATE_FIELDS)))
    if not REQUIRED_STATE_FIELDS.issubset(fields):
        raise ValueError("missing required field(s): " + ",".join(sorted(REQUIRED_STATE_FIELDS - set(fields))))
    supervisor = fields["supervisor"]
    if supervisor not in SUPERVISORS:
        raise ValueError("unknown supervisor: " + str(supervisor))
    symbol = fields["symbol"]
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol required")
    direction = fields["direction"]
    if direction not in DIRECTIONS:
        raise ValueError("unknown direction: " + str(direction))
    if not _text_or_none(fields.get("provenance")):
        raise ValueError("provenance must be a string or None")
    if not _text_or_none(fields.get("correlation_id")):
        raise ValueError("correlation_id must be a string or None")
    _aware(fields["as_of"])
    state = {k: fields.get(k) for k in STATE_FIELDS}
    state["is_entry_trigger"] = False
    state["real_submit_allowed"] = False
    return state


def last_update_age_seconds(as_of, now):
    return (_aware(now) - _aware(as_of)).total_seconds()


def conflict_state(symbol, horizon_directions, as_of):
    """Structured Conflict State (data/conflict_state.schema.json, C-112 Phase 1).

    `horizon_directions` is {supervisor: direction} restricted to
    HORIZON_SUPERVISORS. Conflict means LONG-like and SHORT-like/BLOCK
    directions coexist for this symbol across those lanes. This is a
    display-only descriptive record -- see the module docstring's naming
    note distinguishing this from scripts/conflict_resolver.py.
    """
    has_long = any(d in LONG_LIKE for d in horizon_directions.values())
    has_short = any(d in SHORT_LIKE for d in horizon_directions.values())
    has_block = any(d == "BLOCK" for d in horizon_directions.values())
    conflict = (has_long and has_short) or (has_long and has_block) or (has_short and has_block)
    return {
        "schema_version": "conflict-state-1.0",
        "symbol": symbol,
        "as_of": as_of,
        "conflict": conflict,
        "directions": dict(horizon_directions),
        "has_long": has_long,
        "has_short": has_short,
        "has_block": has_block,
    }


def strategy_live_snapshot(states, now):
    """Group validated states by symbol without collapsing them.

    `states` is a list of build_supervisor_state() outputs. Returns, per
    symbol, every Supervisor's state as reported plus a structured
    `conflict_state` record (data/conflict_state.schema.json) and its
    boolean `conflict` shorthand. The flag is informational for the LIVE
    board; it does not resolve or execute anything.
    """
    by_symbol = {}
    for s in states:
        by_symbol.setdefault(s["symbol"], []).append(s)
    snapshot = {}
    for symbol, symbol_states in by_symbol.items():
        horizon_directions = {
            s["supervisor"]: s["direction"]
            for s in symbol_states
            if s["supervisor"] in HORIZON_SUPERVISORS
        }
        c_state = conflict_state(symbol, horizon_directions, now)
        snapshot[symbol] = {
            "symbol": symbol,
            "supervisors": {
                s["supervisor"]: {**s, "last_update_age_seconds": last_update_age_seconds(s["as_of"], now)}
                for s in symbol_states
            },
            "conflict": c_state["conflict"],
            "conflict_state": c_state,
            "is_entry_trigger": False,
            "real_submit_allowed": False,
        }
    return snapshot


def _pending_transitions(states, previous_states=None):
    """Shared transition detection for both internal and external event builders.

    Yields dicts with everything a caller needs to build either a rich
    internal event or a summary-only external one for the same
    transition, so the two payload shapes can never drift out of sync
    on *which* transitions fire.
    """
    previous_by_key = {(s["supervisor"], s["symbol"]): s for s in (previous_states or [])}
    out = []
    for state in states:
        key = (state["supervisor"], state["symbol"])
        prior = previous_by_key.get(key)
        if prior is not None and prior["direction"] == state["direction"]:
            continue
        out.append({
            "event_type": "SUPERVISOR_STATE_CHANGED", "as_of": state["as_of"], "symbol": state["symbol"],
            "supervisor": state["supervisor"], "direction": state["direction"],
            "previous_direction": prior["direction"] if prior else None,
            "summary": SUPERVISORS[state["supervisor"]] + " -> " + state["direction"],
        })
        was_candidate = prior is not None and prior["direction"] in CANDIDATE_DIRECTIONS
        is_candidate = state["direction"] in CANDIDATE_DIRECTIONS
        if is_candidate and not was_candidate:
            out.append({
                "event_type": "STRATEGY_CANDIDATE_ACTIVATED", "as_of": state["as_of"], "symbol": state["symbol"],
                "supervisor": state["supervisor"], "direction": state["direction"], "previous_direction": None,
                "summary": SUPERVISORS[state["supervisor"]] + " candidate activated: " + state["direction"],
            })
        elif was_candidate and not is_candidate:
            out.append({
                "event_type": "STRATEGY_INVALIDATED", "as_of": state["as_of"], "symbol": state["symbol"],
                "supervisor": state["supervisor"], "direction": None, "previous_direction": prior["direction"],
                "summary": SUPERVISORS[state["supervisor"]] + " candidate invalidated",
            })

    now = max((s["as_of"] for s in states), default=None)
    if now is not None:
        current_snapshot = strategy_live_snapshot(states, now)
        previous_snapshot = strategy_live_snapshot(list(previous_by_key.values()), now) if previous_by_key else {}
        for symbol, entry in current_snapshot.items():
            was_conflict = previous_snapshot.get(symbol, {}).get("conflict", False)
            if entry["conflict"] and not was_conflict:
                out.append({
                    "event_type": "CONFLICT_DETECTED", "as_of": now, "symbol": symbol,
                    "supervisor": None, "direction": None, "previous_direction": None,
                    "directions": {sup: st["direction"] for sup, st in entry["supervisors"].items()},
                    "summary": "Cross-horizon direction conflict detected for " + symbol,
                })
    return out


def supervisor_state_events(build_event, states, previous_states=None, source="ai_strategy_live"):
    """Diff current vs previous states and emit the C-112 event vocabulary
    with full internal detail (for the cockpit's own, internal journal
    projection via scripts/journal_projection.py). `build_event` is
    scripts.event_bus.build_event, passed in rather than imported at
    module scope so this file stays trivially testable.
    """
    events = []
    for t in _pending_transitions(states, previous_states):
        payload = {"summary": t["summary"]}
        if t["supervisor"] is not None:
            payload["supervisor"] = t["supervisor"]
        if t["direction"] is not None:
            payload["direction"] = t["direction"]
        if t["previous_direction"] is not None:
            payload["previous_direction"] = t["previous_direction"]
        if "directions" in t:
            payload["directions"] = t["directions"]
        events.append(build_event(
            timestamp=t["as_of"], domain="STRATEGY", event_type=t["event_type"],
            source=source, symbol=t["symbol"], payload=payload,
        ))
    return events


def external_journal_events(build_event, states, previous_states=None, source="ai_strategy_live"):
    """Same transitions as supervisor_state_events(), but every payload is
    built as {"summary": ...} only, so each event passes
    scripts.public_event_sanitizer.sanitize_event() unmodified. This is
    the feed for the separate, external Trading Journal System C-112
    describes: no supervisor/direction/price/account detail crosses that
    boundary, only a public-safe one-line summary per transition.
    """
    events = []
    for t in _pending_transitions(states, previous_states):
        events.append(build_event(
            timestamp=t["as_of"], domain="STRATEGY", event_type=t["event_type"],
            source=source, symbol=t["symbol"], payload={"summary": t["summary"]},
        ))
    return events


def daily_strategy_summary_event(build_event, states, session_date, source="ai_strategy_live"):
    """One DAILY_STRATEGY_SUMMARY event rolling up a day's final states.

    `states` should be the final build_supervisor_state() snapshot for
    each (supervisor, symbol) as of session close. Purely descriptive
    counts; no P&L or account data (that belongs to Shadow/Reconciliation,
    not this summary).
    """
    by_symbol = {}
    for s in states:
        by_symbol.setdefault(s["symbol"], []).append(s["direction"])
    candidates = sum(1 for s in states if s["direction"] in CANDIDATE_DIRECTIONS)
    watches = sum(1 for s in states if s["direction"] in {"WATCH", "LONG_WATCH", "SHORT_WATCH"})
    blocks = sum(1 for s in states if s["direction"] == "BLOCK")
    symbols_with_conflict = [
        symbol for symbol, entry in strategy_live_snapshot(
            states, max(s["as_of"] for s in states)).items() if entry["conflict"]
    ] if states else []
    summary_text = (
        "Daily strategy summary for " + session_date + ": "
        + str(len(by_symbol)) + " symbols, " + str(candidates) + " candidates, "
        + str(watches) + " watches, " + str(blocks) + " blocks, "
        + str(len(symbols_with_conflict)) + " with conflicts"
    )
    return build_event(
        timestamp=states[-1]["as_of"] if states else session_date + "T15:30:00+09:00",
        domain="STRATEGY", event_type="DAILY_STRATEGY_SUMMARY", source=source,
        payload={
            "session_date": session_date,
            "symbol_count": len(by_symbol),
            "candidate_count": candidates,
            "watch_count": watches,
            "block_count": blocks,
            "conflict_symbols": sorted(symbols_with_conflict),
            "summary": summary_text,
        },
    )


def external_daily_strategy_summary_event(build_event, states, session_date, source="ai_strategy_live"):
    """Sanitizer-compatible (summary-only) counterpart to
    daily_strategy_summary_event(), for the external Trading Journal
    System. Counts are folded into the summary text rather than carried
    as structured fields, so the payload stays {"summary": ...} only.
    """
    rich = daily_strategy_summary_event(build_event, states, session_date, source=source)
    return build_event(
        timestamp=rich["timestamp"], domain="STRATEGY", event_type="DAILY_STRATEGY_SUMMARY",
        source=source, payload={"summary": rich["payload"]["summary"]},
    )
