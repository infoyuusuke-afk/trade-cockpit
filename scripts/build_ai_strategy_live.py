#!/usr/bin/env python3
"""Build the read-only AI Strategy LIVE data artifact (C-112 Phase 2).

Maps already-existing, already-public signal outputs from signals.json
(produced by the existing scripts/signal_scan.py-family pipeline) into
Supervisor states via scripts.ai_strategy_live.build_supervisor_state(),
then through the existing Phase 1 pure-function chain
(strategy_live_snapshot -> route_snapshot -> build_live_board_view) to
produce ai_strategy_live.json.

This deliberately does NOT read live_ms2.json: that file is always an
empty public stub in this repository (the real MS2 RSS data is
local-PC-only and never committed, per the standing private-data
boundary -- see live_ms2.json's own "stale": true / empty "top5"
placeholder). A server-side/CI script can never see real MS2 content,
so it must not pretend to. signals.json, by contrast, is regenerated
and committed by the existing public pipeline (Yahoo Finance-sourced,
not MS2), so it is a legitimate server-side data source.

Mapped so far (deliberately not all 17 Supervisors -- see
scripts/ai_strategy_live.py's SUPERVISORS roster for the rest, which
remain unmapped until a similarly-considered source is chosen for
each):
- OVERNIGHT <- signals.json's overnight_long (direction LONG) /
  overnight_short (direction SHORT). Direct 1:1 mapping; the side is
  already explicit in which upstream list a row came from.
- EVENT <- signals.json's speculative_theme_watch. Always WATCH, never
  LONG/SHORT: this source is explicitly "monitoring only, not a trade
  candidate" on the site's own EVENT 5 tab (see scripts/update.py's
  EVENT 5 section and its "売買候補ではない" label), and this module
  must not contradict that existing, deliberate caution stance.
- SWING <- signals.json's monthly_weekly_hammers. LONG_WATCH (a
  reversal pattern under confirmation, not a breakout trigger).
- SCALP <- signals.json's prepared. LONG_WATCH, never a firm LONG:
  "prepared" means a breakout trigger price is being watched for, not
  that it has fired (the sibling "entered" list -- currently always
  empty -- is where a fired breakout would appear, and is intentionally
  left unmapped until it is ever observed non-empty, since a mapping
  that has never run against real data is not verified). Confirmed by
  inspecting every current row: trigger price > close price in all
  cases, i.e. consistently a bullish breakout-above setup, not a mix.
- VALUE_LONG_CATALYST <- signals.json's large_lot_accumulation
  (LONG_WATCH: a multi-week institutional-accumulation footprint under
  confirmation) and long_term_ma_rebounds_unverified (WATCH, not
  LONG_WATCH: this source's own field name and its "確定・実績未確認"
  status flag explicitly mark it as an unverified track record, and
  this module must not upgrade that caution to a watch-for-long state
  on its own authority).

DATA_QUALITY is intentionally left unmapped in this pass -- every
Router decision therefore resolves to UNKNOWN via DATA_QUALITY_UNKNOWN
rather than a guessed "OK". Wiring a real Data Quality Supervisor is
separate follow-up work, not something to fabricate here.

Still unmapped, no verified source found/chosen yet: REALTIME_DAYTRADE,
TOB_MA, KIOXIA_DEDICATED, GLOBAL_MACRO, MARKET_REGIME, RISK_SAFETY,
SHADOW_EXECUTION, RECONCILIATION, CALIBRATION, JOURNAL_CONTENT_EXPORT,
CHIEF_AI_STRATEGY. signals.json's daily_capitulation_reversals is
currently always empty in this repository, so no mapping for it has
been verified against real data; do not add one until it is.

Every mapped row's provenance names its exact upstream field
(e.g. "signals.json:overnight_long"); correlation_id is left None
(these upstream rows carry no per-row id to preserve).

Read-only / no live influence: writes a JSON file only. Imports no
execution/broker/RssOrder/real_submit module. Asserts at call time
that scripts.strategy_router.FEATURE_FLAG_LIVE_INFLUENCE_ENABLED is
still False -- this script refuses to run otherwise.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.ai_strategy_live import build_supervisor_state, strategy_live_snapshot
from scripts.ai_strategy_live_view import build_live_board_view
from scripts.strategy_router import route_snapshot, FEATURE_FLAG_LIVE_INFLUENCE_ENABLED

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "ai-strategy-live-board-1.0"
OUTPUT_PATH = Path("ai_strategy_live.json")
SIGNALS_PATH = Path("signals.json")
# signals.json is a once-per-run (daily-cadence) artifact, not a live
# intraday feed -- scripts.strategy_router.DEFAULT_STALE_AFTER_SECONDS
# (300s, meant for true live/intraday sources) would mark every row
# stale essentially always. Two trading-day-ish slack is the freshness
# bar for *this* source specifically; it does not change the Router's
# own default for other, faster-moving sources.
SIGNALS_STALE_AFTER_SECONDS = 60 * 60 * 48

SUPERVISOR_ORDER = [
    "SCALP", "EVENT", "REALTIME_DAYTRADE", "OVERNIGHT", "SWING",
    "VALUE_LONG_CATALYST", "TOB_MA", "KIOXIA_DEDICATED", "GLOBAL_MACRO",
]


def _as_of(signal_date, fallback_as_of):
    """signals.json rows carry a bare 'YYYY-MM-DD' signal_date, not a
    timezone-aware timestamp. Treat it as JST market close (15:30) of
    that date, matching how this site already treats daily signal
    snapshots elsewhere. Falls back to fallback_as_of (the snapshot's
    own observed_at, not "now") if signal_date is missing/unparseable
    -- never guesses a different date.
    """
    if not signal_date:
        return fallback_as_of
    try:
        d = datetime.strptime(signal_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return fallback_as_of
    return d.replace(hour=15, minute=30, tzinfo=JST).isoformat()


def _overnight_states(rows, direction, fallback_as_of):
    states = []
    for r in rows:
        ticker = r.get("ticker")
        if not ticker:
            continue
        try:
            states.append(build_supervisor_state(
                supervisor="OVERNIGHT", symbol=ticker, direction=direction,
                as_of=_as_of(r.get("signal_date"), fallback_as_of),
                provenance="signals.json:overnight_" + direction.lower(),
                entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
                condition_score=r.get("score"),
            ))
        except ValueError:
            continue
    return states


def _parse_signals_updated_at(value):
    """Parse signals.json's own 'YYYY-MM-DD HH:MM:SS JST' updated_at into
    a JST-aware ISO string. Returns None if missing/unparseable -- this
    is the observed_at of the whole signals.json snapshot, used for
    rows (like speculative_theme_watch) that carry no better per-row
    timestamp of their own; it must reflect when the data was actually
    generated, not when this script happens to run.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.strptime(value.replace(" JST", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=JST).isoformat()


def _event_states(rows, signals_as_of, now_iso):
    as_of = signals_as_of or now_iso
    states = []
    for r in rows:
        ticker = r.get("ticker")
        if not ticker:
            continue
        try:
            states.append(build_supervisor_state(
                supervisor="EVENT", symbol=ticker, direction="WATCH", as_of=as_of,
                provenance="signals.json:speculative_theme_watch",
                condition_score=r.get("score"),
            ))
        except ValueError:
            continue
    return states


def _swing_states(rows, fallback_as_of):
    states = []
    for r in rows:
        ticker = r.get("ticker")
        if not ticker:
            continue
        try:
            states.append(build_supervisor_state(
                supervisor="SWING", symbol=ticker, direction="LONG_WATCH",
                as_of=_as_of(r.get("signal_date"), fallback_as_of),
                provenance="signals.json:monthly_weekly_hammers",
                entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
                condition_score=r.get("score"),
            ))
        except ValueError:
            continue
    return states


def _scalp_states(rows, fallback_as_of):
    states = []
    for r in rows:
        ticker = r.get("ticker")
        if not ticker:
            continue
        try:
            states.append(build_supervisor_state(
                supervisor="SCALP", symbol=ticker, direction="LONG_WATCH",
                as_of=_as_of(r.get("signal_date"), fallback_as_of),
                provenance="signals.json:prepared",
                entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
                condition_score=r.get("score"),
            ))
        except ValueError:
            continue
    return states


def _value_long_catalyst_states(accumulation_rows, ma_rebound_rows, fallback_as_of):
    """A symbol can legitimately appear in both source lists at once (seen
    in real signals.json, e.g. one ticker with both an accumulation
    footprint and an unverified long-term MA rebound). VALUE_LONG_CATALYST
    is one Supervisor, so it can only report one direction per symbol --
    silently keeping whichever candidate happened to be built last would
    quietly drop the other's evidence. Resolve by taking the more
    cautious of the two labels (WATCH over LONG_WATCH) rather than
    picking one arbitrarily; the dropped candidate's fields are not lost
    silently, they are explicitly not the ones used, by a stated rule.
    """
    candidates = {}  # ticker -> (direction, row, provenance)
    for r in accumulation_rows:
        ticker = r.get("ticker")
        if ticker:
            candidates.setdefault(ticker, []).append(("LONG_WATCH", r, "signals.json:large_lot_accumulation"))
    for r in ma_rebound_rows:
        ticker = r.get("ticker")
        if ticker:
            # WATCH, not LONG_WATCH: this source's own field name and
            # "確定・実績未確認" status explicitly flag an unverified
            # track record; do not upgrade that caution on our own
            # authority (see module docstring).
            candidates.setdefault(ticker, []).append(("WATCH", r, "signals.json:long_term_ma_rebounds_unverified"))

    states = []
    for ticker, options in candidates.items():
        direction, r, provenance = min(options, key=lambda o: 0 if o[0] == "WATCH" else 1)
        try:
            states.append(build_supervisor_state(
                supervisor="VALUE_LONG_CATALYST", symbol=ticker, direction=direction,
                as_of=_as_of(r.get("signal_date"), fallback_as_of),
                provenance=provenance,
                entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
                condition_score=r.get("score"),
            ))
        except ValueError:
            continue
    return states


def build_states(signals, now_iso):
    signals_as_of = _parse_signals_updated_at(signals.get("updated_at")) or now_iso
    states = []
    states += _overnight_states(signals.get("overnight_long") or [], "LONG", signals_as_of)
    states += _overnight_states(signals.get("overnight_short") or [], "SHORT", signals_as_of)
    states += _event_states(signals.get("speculative_theme_watch") or [], signals_as_of, now_iso)
    states += _swing_states(signals.get("monthly_weekly_hammers") or [], signals_as_of)
    states += _scalp_states(signals.get("prepared") or [], signals_as_of)
    states += _value_long_catalyst_states(
        signals.get("large_lot_accumulation") or [],
        signals.get("long_term_ma_rebounds_unverified") or [],
        signals_as_of,
    )
    return states


def build_artifact(signals, now_iso, data_quality_ok_by_symbol=None):
    if FEATURE_FLAG_LIVE_INFLUENCE_ENABLED is not False:
        raise AssertionError(
            "refusing to build the AI Strategy LIVE artifact: "
            "FEATURE_FLAG_LIVE_INFLUENCE_ENABLED must be False in Phase 2"
        )
    states = build_states(signals, now_iso)
    snapshot = strategy_live_snapshot(states, now_iso)
    decisions = route_snapshot(snapshot, now_iso, data_quality_ok_by_symbol=data_quality_ok_by_symbol,
                                stale_after_seconds=SIGNALS_STALE_AFTER_SECONDS)
    board = build_live_board_view(snapshot, decisions, supervisor_order=SUPERVISOR_ORDER)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso,
        "feature_flag_enabled": FEATURE_FLAG_LIVE_INFLUENCE_ENABLED,
        "is_entry_trigger": False,
        "real_submit_allowed": False,
        "board": board,
    }


def main():
    now_iso = datetime.now(JST).isoformat()
    signals = json.loads(SIGNALS_PATH.read_text(encoding="utf-8")) if SIGNALS_PATH.exists() else {}
    artifact = build_artifact(signals, now_iso)
    OUTPUT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ai_strategy_live.json written: {len(artifact['board'])} symbols")


if __name__ == "__main__":
    main()
