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
boundary). signals.json, by contrast, is regenerated and committed by
the existing public pipeline (Yahoo Finance-sourced, not MS2), so it is
a legitimate server-side data source.

## Card vs. watchlist (Owner/GPT directive, 2026-09-22)

Every mapped signal is traced to the *existing* scripts/update.py
section that already renders it, to find whether that section is an
already-selected TOP5 set or a wider candidate pool -- this file never
invents a new "strong" ranking:

- signals.json:overnight_long / overnight_short -> update.py's "⑩ 信用
  需給優先・持ち越しLONG候補 TOP5" / "⑪ ...SHORT候補 TOP5" sections.
  Titled TOP5, sliced to 5 there (carryRows). CARD.
- signals.json:speculative_theme_watch -> legacy internal EVENT lane, user-facing "急騰5 / MOMENTUM 5"
  card section (renderScalpCard, .slice(0,5)). CARD.
- signals.json:monthly_weekly_hammers -> update.py's "⑤-E 月足・週足
  反転＋信用需給 TOP5" section. Titled TOP5, sliced to 5. CARD.
  (This section's title text ("月足・週足反転") is what
  scripts/weekly_tabs.py's client-side routing matches against to
  place it on the **VALUE 5** tab, not SWING -- an earlier version of
  this module mislabeled the Supervisor as SWING based on list length
  alone, which is exactly the mistake this directive corrects.)
- signals.json:long_term_ma_rebounds (the verified list -- NOT
  long_term_ma_rebounds_unverified) -> update.py's "⑤-F 長期右肩上がり
  ・50週線／200日線反発＋信用需給 TOP5" section, also on VALUE 5.
  Titled TOP5, sliced to 5. CARD. (Currently empty in this repository;
  an honest empty result, not a reason to substitute the unverified
  sibling list.)
- signals.json:prepared -> update.py's "⑨ 本日準備点灯銘柄 **上位30**"
  section -- its own title says 30, not 5. Traced through
  scripts/weekly_tabs.py's client-side routing (its h2 text contains
  "準備点灯", matching the `t.includes("準備点灯")` rule), this section
  is the real **REALTIME 5** tab's own data -- so this field is mapped
  to the REALTIME_DAYTRADE Supervisor (an earlier version of this
  module mapped it to SCALP instead; see the SCALP note below for why
  that was wrong). A top-30 pool, not a TOP5 -> WATCHLIST only.
- signals.json:large_lot_accumulation -> update.py's "大口買い集め・
  吸収監視 **TOP20**" section, its own dedicated tab. WATCHLIST.
- signals.json:long_term_ma_rebounds_unverified -> not rendered by any
  section in scripts/update.py at all (only the verified
  long_term_ma_rebounds list is). With no existing classification to
  reuse, this module does not invent one for it and does not use this
  field at all, per the explicit instruction not to add a "strong"
  judgment where none already exists.

