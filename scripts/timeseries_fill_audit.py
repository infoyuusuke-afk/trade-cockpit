"""Point-in-time virtual fill audit.

Issue #342. This module decides whether a virtual trade may move
SIGNAL → ENTRY_ELIGIBLE → ENTRY_OBSERVED → EXIT_OBSERVED → CLOSED.
It does not submit orders, does not write paper_trade_history.json, and
does not treat a price touch as a broker fill.

Estimated fills and real executions stay on separate lanes. Quote-level
estimates reuse scripts/shadow_fill_model.py (shadow-fill-model-0.1)
without changing its hash or fill rules. A model fill is marked
estimated_fill=true and real_fill=false. Independent execution evidence
stays in scripts/fill_execution_collector_contract.py; broker exports are
refused here.

OHLC bars, including 15-second bars, do not order the high and the low.
scripts/backtest_15s.py still chooses a stop when both levels print inside
one bar. That research rule is not reused and its past outputs are not
rewritten.

Public producers audited in producer_catalog() cannot supply a recorded
CLOSED virtual trade. Missing evidence stays BLOCKED or UNKNOWN.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from scripts.shadow_fill_model import (
    FILL_MODEL_VERSION,
    evaluate_limit_fill,
    evaluate_market_fill,
)

EVALUATOR_VERSION = "timeseries-fill-audit-0.1"
LANE_VIRTUAL = "VIRTUAL_ESTIMATE"
STATES = (
    "SIGNAL",
    "ENTRY_ELIGIBLE",
    "ENTRY_OBSERVED",
    "EXIT_OBSERVED",
    "CLOSED",
    "BLOCKED",
    "UNKNOWN",
)
SAMPLE_ROLES = ("TRAIN", "TEST", "SHADOW")
HORIZONS = ("DAYTRADE", "OVERNIGHT", "SWING")
FAMILIES = ("OR5", "OR15", "VWAP", "OTHER")
SESSIONS = ("OPENING_09", "HOUR_10", "AFTERNOON", "AFTER_14")
ENTRY_STYLES = ("LIMIT", "BREAKOUT")
SIDES = ("LONG", "SHORT")
EVIDENCE_ORIGINS = ("SYNTHETIC", "RECORDED")
REAL_SOURCES = frozenset({
    "BROKER_EXECUTION_EXPORT",
    "MANUAL_VERIFIED_EXECUTION",
    "REAL_FILL",
})


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value) -> bool:
    return _finite(value) and value > 0


def _non_negative(value) -> bool:
    return _finite(value) and value >= 0


def _qty(value) -> bool:
    return _positive(value) and int(value) == value


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _entry_order_side(side: str) -> str:
    return "BUY" if side == "LONG" else "SELL"


def _exit_order_side(side: str) -> str:
    return "SELL" if side == "LONG" else "BUY"


def _sign(side: str) -> int:
    return 1 if side == "LONG" else -1


def producer_catalog() -> list[dict]:
    """Static feasibility of the producers that exist in this repository.

    File presence is reported separately by scan_public_evidence(). None of
    these producers is an admissible recorded virtual fill.
    """
    return [
        {
            "producer_id": "morning_review.audit_one",
            "source": "paper_trade_history.json plus the session daily high/low",
            "symbol_scope": "morning snapshot candidates",
            "event_time": "display signal_time 'YYYY-MM-DD HH:MM:SS JST'; no per-fill event_time",
            "available_at": "absent",
            "received_at": "absent",
            "timezone": "JST label on a display string, not an aware instant per price",
            "granularity": "daily high/low/close",
            "orders_intrabar_extremes": False,
            "supports_virtual_fill_states": False,
            "recorded_closed_eligible": False,
            "block_reason": "DAILY_RANGE_CANNOT_PROVE_SEQUENCE",
        },
        {
            "producer_id": "data/5m_calendars",
            "source": "yfinance via scripts/multi_ticker_5m_calendar.py",
            "symbol_scope": "watch symbols with a calendar file",
            "event_time": "clock 'HH:MM' inside a date bucket",
            "available_at": "file-level updated_at only",
            "received_at": "absent on each bar",
            "timezone": "updated_at carries a JST label; bar clocks do not",
            "granularity": "5-minute OHLC stored as percent returns, not prices",
            "orders_intrabar_extremes": False,
            "supports_virtual_fill_states": False,
            "recorded_closed_eligible": False,
            "block_reason": "YFINANCE_5M_NOT_A_PRICE_PATH",
        },
        {
            "producer_id": "ms2_live/Resample_Kioxia_Ticks_15s.ps1",
            "source": "local RssTickList log resampled offline",
            "symbol_scope": "285A local watcher log",
            "event_time": "bucket_start clock HH:MM:SS",
            "available_at": "absent on the 15-second CSV",
            "received_at": "recorded_at exists on the raw tick log, not on the bar",
            "timezone": "not stored on bucket_start",
            "granularity": "15-second OHLCV; empty buckets are omitted",
            "orders_intrabar_extremes": False,
            "supports_virtual_fill_states": False,
            "recorded_closed_eligible": False,
            "block_reason": "BAR_15S_INTRABAR_ORDER_UNKNOWN",
            "notes": (
                "The resampler comment states that order inside a bucket follows "
                "poll order only. suspected_gap stays on the separate diag CSV and "
                "is not joined onto the bar. No kioxia_15s CSV is part of the public tree."
            ),
        },
        {
            "producer_id": "ms2_live tick log",
            "source": "Kioxia_RSS_Live_Watcher.ps1 Write-TickLogDiff",
            "symbol_scope": "285A local file kioxia_ticks_YYYYMMDD.csv",
            "event_time": "tick_time to the second",
            "available_at": "absent; recorded_at is a separate clock",
            "received_at": "recorded_at column when the local file exists",
            "timezone": "not an aware offset in the documented CSV schema",
            "granularity": "trade print; identical second/price/size rows are not distinguishable",
            "orders_intrabar_extremes": False,
            "supports_virtual_fill_states": False,
            "recorded_closed_eligible": False,
            "block_reason": "TICK_LOG_NOT_POINT_IN_TIME_CONTRACT",
            "notes": "Local tick CSV is not in the public repository. It is not a broker execution.",
        },
        {
            "producer_id": "shadow_fill_model.evaluate_limit_fill",
            "source": "caller-supplied MarketObservation",
            "symbol_scope": "whatever the caller passes",
            "event_time": "observed_at, timezone-aware",
            "available_at": "not a field of the fill model; this audit requires it beside the quote",
            "received_at": "optional on this audit's observation",
            "timezone": "aware datetimes only",
            "granularity": "top-of-book quote plus last trade",
            "orders_intrabar_extremes": True,
            "supports_virtual_fill_states": True,
            "recorded_closed_eligible": False,
            "block_reason": None,
            "fill_model_version": FILL_MODEL_VERSION,
            "notes": (
                "MARKET fills are PROBABLE. LIMIT trade-through fills are CERTAIN at the "
                "limit price. slippage_model_status stays NOT_MODELED_V0_1. "
                "fill_execution_collector_contract forbids SHADOW_FILL_MODEL as "
                "independent execution evidence. This module keeps that ban: "
                "real_fill stays false."
            ),
        },
        {
            "producer_id": "fill_execution_collector_contract",
            "source": "BROKER_EXECUTION_EXPORT or MANUAL_VERIFIED_EXECUTION",
            "symbol_scope": "private collector record",
            "event_time": "observed_at",
            "available_at": "collector contract does not define available_at",
            "received_at": "absent",
            "timezone": "aware observed_at",
            "granularity": "claimed execution quantity and price",
            "orders_intrabar_extremes": False,
            "supports_virtual_fill_states": False,
            "recorded_closed_eligible": False,
            "block_reason": "REAL_LANE_NOT_VIRTUAL_AUDIT",
            "notes": "Real executions are not converted into virtual CLOSED trades here.",
        },
        {
            "producer_id": "scripts/backtest_15s.py",
            "source": "research CSV bars",
            "symbol_scope": "caller CSV",
            "event_time": "bar time string",
            "available_at": "absent",
            "received_at": "absent",
            "timezone": "unspecified",
            "granularity": "15-second OHLCV",
            "orders_intrabar_extremes": False,
            "supports_virtual_fill_states": False,
            "recorded_closed_eligible": False,
            "block_reason": "RESEARCH_BACKTEST_ASSUMES_STOP_ON_AMBIGUOUS_BAR",
            "notes": "Left unchanged so existing research measurements are not overwritten.",
        },
    ]


def scan_public_evidence(root: Path | None = None) -> dict:
    """Read-only inventory. Does not print prices, accounts, or order ids."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    history_path = root / "paper_trade_history.json"
    paper_n = None
    paper_sha256 = None
    if history_path.is_file():
        raw = history_path.read_bytes()
        paper_sha256 = hashlib.sha256(raw).hexdigest()
        try:
            loaded = json.loads(raw.decode("utf-8"))
            paper_n = len(loaded) if isinstance(loaded, list) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            paper_n = None
    live = root / "ms2_live"
    tick_files = sorted(p.name for p in live.glob("kioxia_ticks_*.csv")) if live.is_dir() else []
    bar_files = sorted(p.name for p in live.glob("kioxia_15s_*.csv")) if live.is_dir() else []
    five = root / "data" / "5m_calendars"
    five_reason = "YFINANCE_5M_ABSENT"
    five_files = 0
    if five.is_dir():
        files = sorted(five.glob("*.json"))
        five_files = len(files)
        five_reason = _five_minute_reason(files[0]) if files else "YFINANCE_5M_ABSENT"
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "observed_eligible_n": 0,
        "synthetic_n": 0,
        "paper_history_n": paper_n,
        "paper_history_sha256": paper_sha256,
        "paper_history_admissible_n": 0,
        "tick_log_files": tick_files,
        "bar_15s_files": bar_files,
        "five_minute_files": five_files,
        "five_minute_block_reason": five_reason,
        "recorded_producer_supports_closed_virtual_fill": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "producers": producer_catalog(),
    }


