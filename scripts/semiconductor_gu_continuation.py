#!/usr/bin/env python3
"""Semiconductor GU Continuation LIVE MVP (Issue #173 / C-114).

Pure, deterministic research/advisory logic only. This module never fetches
or synthesizes OHLCV data; it only interprets already-computed read-only
fields (OR5/OR15/VWAP/EMA/volume/flow) that a caller supplies per symbol.
It produces no order, no RssOrder, no broker/real-submit signal, and no
formal BUY/SHORT decision -- only an advisory state for the Owner-facing
LIVE panel.

Input record contract (per symbol, all fields optional/None when unknown):
    updated_at   ISO-8601 timestamp of the freshest field in this record
    price        current price
    open         today's session open (or None pre-open)
    prev_close   previous session close
    vwap         intraday VWAP
    ema9/ema20   5-minute EMA9/EMA20
    or5_high/or5_low    opening-range(5m) high/low; None while still forming
    or15_high/or15_low  opening-range(15m) high/low; None while still forming
    volume_burst RVOL-style volume acceleration multiplier
    flow_bias    signed tape/board flow bias (positive = buy-leaning); None
                 when no flow/board source is available -- never inferred
    stale        optional explicit staleness flag from the source collector

R1 scope note: the OVERNIGHT/SWING continuation lane (see
evaluate_no_pullback_lane) has no historical EV/PF/DD database wired yet
(that is P5 Strategy Router / OOS work). It therefore always reports
INSUFFICIENT_SAMPLE except when intraday invalidation forces a BLOCK, so it
never fabricates an expected-value ranking from a single snapshot.
"""
import json
from pathlib import Path

from scripts.time_utils import parse_market_ts, assert_observed_by

FIXED_UNIVERSE = ["285A", "6857", "8035", "6146", "6920"]

SYMBOL_NAMES = {
    "285A": "キオクシアHD",
    "6857": "アドバンテスト",
    "8035": "東京エレクトロン",
    "6146": "ディスコ",
    "6920": "レーザーテック",
}

DAYTRADE_STATES = frozenset([
    "PREOPEN_GU_WATCH", "OR5_FORMING", "GU_CONTINUATION_CANDIDATE",
    "PULLBACK_RECLAIM_CANDIDATE", "OR15_CONFIRMATION", "GU_EXHAUSTION_WARNING",
    "LONG_INVALIDATED", "WAIT_DATA", "CLOSED", "UNKNOWN",
])

HORIZON_STATES = frozenset([
    "OVERNIGHT_CONTINUATION_CANDIDATE", "OVERNIGHT_BLOCK",
    "SWING_CONTINUATION_CANDIDATE", "SWING_WAIT", "SWING_BLOCK",
    "INSUFFICIENT_SAMPLE",
])

MACRO_FIELDS = ["nikkei_futures", "sox_nasdaq", "usdjpy", "us_rates", "vix"]

DEFAULT_CONFIG = {
    "freshness_max_age_seconds": 60,
    "gap_buckets": [(0.0, 1.0, "GU_SMALL"), (1.0, 3.0, "GU_MEDIUM"), (3.0, None, "GU_LARGE")],
    "exhaustion_min_signals": 2,
    "volume_expansion_threshold": 1.5,
}


def load_universe(path=None):
    """Config-driven universe override. Falls back to FIXED_UNIVERSE when
    absent. Never silently repairs a malformed config -- raises instead."""
    if not path:
        return list(FIXED_UNIVERSE)
    p = Path(path)
    if not p.exists():
        return list(FIXED_UNIVERSE)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data or not all(isinstance(c, str) and c for c in data):
        raise ValueError("invalid universe config: expected a non-empty list of ticker codes")
    return data


def _cmp(a, b):
    if a is None or b is None:
        return None
    if a > b:
        return "above"
    if a < b:
        return "below"
    return "at"


def classify_gap(open_, prev_close, config):
    if open_ is None or prev_close is None or prev_close == 0:
        return {"gap_pct": None, "bucket": None}
    gap_pct = (open_ - prev_close) / prev_close * 100.0
    if gap_pct < 0:
        bucket = "GD"
    elif gap_pct == 0:
        bucket = "FLAT"
    else:
        bucket = None
        for lo, hi, name in config["gap_buckets"]:
            if gap_pct >= lo and (hi is None or gap_pct < hi):
                bucket = name
                break
    return {"gap_pct": round(gap_pct, 4), "bucket": bucket}