SWING has no verified existing-TOP5 source in signals.json: SWING 5's
real content (see update.py's "⑤-A/B/C/D" sections, routed to the
`swing` tab by scripts/weekly_tabs.py's title matching) comes from a
different, not-yet-investigated computation, not from signals.json.
SWING is therefore reported unmapped (see CONNECTED_SUPERVISORS)
rather than guessed.

SCALP has no signals.json source at all and is intentionally left
unmapped (Owner/GPT directive, 2026-09-23). The real "SCALP 5" display
(scripts/weekly_tabs.py's `#scalp-fixed-5` panel) is a permanently
fixed set of 5 tickers hardcoded directly in that file's JS
(`["285A.T","9984.T","8035.T","6920.T","6857.T"]`) -- there is no
Python script or signals.json field that produces or scores this list;
grepping the repository for it turns up only that one literal. Its
live judgment (price, ENTRY/STOP/T1, OR5/OR15, VWAP, EMA, flow_bias,
volume_burst) is populated exclusively by the browser's own
`ms2RssUpdate` event, i.e. local MS2 RSS data that is never committed
to this repository (see the module docstring's opening paragraph on
the live_ms2.json/signals.json boundary). Even though the 5 ticker
symbols themselves are public (hardcoded in a committed file), that
alone carries no live SCALP judgment to reuse -- there is nothing
in signals.json this module could honestly attach to the SCALP
Supervisor, so it is reported unmapped rather than borrowing an
unrelated candidate pool for it. (An earlier version of this module
emitted SCALP states from signals.json:prepared; that was a naming
coincidence, not a real connection -- prepared is actually the
REALTIME 5 tab's data, see above.) The existing SCALP 5 panel's own
display is untouched by this change.

A symbol qualifying for CARD treatment under any mapping keeps every
Supervisor lane it has (including ones sourced from a WATCHLIST-only
list, e.g. a large_lot_accumulation row for a symbol that is also an
OVERNIGHT TOP5 pick) merged into that one card -- see
CARD_QUALIFYING_PROVENANCE and build_artifact()'s split. A symbol with
no card-qualifying entry at all goes to `watchlist`, never duplicated
into `board`.

DATA_QUALITY is intentionally left unmapped in this pass -- every
Router decision therefore resolves to UNKNOWN via DATA_QUALITY_UNKNOWN
rather than a guessed "OK". Wiring a real Data Quality Supervisor is
separate follow-up work, not something to fabricate here.

Still unmapped, no verified source found/chosen yet: SCALP, SWING,
TOB_MA, KIOXIA_DEDICATED, GLOBAL_MACRO, MARKET_REGIME, RISK_SAFETY,
SHADOW_EXECUTION, RECONCILIATION, CALIBRATION, JOURNAL_CONTENT_EXPORT,
CHIEF_AI_STRATEGY. signals.json's
daily_capitulation_reversals is currently always empty in this
repository, so no mapping for it has been verified against real data;
do not add one until it is.
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
LANE_STALE_AFTER_SECONDS, matching its natural horizon; a viewer
looking at this page much later than generation also needs its own
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
from scripts.ai_strategy_live_view import build_live_board_view, build_supervisor_row, ROUTER_STATE_LABELS
from scripts.strategy_router import route_snapshot, FEATURE_FLAG_LIVE_INFLUENCE_ENABLED

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "ai-strategy-live-board-1.0"
OUTPUT_PATH = Path("ai_strategy_live.json")
SIGNALS_PATH = Path("signals.json")

SUPERVISOR_ORDER = [
    "SCALP", "EVENT", "REALTIME_DAYTRADE", "OVERNIGHT", "SWING",
    "VALUE_LONG_CATALYST", "TOB_MA", "KIOXIA_DEDICATED", "GLOBAL_MACRO",
]

CONNECTED_SUPERVISORS = {"REALTIME_DAYTRADE", "EVENT", "OVERNIGHT", "VALUE_LONG_CATALYST"}

# provenance strings whose upstream section is an already-selected TOP5
# (see the module docstring's per-source trace). Only these make a
# symbol CARD-eligible; everything else is WATCHLIST-eligible only.
CARD_QUALIFYING_PROVENANCE = {
    "signals.json:overnight_long",
    "signals.json:overnight_short",
    "signals.json:speculative_theme_watch",
    "signals.json:monthly_weekly_hammers",
    "signals.json:long_term_ma_rebounds",
}

LANE_STALE_AFTER_SECONDS = {
    "OVERNIGHT": 20 * 60 * 60,
    "REALTIME_DAYTRADE": 20 * 60 * 60,
    "EVENT": 24 * 60 * 60,
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
    a JST-aware ISO string. Returns None if missing/unparseable. There
    is deliberately no "or now" fallback anywhere in this module.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.strptime(value.replace(" JST", ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=JST).isoformat()


def _emit(states, unresolved, card_symbols, symbol_names, *, supervisor, ticker, direction, as_of_value, provenance, name=None, **fields):
    """Shared row builder for every mapping below.

    If as_of_value is None (see _as_of()), the row is recorded in
    `unresolved` with reason TIMESTAMP_UNAVAILABLE instead of being
    built with a fabricated time. On success, if `provenance` is in
    CARD_QUALIFYING_PROVENANCE, the ticker is added to `card_symbols`
    (a set, shared across the whole build) so build_artifact() can
    later route every symbol's full set of lanes to either the card
    board or the compact watchlist, never both.

    `name` is signals.json's own "name" field for this row (e.g.
    "キオクシアHD（285A）") -- an existing, already-verified display name
    from the same pipeline, not a new lookup. It is recorded into
    `symbol_names` (ticker -> name, first-seen wins) regardless of
    whether the row itself ends up card/watchlist/unresolved, since the
    name is a property of the symbol, not of this one row. It is never
    passed into build_supervisor_state() (not a STATE_FIELDS member).
    """
    if not ticker:
        return
    if name:
        symbol_names.setdefault(ticker, name)
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
        return
    if provenance in CARD_QUALIFYING_PROVENANCE:
        card_symbols.add(ticker)


def _overnight_rows(states, unresolved, card_symbols, symbol_names, rows, direction, fallback_as_of):
    for r in rows:
        _emit(states, unresolved, card_symbols, symbol_names, supervisor="OVERNIGHT", ticker=r.get("ticker"), direction=direction,
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of),
              provenance="signals.json:overnight_" + direction.lower(), name=r.get("name"),
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def _event_rows(states, unresolved, card_symbols, symbol_names, rows, signals_as_of):
    """Legacy EVENT key is retained for compatibility; semantics are MOMENTUM/急騰.

    Catalyst/news confirmation is enrichment, not an admission requirement. Rows
    without a verified catalyst remain eligible and should display 材料未確認 rather
    than being rejected solely for lacking a news explanation.
    """
    for r in rows:
        _emit(states, unresolved, card_symbols, symbol_names, supervisor="EVENT", ticker=r.get("ticker"), direction="WATCH",
              as_of_value=signals_as_of, provenance="signals.json:speculative_theme_watch", name=r.get("name"),
              condition_score=r.get("score"))


def _value_long_catalyst_rows(states, unresolved, card_symbols, symbol_names, hammer_rows, ma_rebound_rows, accumulation_rows, fallback_as_of):
    """VALUE_LONG_CATALYST draws from three signals.json lists that can
    overlap on the same ticker (e.g. one symbol with both an
    accumulation footprint and a monthly/weekly hammer). It is one
    Supervisor, so it can only report one direction per symbol --
    silently keeping whichever candidate happened to be built last
    would quietly drop the other's evidence. Resolve by taking the
    most specific/confident candidate in a fixed, disclosed order
    (hammer/MA-rebound TOP5 evidence over the wider accumulation pool),
    not by build order.
    """
    candidates = {}
    for r in hammer_rows:
        ticker = r.get("ticker")
        if ticker:
            candidates.setdefault(ticker, []).append(
                (0, "LONG_WATCH", r, "signals.json:monthly_weekly_hammers"))
    for r in ma_rebound_rows:
        ticker = r.get("ticker")
        if ticker:
            candidates.setdefault(ticker, []).append(
                (0, "LONG_WATCH", r, "signals.json:long_term_ma_rebounds"))
    for r in accumulation_rows:
        ticker = r.get("ticker")
        if ticker:
            candidates.setdefault(ticker, []).append(
                (1, "LONG_WATCH", r, "signals.json:large_lot_accumulation"))

    for ticker, options in candidates.items():
        _, direction, r, provenance = min(options, key=lambda o: o[0])
        _emit(states, unresolved, card_symbols, symbol_names, supervisor="VALUE_LONG_CATALYST", ticker=ticker, direction=direction,
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of), provenance=provenance, name=r.get("name"),
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def _realtime_daytrade_rows(states, unresolved, card_symbols, symbol_names, rows, fallback_as_of):
    """signals.json:prepared is update.py's "⑨ 本日準備点灯銘柄 上位30"
    section, confirmed via scripts/weekly_tabs.py's routing
    (t.includes("準備点灯")) to be the real REALTIME 5 tab's own data --
    not SCALP (see the module docstring for why SCALP itself has no
    signals.json source at all). A 30-wide candidate pool, not an
    existing TOP5 -- these rows are always WATCHLIST-eligible only
    (never added to card_symbols) unless the same ticker separately
    qualifies via a card-worthy source above.
    """
    for r in rows:
        _emit(states, unresolved, card_symbols, symbol_names, supervisor="REALTIME_DAYTRADE", ticker=r.get("ticker"), direction="LONG_WATCH",
              as_of_value=_as_of(r.get("signal_date"), fallback_as_of),
              provenance="signals.json:prepared", name=r.get("name"),
              entry=r.get("trigger"), stop=r.get("stop"), target=r.get("target1"),
              condition_score=r.get("score"))


def build_states(signals, now_iso):
    """Returns (states, unresolved, card_symbols, symbol_names). `now_iso`
    is used only as the Router's decision-time "now" for freshness
    comparisons downstream -- it is never used as a row's own as_of.
    `symbol_names` maps ticker -> signals.json's own "name" field (e.g.
    "キオクシアHD（285A）"), for display; see _emit()'s docstring.
    """
    signals_as_of = _parse_signals_updated_at(signals.get("updated_at"))
    states, unresolved, card_symbols, symbol_names = [], [], set(), {}
    _overnight_rows(states, unresolved, card_symbols, symbol_names, signals.get("overnight_long") or [], "LONG", signals_as_of)
    _overnight_rows(states, unresolved, card_symbols, symbol_names, signals.get("overnight_short") or [], "SHORT", signals_as_of)
    _event_rows(states, unresolved, card_symbols, symbol_names, signals.get("speculative_theme_watch") or [], signals_as_of)
    _value_long_catalyst_rows(
        states, unresolved, card_symbols, symbol_names,
        signals.get("monthly_weekly_hammers") or [],
        signals.get("long_term_ma_rebounds") or [],
        signals.get("large_lot_accumulation") or [],
        signals_as_of,
    )
    _realtime_daytrade_rows(states, unresolved, card_symbols, symbol_names, signals.get("prepared") or [], signals_as_of)
    return states, unresolved, card_symbols, symbol_names


def _watchlist_entry(symbol, snapshot_entry, router_decision, symbol_name):
    """One compact watchlist row: the symbol, its most notable reporting
    Supervisor (first in SUPERVISOR_ORDER order, for a stable, non-
    arbitrary pick), that Supervisor's direction, freshness and the
    Router's own state -- expandable to the full per-Supervisor detail
    via `rows` (same shape as a card's rows), so nothing is hidden,
    just presented compactly by default.

    Uses build_supervisor_row()'s own default stale_after_seconds (a
    single number, not LANE_STALE_AFTER_SECONDS's per-supervisor dict --
    that view-layer helper only accepts a single threshold), matching
    build_live_board_view()'s existing call below for the card side, so
    the "is_stale" display flag means the same thing on both the card
    and the watchlist. The Router's own per-supervisor freshness gating
    (which DOES use the per-supervisor dict, see route_snapshot() above)
    already governs router_state/router_reasons independently of this
    display-only flag.
    """
    supervisors = snapshot_entry["supervisors"]
    ordered_keys = [k for k in SUPERVISOR_ORDER if k in supervisors] + sorted(k for k in supervisors if k not in SUPERVISOR_ORDER)
    # 300 mirrors build_symbol_card_view()'s own stale_after_seconds=300
    # default in scripts/ai_strategy_live_view.py, so a card and a
    # watchlist row report "is_stale" on the same basis.
    rows = [build_supervisor_row(supervisors[k], 300) for k in ordered_keys]
    headline = rows[0]
    r = router_decision
    return {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "headline_supervisor": headline["supervisor"],
        "headline_direction": headline["direction"],
        "headline_direction_label": headline["direction_label"],
        "headline_css_class": headline["css_class"],
        "headline_is_stale": headline["is_stale"],
        "rows": rows,
        "router_state": r["state"],
        "router_state_label": ROUTER_STATE_LABELS.get(r["state"], {"label": r["state"]})["label"],
        "router_css_class": ROUTER_STATE_LABELS.get(r["state"], {"css_class": "unknown"})["css_class"],
        "router_reasons": r["reasons"],
        "is_entry_trigger": False,
        "real_submit_allowed": False,
    }


def build_artifact(signals, now_iso, data_quality_ok_by_symbol=None):
    if FEATURE_FLAG_LIVE_INFLUENCE_ENABLED is not False:
        raise AssertionError(
            "refusing to build the AI Strategy LIVE artifact: "
            "FEATURE_FLAG_LIVE_INFLUENCE_ENABLED must be False in Phase 2"
        )
    states, unresolved, card_symbols, symbol_names = build_states(signals, now_iso)
    snapshot = strategy_live_snapshot(states, now_iso)
    decisions = route_snapshot(snapshot, now_iso, data_quality_ok_by_symbol=data_quality_ok_by_symbol,
                                stale_after_seconds=LANE_STALE_AFTER_SECONDS)

    card_snapshot = {sym: entry for sym, entry in snapshot.items() if sym in card_symbols}
    card_decisions = {sym: dec for sym, dec in decisions.items() if sym in card_symbols}
    board = build_live_board_view(card_snapshot, card_decisions, supervisor_order=SUPERVISOR_ORDER)
    for card in board:
        card["symbol_name"] = symbol_names.get(card["symbol"])

    watchlist = [
        _watchlist_entry(sym, snapshot[sym], decisions[sym], symbol_names.get(sym))
        for sym in sorted(snapshot)
        if sym not in card_symbols
    ]

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
        "watchlist": watchlist,
    }


def main():
    now_iso = datetime.now(JST).isoformat()
    signals = json.loads(SIGNALS_PATH.read_text(encoding="utf-8")) if SIGNALS_PATH.exists() else {}
    artifact = build_artifact(signals, now_iso)
    OUTPUT_PATH.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"ai_strategy_live.json written: {len(artifact['board'])} cards, "
          f"{len(artifact['watchlist'])} watchlist rows, {len(artifact['data_issues'])} data issues")


if __name__ == "__main__":
    main()