def _five_minute_reason(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "YFINANCE_5M_UNREADABLE"
    days = data.get("days") if isinstance(data, dict) else None
    if not days:
        return "YFINANCE_5M_EMPTY"
    bars = days[0].get("bars") if isinstance(days[0], dict) else None
    if not bars:
        return "YFINANCE_5M_EMPTY"
    bar = bars[0]
    if not isinstance(bar, dict):
        return "YFINANCE_5M_NOT_A_PRICE_PATH"
    if "available_at" not in bar or not _positive(bar.get("c")):
        return "YFINANCE_5M_NOT_A_PRICE_PATH"
    return "YFINANCE_5M_UNCLASSIFIED"


def _base_result(signal: dict, *, evidence_origin, state: str, reasons: list[str]) -> dict:
    signal = signal if isinstance(signal, dict) else {}
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "fill_model_version": FILL_MODEL_VERSION,
        "state": state,
        "reasons": sorted(set(reasons)),
        "lane": LANE_VIRTUAL,
        "real_fill": False,
        "estimated_fill": False,
        "independent_execution_evidence": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "evidence_origin": evidence_origin if evidence_origin in EVIDENCE_ORIGINS else None,
        "sample_role": signal.get("sample_role") if signal.get("sample_role") in SAMPLE_ROLES else None,
        "strategy_id": signal.get("strategy_id") if _text(signal.get("strategy_id")) else None,
        "strategy_version": signal.get("strategy_version") if _text(signal.get("strategy_version")) else None,
        "horizon": signal.get("horizon") if signal.get("horizon") in HORIZONS else None,
        "family": signal.get("family") if signal.get("family") in FAMILIES else None,
        "symbol": signal.get("symbol") if _text(signal.get("symbol")) else None,
        "side": signal.get("side") if signal.get("side") in SIDES else None,
        "session": signal.get("session") if signal.get("session") in SESSIONS else None,
        "regime": signal.get("regime") if _text(signal.get("regime")) else None,
        "symbol_class": signal.get("symbol_class") if _text(signal.get("symbol_class")) else None,
        "entry_style": signal.get("entry_style") if signal.get("entry_style") in ENTRY_STYLES else None,
        "signal_known_at": _iso(signal.get("signal_known_at")) if _aware(signal.get("signal_known_at")) else None,
        "quantity": int(signal["quantity"]) if _qty(signal.get("quantity")) else None,
        "entry_price_plan": signal.get("entry") if _positive(signal.get("entry")) else None,
        "stop_plan": signal.get("stop") if _positive(signal.get("stop")) else None,
        "target_plan": signal.get("target") if _positive(signal.get("target")) else None,
        "observed_entry_price": None,
        "observed_entry_at": None,
        "entry_fill_confidence": None,
        "entry_fill_reason": None,
        "observed_exit_price": None,
        "observed_exit_at": None,
        "exit_reason": None,
        "exit_fill_confidence": None,
        "exit_fill_reason": None,
        "mfe_per_share": None,
        "mae_per_share": None,
        "mfe_mae_uses_pre_entry_extreme": False,
        "intrabar_extreme_order": None,
        "cost_status": "NOT_APPLICABLE",
        "fees_yen": None,
        "slippage_yen": None,
        "cost_model_version": None,
        "cost_assumptions": None,
        "cost_evidence_ref": None,
        "fill_model_slippage_yen": None,
        "fill_model_slippage_status": None,
        "verified_net_pnl_yen": None,
        "model_net_pnl_yen": None,
        "lookahead_excluded_event_ids": [],
        "cohort_axes": {
            "strategy_id": signal.get("strategy_id") if _text(signal.get("strategy_id")) else None,
            "strategy_version": signal.get("strategy_version") if _text(signal.get("strategy_version")) else None,
            "horizon": signal.get("horizon") if signal.get("horizon") in HORIZONS else None,
            "family": signal.get("family") if signal.get("family") in FAMILIES else None,
            "symbol_class": signal.get("symbol_class") if _text(signal.get("symbol_class")) else None,
            "regime": signal.get("regime") if _text(signal.get("regime")) else None,
            "session": signal.get("session") if signal.get("session") in SESSIONS else None,
            "side": signal.get("side") if signal.get("side") in SIDES else None,
            "sample_role": signal.get("sample_role") if signal.get("sample_role") in SAMPLE_ROLES else None,
            "evidence_origin": evidence_origin if evidence_origin in EVIDENCE_ORIGINS else None,
            "fill_model_version": FILL_MODEL_VERSION,
            "lane": LANE_VIRTUAL,
        },
    }


