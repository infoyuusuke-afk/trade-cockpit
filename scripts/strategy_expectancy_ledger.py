"""Closed-trade expectancy ledger.

``reliability_report.summarize`` aggregates paper-trade R and labels a sample
below 30 as still in trial. It does not separate broker fills from virtual
signals, deduct explicit fees, or reject duplicate, lookahead, or undeclared
survivorship rows. ``strategy_validation_lab.validate_run`` checks a
precomputed summary; it does not rebuild that summary from trades.

This module is the missing measurement unit. It never reads a broker, never
writes an order, and always returns ``real_submit_allowed=False`` and
``promotion_eligible=False``. ``expectancy_demonstrated`` means only that one
cohort satisfied this measurement contract. It is not a profit claim and it
does not authorize live trading.

A cohort is one evidence lane, one strategy id, one strategy version, and one
sample role (TRAIN, TEST, SHADOW, or REAL). REAL_FILL accepts only REAL.
VIRTUAL_SIGNAL accepts only TRAIN, TEST, or SHADOW. Mixed cohorts are split
and are not blended.
"""
from __future__ import annotations

import math
from datetime import datetime

MIN_N = 30
LANES = frozenset({"REAL_FILL", "VIRTUAL_SIGNAL"})
ROLES = {
    "REAL_FILL": frozenset({"REAL"}),
    "VIRTUAL_SIGNAL": frozenset({"TRAIN", "TEST", "SHADOW"}),
}
SIDES = frozenset({"LONG", "SHORT"})
CONTRACT = "strategy-expectancy-ledger-1"

# JP cash-session clocks named by the measurement request. Times outside
# these windows stay measurable as OUT_OF_NAMED_SESSION.
_BUCKETS = (
    ("OPEN_0900", 9 * 60, 9 * 60 + 15),
    ("AM_0915", 9 * 60 + 15, 9 * 60 + 30),
    ("AM_0930", 9 * 60 + 30, 10 * 60),
    ("AM_1000", 10 * 60, 10 * 60 + 30),
    ("AM_1030", 10 * 60 + 30, 11 * 60),
    ("AM_1100", 11 * 60, 11 * 60 + 30),
    ("OPEN_1230", 12 * 60 + 30, 13 * 60),
    ("PM_1300", 13 * 60, 14 * 60),
    ("PM_1400", 14 * 60, 14 * 60 + 30),
    ("PM_1430", 14 * 60 + 30, 15 * 60),
    ("CLOSE_1500", 15 * 60, 15 * 60 + 30),
)


def _base(**extra):
    out = {
        "contract": CONTRACT,
        "expectancy_demonstrated": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }
    out.update(extra)
    return out


