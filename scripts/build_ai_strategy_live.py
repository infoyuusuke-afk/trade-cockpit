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
CONNECTED_SUPERVISORS records exactly which Supervisors have a mapping
here; build_artifact() reports it alongside the full roster's
complement (unconnected_supervisors) so a viewer never mistakes
partial lane coverage for a full 17-Supervisor committee review.

DATA_QUALITY has no mapping at all: build_artifact() always reports
data_quality_connected=False at the top level (not merely omitted),
and data_quality_ok stays None -> DATA_QUALITY_UNKNOWN in every Router
decision. Nothing here infers "quality OK" from the mere presence of
signals.json data.

Every mapped row's provenance names its exact upstream field
(e.g. "signals.json:overnight_long"); correlation_id is left None
(these upstream rows carry no per-row id to preserve). A row whose
timestamp cannot be honestly determined (neither its own signal_date
nor signals.json's own updated_at parses) is never given "now" as a
stand-in -- see _as_of()/_emit(). It is instead recorded in the
artifact's top-level data_issues list with reason
TIMESTAMP_UNAVAILABLE, so it stays visible with a reason instead of
vanishing or looking artificially fresh.

Each mapped lane's own freshness window is defined in
LANE_STALE_AFTER_SECONDS, matching its natural horizon (an
OVERNIGHT/SCALP candidate meant for the very next session goes stale
far sooner than a multi-week VALUE_LONG_CATALYST one); the Strategy
Router already reports staleness on the generation-time timestamp,
but a viewer looking at this page much later than generation (e.g.
after the pipeline itself has stopped running) needs its own
client-side check against generated_at -- see scripts/weekly_tabs.py's
rendering code for that.

Read-only / no live influence: writes a JSON file only. Imports no
execution/broker/RssOrder/real_submit module. Asserts at call time
that scripts.strategy_router.FEATURE_FLAG_LIVE_INFLUENCE_ENABLED is
still False -- this script refuses to run otherwise.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from scripts.ai_strategy_live import build_supervisor_state, strategy_live_snapshot, SUPERVISORS
from scripts.ai_strategy_live_view import build_live_board_view
from scripts.strategy_router import route_snapshot, FEATURE_FLAG_LIVE_INFLUENCE_ENABLED

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "ai-strategy-live-board-1.0"
OUTPUT_PATH = Path("ai_strategy_live.json")
SIGNALS_PATH = Path("signals.json")

SUPERVISOR_ORDER = [
    "SCALP", "EVENT", "REALTIME_DAYTRADE", "OVERNIGHT", "SWING",
    "VALUE_LONG_CATALYST", "TOB_MA", "KIOXIA_DEDICATED", "GLOBAL_MACRO",
]

# The Supervisors actually mapped to a verified source in this file (see
# module docstring). The rest of scripts.ai_strategy_live.SUPERVISORS are
# real, named lanes that simply have no data feed wired up yet -- they
# must never be silently absent from the artifact; build_artifact()
# reports both lists explicitly so a viewer never mistakes "5 of 17
# lanes reported" for "the full committee reviewed this and had nothing
# else to say".
CONNECTED_SUPERVISORS = {"SCALP", "EVENT", "OVERNIGHT", "SWING", "VALUE_LONG_CATALYST"}

# Per-lane freshness windows. signals.json is a once-per-run
# (daily-cadence) artifact for every mapped lane today, but the lanes
# themselves have different natural horizons and must not share one
# number: OVERNIGHT/SCALP candidates are meant for the very next
# session and are misleading if still shown after that session has
# passed; SWING/VALUE_LONG_CATALYST are multi-day-to-multi-week setups
# and can honestly tolerate more slack. "default" covers any future
# lane added without its own entry.
LANE_STALE_AFTER_SECONDS = {
    "OVERNIGHT": 20 * 60 * 60,
    "SCALP": 20 * 60 * 60,
    "EVENT": 24 * 60 * 60,
    "SWING": 5 * 24 * 60 * 60,
    "VALUE_LONG_CATALYST": 10 * 24 * 60 * 60,
    "default": 48 * 60 * 60,
}


def _as_of(signal_date, fallback_as_of):
    """signals.json rows carry a bare 'YYYY-MM-DD' signal_date, not a
    timezone-aware timestamp. Treat it as JST market close (15:30) of
    that date, matching how this site already treats daily signal
    snapshots elsewhere. Falls back to fallback_as_of (the snapshot's
    own observed_at -- never "now") if signal_date is missing/
    unparseable. Returns None (not a guess) when fallback_as_of is
    itself None; callers must treat that as "this row's time cannot be
    honestly determined" and exclude it, never substitute "now".
    """
    if signal_date:
        try:
            d = datetime.strptime(signal_date, "%Y-%m-%d")
            return d.replace(hour=15, minute=30, tzinfo=JST).isoformat()
        except (TypeError, ValueError):
            pass
    return fallback_as_of


def _parse_signals_updated_at(value):
    """Parse signals.json's own 'YYYY-MM-DD HH:MM:SS JST' updated_at into
    a JST-aware ISO string. Returns None if missing/unparseable -- this
    is the observed_at of the whole signals.json snapshot, used as the
    fallback timestamp for rows with no better per-row date of their
    own. It must reflect when the data was actually generated, never
    when this script happens to run: there is deliberately no "or now"
    fallback anywhere in this module.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.strptime(value.replace(" JST", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=JST).isoformat()


def _emit(states, unresolved, *, supervisor, ticker, direction, as_of_value, provenance, **fields):
    """Shared row builder for every mapping below. If as_of_value is None
    (see _as_of()), the row is recorded in `unresolved` with an explicit
    TIMESTAMP_UNAVAILABLE reason instead of being built with a
    fabricated time -- it must still show up somewhere a viewer can see
    it, never vanish silently.
    """
    if not ticker:
        return
    if as_of_value is None:
        unresolved.append({
            "supervisor": supervisor, "symbol": ticker, "provenance": provenance,
            "reason": "TIMESTAMP_UNAVAILABLE",
        })
        return
    try:
        states.append(build_supervisor_state(
            supervisor=supervisor, symbol=ticker, direction=direction, as_of=as_of_value,
            provenance=provenance, **fields,
        ))
    except ValueError:
        unresolved.append({
            "supervisor": supervisor, "symbol": ticker, "provenance": provenance,
            "reason": "INVALID_ROW",
        })


def _overnight_rows(states, unresolved, rows, direction, fallback_as_of):
    for r in rows:
        _emit(states, unresolved, supervisor="OVERNIGHT", ticker=r.get("ticker"), direction=direction,
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of),
              provenance="signals.json:overnight_" + direction.lower(),
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def _event_rows(states, unresolved, rows, signals_as_of):
    for r in rows:
        _emit(states, unresolved, supervisor="EVENT", ticker=r.get("ticker"), direction="WATCH",
              as_of_value=signals_as_of, provenance="signals.json:speculative_theme_watch",
              condition_score=r.get("score"))


def _swing_rows(states, unresolved, rows, fallback_as_of):
    for r in rows:
        _emit(states, unresolved, supervisor="SWING", ticker=r.get("ticker"), direction="LONG_WATCH",
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of),
              provenance="signals.json:monthly_weekly_hammers",
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def _scalp_rows(states, unresolved, rows, fallback_as_of):
    for r in rows:
        _emit(states, unresolved, supervisor="SCALP", ticker=r.get("ticker"), direction="LONG_WATCH",
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of),
              provenance="signals.json:prepared",
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def _value_long_catalyst_rows(states, unresolved, accumulation_rows, ma_rebound_rows, fallback_as_of):
    """A symbol can legitimately appear in both source lists at once (seen
    in real signals.json, e.g. one ticker with both an accumulation
    footprint and an unverified long-term MA rebound). VALUE_LONG_CATALYST
    is one Supervisor, so it can only report one direction per symbol --
    silently keeping whichever candidate happened to be built last would
    quietly drop the other's evidence. Resolve by taking the more
    cautious of the two labels (WATCH over LONG_WATCH) rather than
    picking one arbitrarily.
    """
    candidates = {}
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

    for ticker, options in candidates.items():
        direction, r, provenance = min(options, key=lambda o: 0 if o[0] == "WATCH" else 1)
        _emit(states, unresolved, supervisor="VALUE_LONG_CATALYST", ticker=ticker, direction=direction,
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of), provenance=provenance,
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def build_states(signals, now_iso):
    """Returns (states, unresolved). `now_iso` is used only as the
    Router's decision-time "now" for freshness comparisons downstream --
    it is never used as a row's own as_of; see _emit()/_as_of().
    """
    signals_as_of = _parse_signals_updated_at(signals.get("updated_at"))
    states, unresolved = [], []
    _overnight_rows(states, unresolved, signals.get("overnight_long") or [], "LONG", signals_as_of)
    _overnight_rows(states, unresolved, signals.get("overnight_short") or [], "SHORT", signals_as_of)
    _event_rows(states, unresolved, signals.get("speculative_theme_watch") or [], signals_as_of)
    _swing_rows(states, unresolved, signals.get("monthly_weekly_hammers") or [], signals_as_of)
    _scalp_rows(states, unresolved, signals.get("prepared") or [], signals_as_of)
    _value_long_catalyst_rows(
        states, unresolved,
        signals.get("large_lot_accumulation") or [],
        signals.get("long_term_ma_rebounds_unverified") or [],
        signals_as_of,
    )
    return states, unresolved


def build_artifact(signals, now_iso, data_quality_ok_by_symbol=None):
    if FEATURE_FLAG_LIVE_INFLUENCE_ENABLED is not False:
        raise AssertionError(
            "refusing to build the AI Strategy LIVE artifact: "
            "FEATURE_FLAG_LIVE_INFLUENCE_ENABLED must be False in Phase 2"
        )
    states, unresolved = build_states(signals, now_iso)
    snapshot = strategy_live_snapshot(states, now_iso)
    decisions = route_snapshot(snapshot, now_iso, data_quality_ok_by_symbol=data_quality_ok_by_symbol,
                                stale_after_seconds=LANE_STALE_AFTER_SECONDS)
    board = build_live_board_view(snapshot, decisions, supervisor_order=SUPERVISOR_ORDER)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso,
        "feature_flag_enabled": FEATURE_FLAG_LIVE_INFLUENCE_ENABLED,
        "is_entry_trigger": False,
        "real_submit_allowed": False,
        "connected_supervisors": sorted(CONNECTED_SUPERVISORS),
        "unconnected_supervisors": sorted(set(SUPERVISORS) - CONNECTED_SUPERVISORS),
        "data_quality_connected": False,
        "data_issues": unresolved,
        "board": board,
    }


def main():
    now_iso = datetime.now(JST).isoformat()
    signals = json.loads(SIGNALS_PATH.read_text(encoding="utf-8")) if SIGNALS_PATH.exists() else {}
    artifact = build_artifact(signals, now_iso)
    OUTPUT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ai_strategy_live.json written: {len(artifact['board'])} symbols, "
          f"{len(artifact['data_issues'])} data issues")


if __name__ == "__main__":
    main()