def _validate_signal(signal, *, as_of, evidence_origin) -> list[str]:
    reasons = []
    if not isinstance(signal, dict):
        return ["SIGNAL_INVALID"]
    if signal.get("real_submit_allowed") is True:
        reasons.append("REAL_SUBMIT_REQUEST_REJECTED")
    if signal.get("lane") in ("REAL", "REAL_FILL") or signal.get("sample_role") == "REAL":
        reasons.append("REAL_LANE_NOT_VIRTUAL_AUDIT")
    if evidence_origin not in EVIDENCE_ORIGINS:
        reasons.append("EVIDENCE_ORIGIN_INVALID")
    if not _text(signal.get("strategy_id")):
        reasons.append("STRATEGY_ID_MISSING")
    if not _text(signal.get("strategy_version")):
        reasons.append("STRATEGY_VERSION_MISSING")
    if not _text(signal.get("symbol")):
        reasons.append("SYMBOL_MISSING")
    if signal.get("side") not in SIDES:
        reasons.append("SIDE_INVALID")
    if signal.get("entry_style") not in ENTRY_STYLES:
        reasons.append("ENTRY_STYLE_UNKNOWN")
    if not _aware(signal.get("signal_known_at")):
        reasons.append("SIGNAL_KNOWN_AT_INVALID")
    if not _aware(as_of):
        reasons.append("AS_OF_INVALID")
    elif _aware(signal.get("signal_known_at")) and as_of < signal.get("signal_known_at"):
        reasons.append("AS_OF_BEFORE_SIGNAL")
    if not _positive(signal.get("entry")) or not _positive(signal.get("stop")) or not _positive(signal.get("target")):
        reasons.append("PLAN_PRICE_INVALID")
    elif signal.get("side") == "LONG" and not (signal["stop"] < signal["entry"] < signal["target"]):
        reasons.append("PRICE_LADDER_INVALID")
    elif signal.get("side") == "SHORT" and not (signal["target"] < signal["entry"] < signal["stop"]):
        reasons.append("PRICE_LADDER_INVALID")
    if not _aware(signal.get("valid_until")):
        reasons.append("VALID_UNTIL_INVALID")
    elif _aware(signal.get("signal_known_at")) and signal["valid_until"] <= signal["signal_known_at"]:
        reasons.append("VALID_UNTIL_NOT_AFTER_SIGNAL")
    if signal.get("session") not in SESSIONS:
        reasons.append("SESSION_UNKNOWN")
    if not _text(signal.get("regime")):
        reasons.append("REGIME_UNKNOWN")
    if signal.get("horizon") not in HORIZONS:
        reasons.append("HORIZON_INVALID")
    if signal.get("family") not in FAMILIES:
        reasons.append("FAMILY_INVALID")
    if signal.get("sample_role") not in SAMPLE_ROLES:
        reasons.append("SAMPLE_ROLE_INVALID")
    if not _text(signal.get("provenance")):
        reasons.append("PROVENANCE_MISSING")
    if not _qty(signal.get("quantity")):
        reasons.append("QUANTITY_UNKNOWN")
    if "symbol_class" in signal and signal.get("symbol_class") is not None and not _text(signal.get("symbol_class")):
        reasons.append("SYMBOL_CLASS_INVALID")
    return reasons