def _blocked(reason, **extra):
    return _base(status="BLOCKED", reason=reason, metrics=None, **extra)


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _clock_minutes(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    clock = text
    if "T" in text:
        parsed = _parse_time(text)
        if parsed is None:
            return None
        return parsed.hour * 60 + parsed.minute
    if len(clock) < 5 or clock[2] != ":" or not clock[:2].isdigit() or not clock[3:5].isdigit():
        return None
    hour, minute = int(clock[:2]), int(clock[3:5])
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _bucket(minutes):
    if minutes is None:
        return None
    for name, start, end in _BUCKETS:
        if start <= minutes < end:
            return name
    return "OUT_OF_NAMED_SESSION"


def _metric(value, *, status="MEASURED", reason=None):
    return {"status": status, "value": value, "reason": reason}


def _not(reason):
    return _metric(None, status="NOT_MEASURABLE", reason=reason)


def _partition_stats(rows, *, drawdown_ok):
    n = len(rows)
    if n == 0:
        return {
            "trade_count": _metric(0),
            "win_rate": _not("EMPTY"),
            "avg_win": _not("NO_WINS"),
            "avg_loss": _not("NO_LOSSES"),
            "profit_factor": _not("EMPTY"),
            "gross_expectancy_per_trade": _not("EMPTY"),
            "expectancy_per_trade": _not("EMPTY"),
            "max_drawdown": _not("EMPTY"),
            "net_pnl": _metric(0.0),
        }
    nets = [r["net_pnl"] for r in rows]
    gross = [r["gross_pnl"] for r in rows]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    if not drawdown_ok:
        drawdown = _not("SEQUENCE_NOT_MONOTONIC")
    else:
        cum = peak = max_dd = 0.0
        for value in nets:
            cum += value
            peak = max(peak, cum)
            max_dd = max(max_dd, peak - cum)
        drawdown = _metric(max_dd)
    return {
        "trade_count": _metric(n),
        "win_rate": _metric(len(wins) / n),
        "avg_win": _metric(sum(wins) / len(wins)) if wins else _not("NO_WINS"),
        "avg_loss": _metric(sum(losses) / len(losses)) if losses else _not("NO_LOSSES"),
        "profit_factor": _metric(gross_win / gross_loss) if gross_loss else _not("NO_LOSING_TRADES"),
        "gross_expectancy_per_trade": _metric(sum(gross) / n),
        "expectancy_per_trade": _metric(sum(nets) / n),
        "max_drawdown": drawdown,
        "net_pnl": _metric(sum(nets)),
    }


def _group(rows, keyfn):
    groups = {}
    for row in rows:
        key = keyfn(row)
        if key is None:
            return None
        groups.setdefault(key, []).append(row)
    return {key: _partition_stats(items, drawdown_ok=True) for key, items in sorted(groups.items())}


def _split(records, field, invalid_reason, mixed_reason, result_key):
    values = {r.get(field) for r in records}
    if any(not isinstance(value, str) or not value for value in values):
        return _blocked(invalid_reason)
    if len(values) > 1:
        return _blocked(mixed_reason, **{result_key: {
            value: measure([r for r in records if r.get(field) == value])
            for value in sorted(values)
        }})
    return None


def measure(records):
    if not isinstance(records, list):
        return _blocked("RECORDS_NOT_A_LIST")
    if any(not isinstance(record, dict) for record in records):
        return _blocked("RECORD_NOT_AN_OBJECT")
    if not records:
        return _cohort([], lane=None, strategy_id=None, strategy_version=None, sample_role=None)

    lanes = {r.get("evidence_lane") for r in records}
    if not lanes <= LANES:
        return _blocked("EVIDENCE_LANE_INVALID")
    split = _split(records, "evidence_lane", "EVIDENCE_LANE_INVALID", "MIXED_EVIDENCE_LANES", "by_lane")
    if split:
        return split
    split = _split(records, "strategy_id", "STRATEGY_ID_INVALID", "MIXED_STRATEGY_IDS", "by_strategy")
    if split:
        return split
    split = _split(records, "strategy_version", "STRATEGY_VERSION_INVALID", "MIXED_STRATEGY_VERSIONS", "by_version")
    if split:
        return split
    split = _split(records, "sample_role", "SAMPLE_ROLE_INVALID", "MIXED_SAMPLE_ROLES", "by_sample_role")
    if split:
        return split
    return _cohort(
        records,
        lane=records[0]["evidence_lane"],
        strategy_id=records[0]["strategy_id"],
        strategy_version=records[0]["strategy_version"],
        sample_role=records[0]["sample_role"],
    )


def _cohort(records, *, lane, strategy_id, strategy_version, sample_role):
    if not records:
        metrics = _partition_stats([], drawdown_ok=False)
        return _base(
            status="EMPTY",
            evidence_lane=lane,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            sample_role=sample_role,
            integrity=["INSUFFICIENT_SAMPLE"],
            included_n=0,
            excluded_n=0,
            provisional=True,
            metrics=metrics,
            mfe_mean=_not("EMPTY"),
            mae_mean=_not("EMPTY"),
            by_side=_not("EMPTY"),
            by_symbol=_not("EMPTY"),
            by_time_bucket=_not("EMPTY"),
        )

    allowed_roles = ROLES[lane]
    if sample_role not in allowed_roles:
        return _blocked("LANE_ROLE_MISMATCH", evidence_lane=lane, sample_role=sample_role)

    window_starts = {r.get("window_start") for r in records}
    window_ends = {r.get("window_end") for r in records}
    window_start = _parse_time(next(iter(window_starts))) if len(window_starts) == 1 else None
    window_end = _parse_time(next(iter(window_ends))) if len(window_ends) == 1 else None
    window_ok = window_start is not None and window_end is not None and window_start < window_end

    duplicate_ids = set()
    seen = set()
    for record in records:
        trade_id = record.get("trade_id")
        if isinstance(trade_id, str) and trade_id:
            if trade_id in seen:
                duplicate_ids.add(trade_id)
            seen.add(trade_id)

    integrity = []
    accepted = []
    excluded = 0
    for record in records:
        reasons = []
        trade_id = record.get("trade_id")
        if not isinstance(trade_id, str) or not trade_id:
            reasons.append("MISSING_TRADE_ID")
        elif trade_id in duplicate_ids:
            reasons.append("DUPLICATE_FILL")
        gross = _num(record.get("pnl_yen"))
        fees = _num(record.get("fees"))
        slippage = _num(record.get("slippage"))
        if gross is None or fees is None or slippage is None or fees < 0 or slippage < 0:
            reasons.append("INCOMPLETE_COST_OR_PNL")
        signal = _parse_time(record.get("signal_known_at"))
        exit_at = _parse_time(record.get("exit_known_at"))
        if signal is None or exit_at is None:
            reasons.append("LOOKAHEAD_UNVERIFIED")
        elif exit_at < signal:
            reasons.append("LOOKAHEAD")
        if record.get("universe_fixed_before_outcome") is not True:
            reasons.append("SURVIVORSHIP_UNDECLARED")
        sequence = _parse_time(record.get("sequence_time"))
        if sequence is None:
            reasons.append("SEQUENCE_UNVERIFIED")
        elif window_ok and not (window_start <= sequence <= window_end):
            reasons.append("WINDOW_VIOLATION")
        if reasons:
            excluded += 1
            for reason in reasons:
                if reason not in integrity:
                    integrity.append(reason)
            continue
        accepted.append({
            "net_pnl": gross - fees - slippage,
            "gross_pnl": gross,
            "sequence": sequence,
            "side": record.get("side") if record.get("side") in SIDES else None,
            "symbol": record.get("symbol") if isinstance(record.get("symbol"), str) and record.get("symbol") else None,
            "bucket": _bucket(_clock_minutes(record.get("entry_time"))),
            "mfe": _num(record.get("mfe")),
            "mae": _num(record.get("mae")),
        })

    if not window_ok:
        integrity.append("EVALUATION_WINDOW_UNDECLARED")
    sequences = [row["sequence"] for row in accepted]
    drawdown_ok = all(sequences[i] < sequences[i + 1] for i in range(len(sequences) - 1))
    if not drawdown_ok:
        integrity.append("SEQUENCE_NOT_MONOTONIC")
    if len(accepted) < MIN_N:
        integrity.append("INSUFFICIENT_SAMPLE")

    def _mean(field, reason):
        values = [row[field] for row in accepted]
        if not values or any(value is None for value in values):
            return _not(reason)
        return _metric(sum(values) / len(values))

    mfe = _mean("mfe", "MFE_INCOMPLETE")
    mae = _mean("mae", "MAE_INCOMPLETE")
    by_side = _group(accepted, lambda row: row["side"])
    by_symbol = _group(accepted, lambda row: row["symbol"])
    by_time = _group(accepted, lambda row: row["bucket"])
    if accepted and mfe["status"] != "MEASURED":
        integrity.append("MFE_INCOMPLETE")
    if accepted and mae["status"] != "MEASURED":
        integrity.append("MAE_INCOMPLETE")
    if accepted and by_side is None:
        integrity.append("SIDE_INCOMPLETE")
    if accepted and by_symbol is None:
        integrity.append("SYMBOL_INCOMPLETE")
    if accepted and by_time is None:
        integrity.append("TIME_BUCKET_INCOMPLETE")
    metrics = _partition_stats(accepted, drawdown_ok=drawdown_ok)
    if accepted and metrics["profit_factor"]["status"] != "MEASURED":
        integrity.append("NO_LOSING_TRADES")

    return _base(
        status="MEASURED",
        evidence_lane=lane,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        sample_role=sample_role,
        expectancy_demonstrated=not integrity and len(accepted) >= MIN_N and excluded == 0,
        integrity=integrity,
        included_n=len(accepted),
        excluded_n=excluded,
        provisional=bool(integrity or excluded),
        metrics=metrics,
        mfe_mean=mfe,
        mae_mean=mae,
        by_side=by_side if by_side is not None else _not("SIDE_INCOMPLETE"),
        by_symbol=by_symbol if by_symbol is not None else _not("SYMBOL_INCOMPLETE"),
        by_time_bucket=by_time if by_time is not None else _not("TIME_BUCKET_INCOMPLETE"),
    )
