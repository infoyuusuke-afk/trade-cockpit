"""Audit of the inputs that actually reach a LONG / SHORT / NO-TRADE decision.

The live entry is the collector signal string. AI SHADOW obeys that string
through entry_candidate and does not rescore the board. This module does not
change that rule, does not submit, and does not treat an observational
association as a live pass.

Grades:
  A  used by the live decision
  B  present on the live row or a live side list, and not used for that decision
  C  code exists elsewhere and is not wired into the live decision
  D  no implementation
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ai_shadow_supervisor as shadow

CREDIT_RATIO_BIN = 3.0
MIN_BIN_COUNT = 8

# id, grade, scope. scope is "intraday_signal" or "overnight_hold".
# An A grade changes that scope. It is not a weight invented here.
CATALOG = (
    {"id": "or5", "grade": "A", "scope": "intraday_signal"},
    {"id": "or10", "grade": "D", "scope": ""},
    {"id": "or15", "grade": "A", "scope": "intraday_signal"},
    {"id": "or20", "grade": "D", "scope": ""},
    {"id": "vwap", "grade": "A", "scope": "intraday_signal"},
    {"id": "ema9_20", "grade": "A", "scope": "intraday_signal"},
    {"id": "bollinger", "grade": "D", "scope": ""},
    {"id": "volume_acceleration", "grade": "A", "scope": "intraday_signal"},
    {"id": "gap_gu_gd", "grade": "A", "scope": "intraday_signal"},
    {"id": "special_quote", "grade": "A", "scope": "intraday_signal"},
    {"id": "best_bid_ask", "grade": "A", "scope": "intraday_signal"},
    {"id": "board_depth10", "grade": "D", "scope": ""},
    {"id": "tape", "grade": "A", "scope": "intraday_signal"},
    {"id": "market_order_qty", "grade": "A", "scope": "intraday_signal"},
    {"id": "over_under", "grade": "A", "scope": "intraday_signal"},
    {"id": "spread", "grade": "A", "scope": "intraday_signal"},
    {"id": "imbalance", "grade": "A", "scope": "intraday_signal"},
    {"id": "trade_speed", "grade": "D", "scope": ""},
    {"id": "time_band", "grade": "A", "scope": "intraday_signal"},
    {"id": "market_breadth", "grade": "A", "scope": "intraday_signal"},
    {"id": "margin_buy_balance", "grade": "B", "scope": "intraday_signal"},
    {"id": "margin_sell_balance", "grade": "B", "scope": "intraday_signal"},
    {"id": "credit_ratio", "grade": "B", "scope": "intraday_signal"},
    {"id": "credit_evaluation_loss", "grade": "D", "scope": ""},
    {"id": "short_sale_ratio", "grade": "D", "scope": ""},
    {"id": "institutional_short", "grade": "C", "scope": ""},
    {"id": "arbitrage_balance", "grade": "D", "scope": ""},
    {"id": "margin_daily_designation", "grade": "C", "scope": ""},
    {"id": "reverse_fee", "grade": "D", "scope": ""},
    {"id": "nikkei225_futures_price", "grade": "C", "scope": ""},
    {"id": "topix_futures", "grade": "D", "scope": ""},
    {"id": "nt_ratio", "grade": "D", "scope": ""},
    {"id": "investor_futures_flow", "grade": "A", "scope": "overnight_hold"},
    {"id": "futures_open_interest", "grade": "D", "scope": ""},
    {"id": "nikkei225_options", "grade": "D", "scope": ""},
    {"id": "put_call", "grade": "D", "scope": ""},
    {"id": "implied_vol", "grade": "D", "scope": ""},
    {"id": "strike_concentration", "grade": "D", "scope": ""},
    {"id": "sq_calendar", "grade": "C", "scope": ""},
    {"id": "us_index_sox", "grade": "C", "scope": ""},
    {"id": "us_rates", "grade": "C", "scope": ""},
    {"id": "usdjpy", "grade": "C", "scope": ""},
    {"id": "crude_gold_copper", "grade": "C", "scope": ""},
    {"id": "silver", "grade": "D", "scope": ""},
    {"id": "korea_equity", "grade": "D", "scope": ""},
    {"id": "macro_event_calendar", "grade": "C", "scope": ""},
    {"id": "official_speech", "grade": "D", "scope": ""},
    {"id": "earnings_estimates", "grade": "C", "scope": ""},
    {"id": "tdnet_material", "grade": "B", "scope": "after_close_pts"},
    {"id": "segments_cashflow_valuation", "grade": "D", "scope": ""},
    {"id": "shikiho_midplan", "grade": "D", "scope": ""},
)

ROADMAP = (
    "marginal_ev_ledger",
    "credit_already_on_the_live_row",
    "earnings_event_veto",
    "prior_close_us_semiconductor",
    "options_cross_asset_fundamentals",
)

_CREDIT_FIELDS = ("credit_buy", "credit_sell", "credit_ratio", "credit_buy_change", "credit_sell_change", "shortable_quantity")


def grade_of(input_id: str) -> str:
    for item in CATALOG:
        if item["id"] == input_id:
            return item["grade"]
    raise KeyError(input_id)


def engine_verdict() -> dict:
    """The live brain is a fixed rule, read from the collector and shadow code."""
    return {
        "engine": "FIXED_RULE",
        "statistical_expectancy": False,
        "strategy_competition": False,
        "real_submit_allowed": False,
    }


def live_side(row: dict) -> str:
    """The side AI SHADOW would take. Credit fields are not an input."""
    candidate = shadow.entry_candidate(row if isinstance(row, dict) else {})
    if candidate is None:
        return "NO_TRADE"
    return candidate["side"]


def _aware(value, decided_at: datetime):
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=decided_at.tzinfo)
    return value


def _credit_status(row: dict, field: str, decided_at: datetime) -> str:
    if not isinstance(row, dict) or not shadow._finite(row.get(field)):
        return "ABSENT"
    observed = _aware(row.get(field + "_observed_at"), decided_at)
    if observed is None:
        return "UNSTAMPED"
    if observed > decided_at:
        return "LOOKAHEAD_EXCLUDED"
    return "PRESENT"


def information_value_record(row: dict, *, realized_pnl_per_share, decided_at: datetime) -> dict:
    """Snapshot one decision without changing it.

    B inputs that the live rule ignores keep ev_if_used empty. A stamped
    credit ratio is binned for a later observational comparison. The bin is
    not an entry weight.
    """
    side = live_side(row)
    traded = side in {"LONG", "SHORT"}
    baseline = realized_pnl_per_share if traded and shadow._finite(realized_pnl_per_share) else (0.0 if not traded else None)
    credit_state = _credit_status(row, "credit_ratio", decided_at)
    ratio_bin = ""
    if credit_state == "PRESENT":
        ratio_bin = "HIGH" if float(row.get("credit_ratio")) >= CREDIT_RATIO_BIN else "LOW"
    observed = {}
    for field in _CREDIT_FIELDS:
        observed[field] = {
            "status": _credit_status(row, field, decided_at),
            "grade": "B",
        }
    return {
        "engine": "FIXED_RULE",
        "live_side": side,
        "baseline_ev_yen_per_share": baseline,
        "credit_ratio_bin": ratio_bin,
        "credit_fields": observed,
        "ev_if_credit_removed": baseline,
        "ev_if_credit_used": None,
        "measurement_status": "UNMEASURED_NOT_IN_LIVE_RULE" if credit_state == "PRESENT" else credit_state,
        "acceptance_class": "input_value_observation",
        "real_submit_allowed": False,
    }


def summarize_credit_ratio(records) -> dict:
    """Compare stamped bins. Too few trades stay unmeasured.

    The difference is an observational association. It is not a live pass
    and it does not change the collector signal.
    """
    bins = {"HIGH": [], "LOW": []}
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("acceptance_class") != "input_value_observation":
                continue
            if record.get("real_submit_allowed") is not False:
                continue
            name = record.get("credit_ratio_bin")
            value = record.get("baseline_ev_yen_per_share")
            if name in bins and shadow._finite(value):
                bins[name].append(float(value))
    counts = {name: len(values) for name, values in bins.items()}
    ready = all(count >= MIN_BIN_COUNT for count in counts.values())
    delta = None
    status = "INSUFFICIENT_SAMPLE"
    if ready:
        high = sum(bins["HIGH"]) / len(bins["HIGH"])
        low = sum(bins["LOW"]) / len(bins["LOW"])
        delta = high - low
        status = "OBSERVATIONAL_ASSOCIATION"
    return {
        "input_id": "credit_ratio",
        "bin_threshold": CREDIT_RATIO_BIN,
        "counts": counts,
        "delta_ev_yen_per_share": delta,
        "measurement_status": status,
        "live_roundtrip": "NOT_RUN/INPUT_VALUE_OBSERVATION",
        "real_submit_allowed": False,
    }


def roadmap() -> tuple:
    return ROADMAP