def _observation_problems(obs, signal) -> list[str]:
    reasons = []
    if not isinstance(obs, dict):
        return ["OBSERVATION_INVALID"]
    if not _text(obs.get("event_id")):
        reasons.append("EVENT_ID_MISSING")
    if not _text(obs.get("source")):
        reasons.append("SOURCE_MISSING")
    elif obs.get("source") in REAL_SOURCES:
        reasons.append("REAL_SOURCE_NOT_ACCEPTED_IN_VIRTUAL_AUDIT")
    if obs.get("symbol") != signal.get("symbol"):
        reasons.append("SYMBOL_MISMATCH")
    kind = obs.get("kind")
    if kind not in ("QUOTE", "ORDERED_PRINT", "OHLCV_BAR", "DAILY_RANGE", "MISSING"):
        reasons.append("OBSERVATION_KIND_INVALID")
    if not _aware(obs.get("event_time")) or not _aware(obs.get("available_at")):
        reasons.append("TIMESTAMP_NOT_TIMEZONE_AWARE")
    else:
        if obs["available_at"] < obs["event_time"]:
            reasons.append("TIMESTAMP_INCONSISTENT")
        end = obs.get("event_time_end")
        if end is not None and (not _aware(end) or end < obs["event_time"]):
            reasons.append("TIMESTAMP_INCONSISTENT")
    received = obs.get("received_at")
    if received is not None and not _aware(received):
        reasons.append("TIMESTAMP_NOT_TIMEZONE_AWARE")
    elif _aware(received) and _aware(obs.get("event_time")) and received < obs["event_time"]:
        reasons.append("TIMESTAMP_INCONSISTENT")
    session = obs.get("session")
    if session is not None and session != signal.get("session"):
        reasons.append("MIXED_SESSION")
    freshness = obs.get("data_freshness")
    if freshness == "STALE" or obs.get("stale") is True:
        reasons.append("STALE")
    elif freshness == "MISSING" or obs.get("quality") == "MISSING" or kind == "MISSING":
        reasons.append("DATA_MISSING")
    elif freshness == "FUTURE":
        reasons.append("OBSERVATION_FRESHNESS_FUTURE")
    elif freshness != "OK":
        reasons.append("FRESHNESS_UNKNOWN")
    if obs.get("suspected_gap") is True or obs.get("quality") == "GAP":
        reasons.append("SUSPECTED_GAP")
    elif "suspected_gap" in obs and not isinstance(obs.get("suspected_gap"), bool):
        reasons.append("SUSPECTED_GAP_FLAG_INVALID")
    if kind == "OHLCV_BAR":
        prices = [obs.get("open"), obs.get("high"), obs.get("low"), obs.get("close")]
        if not all(_positive(p) for p in prices):
            reasons.append("ABNORMAL_PRICE")
        elif obs["high"] < obs["low"] or not (obs["low"] <= obs["open"] <= obs["high"]) or not (obs["low"] <= obs["close"] <= obs["high"]):
            reasons.append("ABNORMAL_PRICE")
        if "volume" not in obs:
            reasons.append("VOLUME_MISSING")
        elif not _non_negative(obs.get("volume")):
            reasons.append("ABNORMAL_VOLUME")
    elif kind == "ORDERED_PRINT":
        if not _positive(obs.get("price")):
            reasons.append("ABNORMAL_PRICE")
        if "volume" not in obs:
            reasons.append("VOLUME_MISSING")
        elif not _non_negative(obs.get("volume")):
            reasons.append("ABNORMAL_VOLUME")
    elif kind == "QUOTE":
        for key in ("bid", "ask", "last_trade_price"):
            value = obs.get(key)
            if value is not None and not _positive(value):
                reasons.append("ABNORMAL_PRICE")
        if _positive(obs.get("bid")) and _positive(obs.get("ask")) and obs["bid"] > obs["ask"]:
            reasons.append("ABNORMAL_PRICE")
        for key in ("bid_qty", "ask_qty", "last_trade_qty"):
            value = obs.get(key)
            if value is not None and not _non_negative(value):
                reasons.append("ABNORMAL_VOLUME")
    elif kind == "DAILY_RANGE":
        for key in ("high", "low", "close"):
            value = obs.get(key)
            if value is not None and not _positive(value):
                reasons.append("ABNORMAL_PRICE")
    return reasons