def _evaluate_freshness(observed_at, now, max_age_seconds):
    if not observed_at:
        return False, None, "MISSING_TIMESTAMP"
    try:
        obs, dec = assert_observed_by(observed_at, now)
    except ValueError as e:
        reason = "FUTURE_TIMESTAMP" if "future information" in str(e) else "UNPARSEABLE_TIMESTAMP"
        return False, None, reason
    age = (dec - obs).total_seconds()
    if age > max_age_seconds:
        return False, age, "STALE_DATA"
    return True, age, None


def evaluate_symbol(code, record, now, config=None):
    """Evaluate one symbol's GU-continuation advisory state. Deterministic:
    same (code, record, now, config) always yields the same result."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    record = record or {}

    result = {
        "code": code,
        "name": SYMBOL_NAMES.get(code),
        "state": "UNKNOWN",
        "fail_closed": False,
        "fail_reason": None,
        "gap_pct": None,
        "gap_bucket": None,
        "price_vs_open": None,
        "vwap_relation": None,
        "or5": {"state": "UNKNOWN", "high": None, "low": None, "price_vs_high": None, "price_vs_low": None},
        "or15": {"state": "UNKNOWN", "high": None, "low": None, "price_vs_high": None, "price_vs_low": None, "breakout": None},
        "ema_state": None,
        "volume_state": None,
        "flow_state": None,
        "freshness": {"observed_at": record.get("updated_at"), "age_seconds": None, "stale": True},
        "evidence": [],
    }

    if record.get("stale") is True:
        result["freshness"]["stale"] = True
        result["state"] = "WAIT_DATA"
        result["fail_closed"] = True
        result["fail_reason"] = "STALE_DATA"
        result["evidence"].append("fail_closed:STALE_DATA")
        return result

    fresh_ok, age, reason = _evaluate_freshness(record.get("updated_at"), now, cfg["freshness_max_age_seconds"])
    result["freshness"]["age_seconds"] = age
    result["freshness"]["stale"] = not fresh_ok
    if not fresh_ok:
        result["fail_closed"] = True
        result["fail_reason"] = reason
        result["evidence"].append(f"fail_closed:{reason}")
        result["state"] = "WAIT_DATA" if reason in ("MISSING_TIMESTAMP", "STALE_DATA") else "UNKNOWN"
        return result

    price = record.get("price")
    open_ = record.get("open")
    prev_close = record.get("prev_close")

    gap = classify_gap(open_, prev_close, cfg)
    result["gap_pct"] = gap["gap_pct"]
    result["gap_bucket"] = gap["bucket"]

    if price is None:
        if open_ is not None and prev_close is not None:
            result["state"] = "PREOPEN_GU_WATCH"
            result["evidence"].append("preopen_indicative_quote_only")
        else:
            result["state"] = "WAIT_DATA"
            result["fail_reason"] = "MISSING_CORE_FIELDS"
            result["evidence"].append("missing_open_or_prev_close")
        return result

    if open_ is None or prev_close is None:
        result["state"] = "WAIT_DATA"
        result["fail_reason"] = "MISSING_CORE_FIELDS"
        result["evidence"].append("missing_open_or_prev_close")
        return result

    if gap["bucket"] in (None, "GD", "FLAT"):
        result["state"] = "UNKNOWN"
        result["fail_reason"] = "NOT_A_GAP_UP"
        result["evidence"].append("no_qualifying_gap_up")
        return result

    vwap = record.get("vwap")
    ema9 = record.get("ema9")
    ema20 = record.get("ema20")
    or5_high = record.get("or5_high")
    or5_low = record.get("or5_low")
    or15_high = record.get("or15_high")
    or15_low = record.get("or15_low")
    volume_burst = record.get("volume_burst")
    flow_bias = record.get("flow_bias")

    result["price_vs_open"] = _cmp(price, open_)
    result["vwap_relation"] = _cmp(price, vwap)

    or5_complete = or5_high is not None and or5_low is not None
    result["or5"]["state"] = "COMPLETE" if or5_complete else "FORMING"
    result["or5"]["high"] = or5_high
    result["or5"]["low"] = or5_low
    if or5_complete:
        result["or5"]["price_vs_high"] = _cmp(price, or5_high)
        result["or5"]["price_vs_low"] = _cmp(price, or5_low)

    or15_complete = or15_high is not None and or15_low is not None
    result["or15"]["state"] = "COMPLETE" if or15_complete else "FORMING"
    result["or15"]["high"] = or15_high
    result["or15"]["low"] = or15_low
    if or15_complete:
        result["or15"]["price_vs_high"] = _cmp(price, or15_high)
        result["or15"]["price_vs_low"] = _cmp(price, or15_low)
        if price > or15_high:
            result["or15"]["breakout"] = "ABOVE"
        elif price < or15_low:
            result["or15"]["breakout"] = "BELOW"
        else:
            result["or15"]["breakout"] = "INSIDE"

    if ema9 is not None and ema20 is not None:
        result["ema_state"] = "BULLISH" if ema9 > ema20 else "BEARISH" if ema9 < ema20 else "FLAT"

    if volume_burst is not None:
        result["volume_state"] = "EXPANDING" if volume_burst >= cfg["volume_expansion_threshold"] else "NORMAL"

    if flow_bias is not None:
        result["flow_state"] = "BUY_LEAN" if flow_bias > 0 else "SELL_LEAN" if flow_bias < 0 else "NEUTRAL"

    lost_open = result["price_vs_open"] == "below"
    lost_vwap = result["vwap_relation"] == "below"
    broke_or5_low = or5_complete and result["or5"]["price_vs_low"] == "below"
    broke_or15_low = or15_complete and result["or15"]["price_vs_low"] == "below"

    if lost_open and lost_vwap and (broke_or5_low or broke_or15_low):
        result["state"] = "LONG_INVALIDATED"
        result["evidence"].append("lost_open")
        result["evidence"].append("lost_vwap")
        if broke_or5_low:
            result["evidence"].append("broke_or5_low")
        if broke_or15_low:
            result["evidence"].append("broke_or15_low")
        return result

    exhaustion_signals = []
    if gap["bucket"] == "GU_LARGE":
        exhaustion_signals.append("large_gap")
    if lost_vwap:
        exhaustion_signals.append("lost_vwap")
    if lost_open:
        exhaustion_signals.append("lost_open")
    if broke_or5_low:
        exhaustion_signals.append("broke_or5_low")
    if result["volume_state"] == "EXPANDING" and result["ema_state"] == "BEARISH":
        exhaustion_signals.append("volume_spike_momentum_loss")

    if len(exhaustion_signals) >= cfg["exhaustion_min_signals"]:
        result["state"] = "GU_EXHAUSTION_WARNING"
        result["evidence"].extend(exhaustion_signals)
        return result

    if or15_complete:
        result["state"] = "OR15_CONFIRMATION"
        result["evidence"].append(f"or15_breakout:{result['or15']['breakout']}")
        return result

    if or5_complete:
        holding_above = result["price_vs_open"] == "above" and result["vwap_relation"] in ("above", "at")
        pulled_back = result["or5"]["price_vs_high"] == "below" and result["or5"]["price_vs_low"] in ("above", "at")
        if pulled_back and result["vwap_relation"] in ("above", "at"):
            result["state"] = "PULLBACK_RECLAIM_CANDIDATE"
            result["evidence"].append("pullback_holding_vwap_and_or5_low")
        elif holding_above and result["or5"]["price_vs_high"] in ("above", "at"):
            result["state"] = "GU_CONTINUATION_CANDIDATE"
            result["evidence"].append("holding_above_open_vwap_or5_high")
        else:
            result["state"] = "WAIT_DATA"
            result["fail_reason"] = "AMBIGUOUS_OR5_STRUCTURE"
        return result

    result["state"] = "OR5_FORMING"
    result["evidence"].append("or5_not_yet_complete")
    return result


def evaluate_universe(records, now, config=None, universe=None):
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    uni = universe or FIXED_UNIVERSE
    return [evaluate_symbol(code, (records or {}).get(code), now, cfg) for code in uni]


def evaluate_no_pullback_lane(daytrade_state, session_states_seen=None):
    """Second decision lane: DAYTRADE_MISSED_NO_PULLBACK -> OVERNIGHT/SWING.

    R1 has no historical EV/PF/DD sample database wired in, so this always
    reports INSUFFICIENT_SAMPLE unless intraday state already invalidated
    the setup, in which case it blocks the longer horizons outright."""
    seen = set(session_states_seen or [])
    pullback_seen = "PULLBACK_RECLAIM_CANDIDATE" in seen

    if daytrade_state in ("LONG_INVALIDATED", "GU_EXHAUSTION_WARNING"):
        return {
            "daytrade_missed_no_pullback": False,
            "overnight_state": "OVERNIGHT_BLOCK",
            "swing_state": "SWING_BLOCK",
            "sample_n": 0,
            "evidence": ["intraday_invalidation_blocks_continuation_horizons"],
        }

    missed = daytrade_state in ("GU_CONTINUATION_CANDIDATE", "OR15_CONFIRMATION") and not pullback_seen
    evidence = ["no_historical_ev_pf_dd_database_wired_in_r1"]
    if missed:
        evidence.insert(0, "no_clean_intraday_pullback_observed")

    return {
        "daytrade_missed_no_pullback": missed,
        "overnight_state": "INSUFFICIENT_SAMPLE",
        "swing_state": "INSUFFICIENT_SAMPLE",
        "sample_n": 0,
        "evidence": evidence,
    }


def compute_breadth(symbol_results):
    n = len(symbol_results)
    above_open = sum(1 for s in symbol_results if s["price_vs_open"] == "above")
    above_vwap = sum(1 for s in symbol_results if s["vwap_relation"] == "above")
    above_or5_high = sum(1 for s in symbol_results if s["or5"]["state"] == "COMPLETE" and s["or5"]["price_vs_high"] == "above")
    invalidated = sum(1 for s in symbol_results if s["state"] == "LONG_INVALIDATED")
    stale = sum(1 for s in symbol_results if s["freshness"]["stale"])
    return {
        "universe_n": n,
        "above_open_n": above_open,
        "above_vwap_n": above_vwap,
        "above_or5_high_n": above_or5_high,
        "invalidated_n": invalidated,
        "stale_n": stale,
        "note": "sector context only; never majority-voted into a trade decision",
    }


def summarize(symbol_results, breadth):
    n = breadth["universe_n"]
    if n == 0 or breadth["stale_n"] > n / 2:
        return "WAIT_DATA"
    exhaustion_n = sum(1 for s in symbol_results if s["state"] in ("LONG_INVALIDATED", "GU_EXHAUSTION_WARNING"))
    continuation_n = sum(
        1 for s in symbol_results
        if s["state"] in ("GU_CONTINUATION_CANDIDATE", "OR15_CONFIRMATION")
        and s["or15"].get("breakout") != "BELOW"
    )
    if exhaustion_n > n / 2:
        return "EXHAUSTION_RISK"
    if continuation_n > n / 2:
        return "CONTINUATION_BIAS"
    return "MIXED"


def normalize_macro(macro):
    """Global macro is a Regime Modifier only, never a direct entry trigger.
    Unavailable fields stay UNKNOWN instead of being invented."""
    macro = macro or {}
    out = {}
    for f in MACRO_FIELDS:
        v = macro.get(f)
        out[f] = {"value": v, "state": "UNKNOWN"} if v is None else {"value": v, "state": "AVAILABLE"}
    out["role"] = "regime_modifier_only"
    return out


def build_panel(records, now, macro=None, config=None, universe=None, session_states_seen=None):
    """Build the full Owner-facing LIVE panel for the fixed semiconductor
    GU-continuation universe. Pure function of its inputs -- no I/O, no
    wall-clock reads, no randomness -- so identical inputs always produce
    an identical panel (point-in-time, no lookahead)."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    uni = universe or FIXED_UNIVERSE
    symbol_results = evaluate_universe(records, now, cfg, uni)
    seen_map = session_states_seen or {}
    for s in symbol_results:
        s["horizon"] = evaluate_no_pullback_lane(s["state"], seen_map.get(s["code"]))
    breadth = compute_breadth(symbol_results)
    generated_at = parse_market_ts(now).isoformat()
    return {
        "schema_version": "gu_continuation_panel_v1",
        "generated_at": generated_at,
        "universe": list(uni),
        "symbols": symbol_results,
        "breadth": breadth,
        "macro": normalize_macro(macro),
        "summary": summarize(symbol_results, breadth),
        "research_only": True,
        "auto_execute": False,
    }
