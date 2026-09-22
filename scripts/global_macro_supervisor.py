#!/usr/bin/env python3
"""Global Macro Supervisor / Yield Curve Engine (Master Spec 4.7.3, C-113).

Schema validation, point-in-time-safe yield-curve classification, and a
non-triggering Regime Modifier output only. Data acquisition and LIVE
reflection are a separate, later stage per C-113 and are out of scope here.

Output is always a Regime Modifier, never a BUY/SHORT trigger:
- real_submit_allowed is always False;
- is_entry_trigger is always False at every level of the output;
- nothing here bypasses Risk Gate, Permission Gate, Conflict Resolver or
  Owner approval;
- OR5/OR15/VWAP/EMA/Flow entry triggers remain separately defined elsewhere.

Curve-regime classification is a disclosed, versioned heuristic
(CURVE_REGIME_CLASSIFIER_VERSION) operating on observed yield levels only.
It is descriptive, not a causal claim: it does not decompose growth-driven
vs inflation-driven rate moves, and it never guesses a state from missing
data. Any instrument with fewer than min_curve_history validated,
non-stale observations reports its curve as INSUFFICIENT_SAMPLE/UNKNOWN.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from scripts.time_utils import assert_observed_by

SCHEMA_VERSION = "global-macro-observation-1.0"
CURVE_REGIME_CLASSIFIER_VERSION = "curve-regime-v1"

INSTRUMENTS = frozenset({
    "US_3M", "US_2Y", "US_5Y", "US_10Y", "US_30Y",
    "JP_2Y", "JP_5Y", "JP_10Y", "JP_20Y", "JP_30Y", "JP_40Y",
    "US_JP_2Y_SPREAD", "US_JP_10Y_SPREAD",
    "REAL_YIELD", "BREAKEVEN_INFLATION",
    "WTI", "BRENT", "GOLD", "COPPER",
    "USDJPY", "VIX", "NIKKEI_FUTURES", "SOX", "NASDAQ",
})
ALLOWED_FIELDS = {"schema_version", "instrument", "value", "observed_at", "source", "correlation_id"}
REQUIRED_FIELDS = {"schema_version", "instrument", "value", "observed_at", "source"}

# Minimum yield-curve spreads required by Master Spec 4.7.3.
US_CURVE_PAIRS = {
    "US_3M10Y": ("US_3M", "US_10Y"),
    "US_2S10S": ("US_2Y", "US_10Y"),
    "US_5S30S": ("US_5Y", "US_30Y"),
    "US_10S30S": ("US_10Y", "US_30Y"),
}
JP_CURVE_PAIRS = {
    "JP_2S10S": ("JP_2Y", "JP_10Y"),
    "JP_5S10S": ("JP_5Y", "JP_10Y"),
    "JP_10S20S": ("JP_10Y", "JP_20Y"),
    "JP_10S30S": ("JP_10Y", "JP_30Y"),
    "JP_10S40S": ("JP_10Y", "JP_40Y"),
}
CURVE_PAIRS = {**US_CURVE_PAIRS, **JP_CURVE_PAIRS}

CURVE_REGIMES = {
    "BULL_STEEPENER", "BULL_FLATTENER", "BEAR_STEEPENER", "BEAR_FLATTENER",
    "INVERTED", "NORMALIZING", "UNKNOWN",
}


def _text_or_none(v):
    return v is None or isinstance(v, str)


def _require_aware(value):
    """Reject naive timestamps outright; this module never assumes a timezone.

    time_utils.parse_market_ts silently attaches JST to a naive timestamp,
    which is convenient elsewhere but not acceptable here: the master spec
    requires every macro observation to explicitly carry its timezone.
    """
    dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive timestamp: " + str(value))
    return dt


def validate_observation(obs):
    """Fail-closed schema validation for one point-in-time macro observation."""
    if not isinstance(obs, dict) or set(obs) - ALLOWED_FIELDS or not REQUIRED_FIELDS.issubset(obs):
        return False
    if obs.get("schema_version") != SCHEMA_VERSION:
        return False
    if obs.get("instrument") not in INSTRUMENTS:
        return False
    if isinstance(obs.get("value"), bool) or not isinstance(obs.get("value"), (int, float)):
        return False
    if not isinstance(obs.get("source"), str) or not obs["source"]:
        return False
    if not _text_or_none(obs.get("correlation_id")):
        return False
    try:
        _require_aware(obs["observed_at"])
    except (TypeError, ValueError):
        return False
    return True


def freshness_state(observed_at, as_of, stale_after=timedelta(hours=6)):
    """Point-in-time freshness check. Never infers a value for missing/stale data.

    A future observed_at relative to as_of is rejected the same as a stale
    one (fails closed to UNKNOWN) rather than silently accepted.
    """
    try:
        _require_aware(observed_at)
        _require_aware(as_of)
        obs, now = assert_observed_by(observed_at, as_of)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return "FRESH" if (now - obs) <= stale_after else "STALE"


def classify_curve_regime(short_change, long_change, spread_now, spread_prior):
    """Deterministic, versioned curve-regime classification (curve-regime-v1).

    Descriptive only: not a causal claim, not an entry trigger. Any missing
    input, or a spread that has not moved, resolves to UNKNOWN rather than
    guessing a direction. INVERTED/NORMALIZING still require a valid prior
    comparison point (via short_change/long_change) so a single observation
    can never claim inversion on its own.
    """
    if short_change is None or long_change is None or spread_now is None:
        return "UNKNOWN"
    if spread_prior is not None and spread_prior < 0 and spread_now >= 0:
        return "NORMALIZING"
    if spread_now < 0:
        return "NORMALIZING" if (spread_prior is not None and spread_now > spread_prior) else "INVERTED"
    if spread_prior is None:
        return "UNKNOWN"
    spread_change = spread_now - spread_prior
    if spread_change == 0:
        return "UNKNOWN"
    avg_change = (short_change + long_change) / 2
    steepening = spread_change > 0
    if steepening:
        return "BULL_STEEPENER" if avg_change <= 0 else "BEAR_STEEPENER"
    return "BULL_FLATTENER" if avg_change <= 0 else "BEAR_FLATTENER"


def yield_curve_state(curve_name, short_now, short_prior, long_now, long_prior):
    """One curve's point-in-time state. Inputs are plain yield levels (%).

    *_prior is the same tenor's level at the comparison lookback (e.g. the
    prior session); callers choose the lookback window (1/5/20-session).
    """
    if curve_name not in CURVE_PAIRS:
        raise ValueError("unknown curve: " + curve_name)
    base = {
        "curve": curve_name,
        "classifier_version": CURVE_REGIME_CLASSIFIER_VERSION,
        "regime_modifier": True,
        "is_entry_trigger": False,
    }
    if short_now is None or long_now is None:
        return {**base, "spread": None, "spread_change": None, "inverted": None, "regime": "UNKNOWN"}
    spread_now = long_now - short_now
    spread_prior = None
    short_change = None
    long_change = None
    if short_prior is not None and long_prior is not None:
        spread_prior = long_prior - short_prior
        short_change = short_now - short_prior
        long_change = long_now - long_prior
    regime = classify_curve_regime(short_change, long_change, spread_now, spread_prior)
    return {
        **base,
        "spread": spread_now,
        "spread_change": None if spread_prior is None else spread_now - spread_prior,
        "inverted": spread_now < 0,
        "regime": regime,
    }


def build_regime_modifier(observations, as_of, curve_lookbacks=None, min_curve_history=2, stale_after=timedelta(hours=6)):
    """Top-level Global Macro Supervisor output.

    `observations` is {instrument: [obs, ...]} with each instrument's list
    ordered oldest-to-newest. `curve_lookbacks` optionally maps a curve name
    to how many observations back its comparison point is (default: the
    previous observation, i.e. a 1-session change).

    Any single invalid observation disqualifies that whole instrument's
    series for this call (fail-closed v0.1 behaviour, not a partial-repair
    attempt) — the instrument then shows up in stale_or_missing_instruments
    and every curve depending on it reports INSUFFICIENT_SAMPLE.

    Output is a Regime Modifier only. It never sets real_submit_allowed=True,
    never proposes a BUY/SHORT trigger, and never bypasses Risk Gate,
    Permission Gate, Conflict Resolver or Owner approval.
    """
    curve_lookbacks = curve_lookbacks or {}
    usable = {}
    stale_or_missing = []
    for instrument in INSTRUMENTS:
        rows = observations.get(instrument) or []
        valid = [r for r in rows if validate_observation(r)]
        if not rows or len(valid) != len(rows):
            stale_or_missing.append(instrument)
            continue
        if freshness_state(valid[-1]["observed_at"], as_of, stale_after) != "FRESH":
            stale_or_missing.append(instrument)
            continue
        usable[instrument] = valid

    curves = {}
    for curve_name, (short_i, long_i) in CURVE_PAIRS.items():
        short_rows = usable.get(short_i)
        long_rows = usable.get(long_i)
        if not short_rows or not long_rows:
            state = yield_curve_state(curve_name, None, None, None, None)
            state["status"] = "INSUFFICIENT_SAMPLE"
            curves[curve_name] = state
            continue
        lookback = curve_lookbacks.get(curve_name, 1)
        short_now = short_rows[-1]["value"]
        long_now = long_rows[-1]["value"]
        if len(short_rows) < min_curve_history or len(long_rows) < min_curve_history or lookback >= len(short_rows) or lookback >= len(long_rows):
            state = yield_curve_state(curve_name, short_now, None, long_now, None)
            state["status"] = "INSUFFICIENT_SAMPLE"
        else:
            short_prior = short_rows[-1 - lookback]["value"]
            long_prior = long_rows[-1 - lookback]["value"]
            state = yield_curve_state(curve_name, short_now, short_prior, long_now, long_prior)
            state["status"] = "OK"
        curves[curve_name] = state

    return {
        "regime_modifier": True,
        "is_entry_trigger": False,
        "real_submit_allowed": False,
        "as_of": str(as_of),
        "stale_or_missing_instruments": sorted(stale_or_missing),
        "curves": curves,
    }