def _entry_reached(signal, price) -> bool:
    if not _positive(price):
        return False
    if signal["entry_style"] == "LIMIT":
        return price <= signal["entry"] if signal["side"] == "LONG" else price >= signal["entry"]
    return price >= signal["entry"] if signal["side"] == "LONG" else price <= signal["entry"]


def _stop_reached(signal, price) -> bool:
    if not _positive(price):
        return False
    return price <= signal["stop"] if signal["side"] == "LONG" else price >= signal["stop"]


def _bar_contains_level(bar, level) -> bool:
    return _finite(bar.get("low")) and _finite(bar.get("high")) and bar["low"] <= level <= bar["high"]


def _bar_contains_both_exits(signal, bar) -> bool:
    return _bar_contains_level(bar, signal["stop"]) and _bar_contains_level(bar, signal["target"])


def _quote_view(obs: dict) -> dict:
    return {
        "observed_at": obs["event_time"],
        "bid": obs.get("bid"),
        "ask": obs.get("ask"),
        "bid_qty": obs.get("bid_qty"),
        "ask_qty": obs.get("ask_qty"),
        "last_trade_price": obs.get("last_trade_price"),
        "last_trade_qty": obs.get("last_trade_qty"),
        "tick_size": obs.get("tick_size"),
        "data_freshness": obs.get("data_freshness"),
    }


def _print_price(obs) -> float | None:
    if obs.get("kind") == "ORDERED_PRINT":
        return obs.get("price")
    if obs.get("kind") == "QUOTE":
        return obs.get("last_trade_price")
    return None


def _assess_cost(cost) -> dict:
    empty = {
        "status": "UNVERIFIED",
        "fees_yen": None,
        "slippage_yen": None,
        "model_version": None,
        "assumptions": None,
        "evidence_ref": None,
        "reason": "COST_UNVERIFIED",
    }
    if cost is None:
        return empty
    if not isinstance(cost, dict):
        return {**empty, "reason": "COST_INVALID"}
    status = cost.get("status")
    fees = cost.get("fees_yen")
    slip = cost.get("slippage_yen")
    numbers_ok = _non_negative(fees) and _non_negative(slip)
    evidence = cost.get("evidence_ref")
    if status == "VERIFIED" and numbers_ok and _text(evidence):
        return {
            "status": "VERIFIED",
            "fees_yen": float(fees),
            "slippage_yen": float(slip),
            "model_version": None,
            "assumptions": None,
            "evidence_ref": evidence.strip(),
            "reason": None,
        }
    if (
        status == "MODEL"
        and numbers_ok
        and _text(cost.get("model_version"))
        and _text(cost.get("assumptions"))
        and _text(evidence)
    ):
        return {
            "status": "MODEL",
            "fees_yen": float(fees),
            "slippage_yen": float(slip),
            "model_version": cost["model_version"].strip(),
            "assumptions": cost["assumptions"].strip(),
            "evidence_ref": evidence.strip(),
            "reason": "COST_MODEL_NOT_VERIFIED_NET",
        }
    if status in ("VERIFIED", "MODEL") or (fees is not None and not _non_negative(fees)) or (slip is not None and not _non_negative(slip)):
        return {**empty, "reason": "COST_INVALID"}
    return empty


def _net_pnl(side, entry, exit_price, quantity, fees, slip) -> float:
    return _sign(side) * (exit_price - entry) * quantity - fees - slip


def _excursions(signal, entry_price, entry_at, usable) -> tuple[float | None, float | None]:
    favorable = []
    adverse = []
    for obs in usable:
        if obs.get("kind") in ("QUOTE", "ORDERED_PRINT"):
            if obs["event_time"] <= entry_at:
                continue
            price = _print_price(obs)
            if not _positive(price):
                continue
        elif obs.get("kind") == "OHLCV_BAR":
            end = obs.get("event_time_end")
            if not _aware(end) or obs["event_time"] <= entry_at or end <= entry_at:
                continue
            if signal["side"] == "LONG":
                favorable.append(obs["high"] - entry_price)
                adverse.append(entry_price - obs["low"])
            else:
                favorable.append(entry_price - obs["low"])
                adverse.append(obs["high"] - entry_price)
            continue
        else:
            continue
        if signal["side"] == "LONG":
            favorable.append(price - entry_price)
            adverse.append(entry_price - price)
        else:
            favorable.append(entry_price - price)
            adverse.append(price - entry_price)
    if not favorable and not adverse:
        return None, None
    return max(0.0, max(favorable)), max(0.0, max(adverse))


def _apply_exit(signal, post, entry_at, as_of, quantity) -> dict | None:
    stop_triggered_at = None
    for obs in post:
        if obs["kind"] not in ("QUOTE", "ORDERED_PRINT"):
            continue
        price = _print_price(obs)
        if obs["kind"] == "QUOTE":
            view = _quote_view(obs)
            if stop_triggered_at is None and _positive(price) and _stop_reached(signal, price):
                stop_triggered_at = obs["event_time"]
                continue
            if stop_triggered_at is None:
                filled = evaluate_limit_fill(
                    side=_exit_order_side(signal["side"]),
                    requested_qty=quantity,
                    limit_price=signal["target"],
                    observation=view,
                    now=as_of,
                    submitted_at=entry_at,
                )
                if filled["filled_qty"] == quantity and filled["avg_fill_price"] is not None:
                    return {
                        "price": filled["avg_fill_price"],
                        "at": obs["event_time"],
                        "reason": "TARGET",
                        "confidence": filled["fill_confidence"],
                        "fill_reason": filled["fill_reason"],
                        "slippage_yen": filled["slippage_yen"],
                        "slippage_status": filled["slippage_model_status"],
                    }
                continue
            if obs["event_time"] <= stop_triggered_at:
                continue
            filled = evaluate_market_fill(
                side=_exit_order_side(signal["side"]),
                requested_qty=quantity,
                observation=view,
                now=as_of,
                submitted_at=stop_triggered_at,
            )
            if filled["filled_qty"] == quantity and filled["avg_fill_price"] is not None:
                return {
                    "price": filled["avg_fill_price"],
                    "at": obs["event_time"],
                    "reason": "STOP",
                    "confidence": filled["fill_confidence"],
                    "fill_reason": filled["fill_reason"],
                    "slippage_yen": filled["slippage_yen"],
                    "slippage_status": filled["slippage_model_status"],
                }
        elif stop_triggered_at is None and _positive(price) and _stop_reached(signal, price):
            stop_triggered_at = obs["event_time"]
    return None


def _ambiguous_exit_bar(signal, entry_at, usable) -> str | None:
    """A bar never supplies the order of its high and low.

    Prints inside that bar do not cancel the unknown path between those
    extremes, so a bar that contains both the stop and the target cannot
    choose either exit.
    """
    for bar in usable:
        if bar.get("kind") != "OHLCV_BAR":
            continue
        end = bar.get("event_time_end")
        if not _aware(end):
            return "BAR_END_UNKNOWN"
        if end <= entry_at:
            continue
        overlaps_entry = bar["event_time"] <= entry_at < end
        if overlaps_entry and (
            _bar_contains_level(bar, signal["stop"]) or _bar_contains_level(bar, signal["target"])
        ):
            return "BAR_OVERLAPS_ENTRY_AND_EXIT"
        if bar["event_time"] > entry_at and _bar_contains_both_exits(signal, bar):
            return "INTRABAR_EXIT_ORDER_UNKNOWN"
    return None


def _find_entry(signal, usable, as_of):
    eligible = None
    for obs in usable:
        if obs["event_time"] <= signal["signal_known_at"] or obs["event_time"] > signal["valid_until"]:
            continue
        price = _print_price(obs)
        if obs["kind"] == "OHLCV_BAR":
            continue
        if obs["kind"] == "ORDERED_PRINT":
            if _entry_reached(signal, price):
                eligible = {
                    "at": obs["event_time"],
                    "reason": "FILL_MODEL_INPUT_INCOMPLETE",
                }
            continue
        if obs["kind"] != "QUOTE":
            continue
        view = _quote_view(obs)
        if signal["entry_style"] == "LIMIT":
            filled = evaluate_limit_fill(
                side=_entry_order_side(signal["side"]),
                requested_qty=int(signal["quantity"]),
                limit_price=signal["entry"],
                observation=view,
                now=as_of,
                submitted_at=signal["signal_known_at"],
            )
        else:
            if not _entry_reached(signal, price):
                continue
            filled = evaluate_market_fill(
                side=_entry_order_side(signal["side"]),
                requested_qty=int(signal["quantity"]),
                observation=view,
                now=as_of,
                submitted_at=signal["signal_known_at"],
            )
        if filled["filled_qty"] == int(signal["quantity"]) and filled["avg_fill_price"] is not None:
            return {
                "observed": True,
                "price": filled["avg_fill_price"],
                "at": obs["event_time"],
                "confidence": filled["fill_confidence"],
                "fill_reason": filled["fill_reason"],
                "slippage_yen": filled["slippage_yen"],
                "slippage_status": filled["slippage_model_status"],
            }, eligible
        if _entry_reached(signal, price) or filled["fill_reason"] in ("TOUCH_ONLY", "VISIBLE_QTY_ZERO", "PARTIAL_FILL_VISIBLE_QTY_ONLY"):
            eligible = {"at": obs["event_time"], "reason": filled["fill_reason"]}
    return None, eligible


def evaluate_virtual_fill(signal, observations, *, as_of, evidence_origin, cost=None, expected_bar_seconds=None) -> dict:
    """Return one deterministic virtual-fill decision. Inputs are not modified."""
    signal = signal if isinstance(signal, dict) else {}
    observations = list(observations or [])
    reasons = _validate_signal(signal, as_of=as_of, evidence_origin=evidence_origin)
    result = _base_result(signal, evidence_origin=evidence_origin, state="BLOCKED", reasons=reasons)
    if reasons:
        return result

    integrity = []
    usable = []
    excluded = []
    seen_ids = set()
    basis_ids = signal.get("basis_event_ids") or []
    if not isinstance(basis_ids, (list, tuple)) or not all(_text(item) for item in basis_ids):
        result["reasons"] = ["SIGNAL_BASIS_INVALID"]
        result["state"] = "BLOCKED"
        return result

    for obs in observations:
        problems = _observation_problems(obs, signal)
        hard = [code for code in problems if code != "TIMESTAMP_NOT_TIMEZONE_AWARE"]
        # Freshness and schema failures inside the decision window block the path.
        # Events that are only not-yet-available are excluded below after the clock parses.
        if any(code in problems for code in (
            "OBSERVATION_INVALID", "EVENT_ID_MISSING", "SOURCE_MISSING",
            "REAL_SOURCE_NOT_ACCEPTED_IN_VIRTUAL_AUDIT", "SYMBOL_MISMATCH",
            "OBSERVATION_KIND_INVALID", "TIMESTAMP_NOT_TIMEZONE_AWARE",
            "TIMESTAMP_INCONSISTENT", "MIXED_SESSION", "STALE", "DATA_MISSING",
            "OBSERVATION_FRESHNESS_FUTURE", "FRESHNESS_UNKNOWN", "SUSPECTED_GAP",
            "SUSPECTED_GAP_FLAG_INVALID", "ABNORMAL_PRICE", "ABNORMAL_VOLUME",
            "VOLUME_MISSING",
        )):
            integrity.extend(problems)
            continue
        if hard:
            integrity.extend(hard)
            continue
        event_id = obs["event_id"]
        if event_id in seen_ids:
            integrity.append("DUPLICATE_EVENT")
            continue
        seen_ids.add(event_id)
        end = obs.get("event_time_end")
        if obs["available_at"] > as_of or obs["event_time"] > as_of or (_aware(end) and end > as_of):
            excluded.append(event_id)
            continue
        usable.append(obs)

    result["lookahead_excluded_event_ids"] = sorted(excluded)
    if integrity:
        result["reasons"] = sorted(set(integrity))
        result["state"] = "BLOCKED"
        return result

    if any(obs.get("kind") == "DAILY_RANGE" for obs in usable):
        result["reasons"] = ["DAILY_RANGE_CANNOT_PROVE_SEQUENCE"]
        result["state"] = "BLOCKED"
        result["intrabar_extreme_order"] = "UNKNOWN"
        return result

    known_basis = {
        obs["event_id"]: obs for obs in usable
        if obs["available_at"] <= signal["signal_known_at"]
    }
    missing_basis = [item for item in basis_ids if item not in known_basis]
    if missing_basis:
        result["reasons"] = ["SIGNAL_BASIS_NOT_KNOWN_AT_SIGNAL"]
        result["state"] = "BLOCKED"
        return result

    usable.sort(key=lambda obs: (obs["event_time"], obs["event_id"]))
    times = [obs["event_time"] for obs in usable]
    if len(times) != len(set(times)):
        result["reasons"] = ["TIMESTAMP_TIE_ORDER_UNKNOWN"]
        result["state"] = "BLOCKED"
        return result

    if any(obs.get("kind") == "OHLCV_BAR" for obs in usable):
        result["intrabar_extreme_order"] = "UNKNOWN"

    if expected_bar_seconds is not None:
        if not _positive(expected_bar_seconds):
            result["reasons"] = ["EXPECTED_BAR_SECONDS_INVALID"]
            result["state"] = "BLOCKED"
            return result
        bars = [obs for obs in usable if obs.get("kind") == "OHLCV_BAR"]
        for prev, nxt in zip(bars, bars[1:]):
            if nxt.get("session_break") is True:
                continue
            gap = (nxt["event_time"] - prev["event_time"]).total_seconds()
            if gap > float(expected_bar_seconds):
                result["reasons"] = ["DATA_GAP"]
                result["state"] = "BLOCKED"
                return result

    if not usable and not observations:
        result["state"] = "UNKNOWN"
        result["reasons"] = ["NO_OBSERVATIONS"]
        return result

    saw_bar = any(obs.get("kind") == "OHLCV_BAR" for obs in usable)
    if not any(obs.get("kind") in ("QUOTE", "ORDERED_PRINT") for obs in usable):
        result["state"] = "UNKNOWN"
        result["reasons"] = ["INTRABAR_EXTREME_ORDER_UNKNOWN"] if saw_bar else ["NO_ORDERED_PRICE_EVIDENCE"]
        return result

    entry, eligible = _find_entry(signal, usable, as_of)
    if entry is None:
        if eligible is not None:
            result["state"] = "ENTRY_ELIGIBLE"
            result["reasons"] = [eligible["reason"]]
            return result
        result["state"] = "SIGNAL"
        result["reasons"] = ["ENTRY_NOT_REACHED"]
        return result

    result["estimated_fill"] = True
    result["observed_entry_price"] = entry["price"]
    result["observed_entry_at"] = _iso(entry["at"])
    result["entry_fill_confidence"] = entry["confidence"]
    result["entry_fill_reason"] = entry["fill_reason"]
    result["fill_model_slippage_yen"] = entry["slippage_yen"]
    result["fill_model_slippage_status"] = entry["slippage_status"]

    ambiguity = _ambiguous_exit_bar(signal, entry["at"], usable)
    mfe, mae = _excursions(signal, entry["price"], entry["at"], usable)
    result["mfe_per_share"] = mfe
    result["mae_per_share"] = mae
    if ambiguity:
        result["state"] = "UNKNOWN"
        result["reasons"] = [ambiguity]
        return result

    post = [obs for obs in usable if obs["event_time"] > entry["at"]]
    exit_fill = _apply_exit(signal, post, entry["at"], as_of, int(signal["quantity"]))
    if exit_fill is None:
        result["state"] = "ENTRY_OBSERVED"
        result["reasons"] = ["EXIT_NOT_OBSERVED"]
        return result

    result["observed_exit_price"] = exit_fill["price"]
    result["observed_exit_at"] = _iso(exit_fill["at"])
    result["exit_reason"] = exit_fill["reason"]
    result["exit_fill_confidence"] = exit_fill["confidence"]
    result["exit_fill_reason"] = exit_fill["fill_reason"]
    result["fill_model_slippage_yen"] = exit_fill["slippage_yen"]
    result["fill_model_slippage_status"] = exit_fill["slippage_status"]
    assessed = _assess_cost(cost)
    result["cost_status"] = assessed["status"]
    result["cost_model_version"] = assessed["model_version"]
    result["cost_assumptions"] = assessed["assumptions"]
    result["cost_evidence_ref"] = assessed["evidence_ref"]
    if assessed["status"] == "VERIFIED":
        result["fees_yen"] = assessed["fees_yen"]
        result["slippage_yen"] = assessed["slippage_yen"]
        result["verified_net_pnl_yen"] = _net_pnl(
            signal["side"], entry["price"], exit_fill["price"], int(signal["quantity"]),
            assessed["fees_yen"], assessed["slippage_yen"],
        )
        result["state"] = "CLOSED"
        result["reasons"] = ["VIRTUAL_ESTIMATE_CLOSED"]
        return result
    if assessed["status"] == "MODEL":
        result["fees_yen"] = assessed["fees_yen"]
        result["slippage_yen"] = assessed["slippage_yen"]
        result["model_net_pnl_yen"] = _net_pnl(
            signal["side"], entry["price"], exit_fill["price"], int(signal["quantity"]),
            assessed["fees_yen"], assessed["slippage_yen"],
        )
    result["state"] = "EXIT_OBSERVED"
    result["reasons"] = [assessed["reason"]]
    return result


def summarize_cohort(results: list[dict]) -> dict:
    """Metrics stay inside one evidence cohort. Mixed axes publish no EV/PF/DD."""
    rows = list(results or [])
    def axis(name):
        return {row.get("cohort_axes", {}).get(name) for row in rows}

    mixed = any(len(axis(name)) > 1 for name in (
        "strategy_id", "strategy_version", "horizon", "family", "sample_role",
        "evidence_origin", "fill_model_version", "lane", "side", "session", "regime",
    ))
    recorded_closed = [
        row for row in rows
        if row.get("evidence_origin") == "RECORDED"
        and row.get("state") == "CLOSED"
        and row.get("cost_status") == "VERIFIED"
        and row.get("real_fill") is False
        and row.get("lane") == LANE_VIRTUAL
    ]
    synthetic_rows = [row for row in rows if row.get("evidence_origin") == "SYNTHETIC"]
    report = {
        "evaluator_version": EVALUATOR_VERSION,
        "mixed_cohort": mixed,
        "observed_eligible_n": len(recorded_closed),
        "synthetic_n": len(synthetic_rows),
        "recorded_n": sum(row.get("evidence_origin") == "RECORDED" for row in rows),
        "expectancy_yen": None,
        "profit_factor": None,
        "max_drawdown_yen": None,
        "verified_net_pnl_yen": None,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "reasons": ["MIXED_COHORT"] if mixed else [],
    }
    if mixed or not rows:
        if not rows:
            report["reasons"] = ["COHORT_EMPTY"]
        return report
    closed = [
        row for row in rows
        if row.get("state") == "CLOSED" and row.get("cost_status") == "VERIFIED"
        and row.get("verified_net_pnl_yen") is not None
    ]
    if len(closed) != len(rows):
        report["reasons"] = ["COHORT_NOT_UNIFORM_VERIFIED_CLOSED"]
        return report
    ordered = sorted(closed, key=lambda row: (row.get("observed_exit_at") or "", row.get("symbol") or ""))
    times = [row.get("observed_exit_at") for row in ordered]
    pnls = [float(row["verified_net_pnl_yen"]) for row in ordered]
    report["verified_net_pnl_yen"] = sum(pnls)
    report["expectancy_yen"] = sum(pnls) / len(pnls)
    gains = sum(value for value in pnls if value > 0)
    losses = sum(-value for value in pnls if value < 0)
    report["profit_factor"] = None if losses == 0 else gains / losses
    if any(not times[i] or times[i] <= times[i - 1] for i in range(1, len(times))):
        report["reasons"] = ["DRAWDOWN_TIME_NOT_STRICT"]
    else:
        equity = 0.0
        peak = 0.0
        drawdown = 0.0
        for value in pnls:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        report["max_drawdown_yen"] = drawdown
    return report
