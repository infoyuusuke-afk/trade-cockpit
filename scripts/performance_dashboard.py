"""Build strategy-performance data for the CONTROL tab.

This module is intentionally pure/read-only with respect to trading state. It consumes
paper/shadow/backtest history and produces a normalized analytics artifact. It does
not place orders and it never guesses missing tab or execution-mode identity.

Design principles:
- Missing data is UNKNOWN, not zero.
- OPEN_MARK / NOT_TRIGGERED / ambiguous rows are not realized outcomes.
- Real / Shadow / Backtest are kept in separate lanes.
- Legacy rows without deterministic identity remain visible as unclassified.
- Profit factor has an explicit status when there are no losses rather than an
  arbitrary sentinel such as 99.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

SCHEMA_VERSION = "performance-by-strategy-1.0"

TAB_LABELS = {
    "scalp": "SCALP 5",
    "event-hot": "EVENT 5",
    "ms2-live": "REALTIME 5",
    "overnight": "OVERNIGHT 5",
    "swing": "SWING 5",
    "value": "VALUE 5",
    "kioxia-calendar": "KIOXIA",
}

# Keep this deliberately small. New records should carry cockpit_tab directly.
KNOWN_STRATEGY_TO_TAB = {
    "day_ifo_long": "ms2-live",
    "day_rank_long": "ms2-live",
    "day_short_mvp": "ms2-live",
}

REALIZED_EXIT_REASONS = {
    "STOP",
    "TARGET1",
    "TARGET2",
    "EOD",
    "CLOSE",
    "MANUAL_CLOSE",
    "TIME_EXIT",
}

NON_REALIZED_EXIT_REASONS = {
    "OPEN_MARK",
    "NOT_TRIGGERED",
    "AMBIGUOUS_EXCLUDED",
    "UNKNOWN",
    "",
}

RESULT_TO_EXIT_REASON = {
    "未発動（見送り）": "NOT_TRIGGERED",
    "順序不明（成績除外）": "AMBIGUOUS_EXCLUDED",
    "IFO損切り": "STOP",
    "IFO利確1": "TARGET1",
    "IFO利確2": "TARGET2",
    "時点評価・未決済": "OPEN_MARK",
    "大引け決済": "EOD",
}

VALID_MODES = {"real", "shadow", "backtest", "unknown"}


def _num(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if result != result:  # NaN
            return None
        return result
    except (TypeError, ValueError):
        return None


def classify_tab(record: dict) -> Optional[str]:
    explicit = str(record.get("cockpit_tab") or record.get("tab") or "").strip()
    if explicit in TAB_LABELS:
        return explicit

    strategy_id = str(record.get("strategy_id") or "").strip().lower()
    return KNOWN_STRATEGY_TO_TAB.get(strategy_id)


def classify_mode(record: dict) -> str:
    raw = str(
        record.get("execution_mode")
        or record.get("trade_mode")
        or record.get("mode")
        or ""
    ).strip().lower()

    aliases = {
        "paper": "shadow",
        "paper_trade": "shadow",
        "paper-trade": "shadow",
        "sim": "shadow",
        "simulation": "shadow",
        "live": "real",
        "broker": "real",
        "historical": "backtest",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in VALID_MODES else "unknown"


def exit_reason(record: dict) -> str:
    explicit = str(record.get("exit_reason") or "").strip()
    if explicit:
        return explicit
    return RESULT_TO_EXIT_REASON.get(str(record.get("result") or "").strip(), "UNKNOWN")


def is_realized(record: dict) -> bool:
    reason = exit_reason(record)
    if reason in NON_REALIZED_EXIT_REASONS:
        return False
    if reason in REALIZED_EXIT_REASONS:
        return _num(record.get("pnl_yen")) is not None

    # Unknown/custom exit labels are not silently counted as realized.
    return False


def _date_key(record: dict) -> str:
    return str(record.get("date") or record.get("evaluation_date") or "")


def _sort_key(record: dict):
    return (
        _date_key(record),
        str(record.get("signal_time") or ""),
        str(record.get("ticker") or record.get("code") or ""),
    )


def _max_drawdown(values: Iterable[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return max_dd


def _streak(realized_rows: list[dict]) -> tuple[int, str]:
    if not realized_rows:
        return 0, "NONE"

    def outcome(row: dict) -> str:
        pnl = _num(row.get("pnl_yen"))
        if pnl is None:
            return "NONE"
        if pnl > 0:
            return "WIN"
        if pnl < 0:
            return "LOSS"
        return "FLAT"

    ordered = sorted(realized_rows, key=_sort_key)
    last = outcome(ordered[-1])
    if last == "NONE":
        return 0, "NONE"

    count = 0
    for row in reversed(ordered):
        if outcome(row) != last:
            break
        count += 1
    return count, last


def _daily_series(realized_rows: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in sorted(realized_rows, key=_sort_key):
        date = _date_key(row)
        if not date:
            continue
        pnl = _num(row.get("pnl_yen"))
        if pnl is None:
            continue
        bucket = grouped.setdefault(date, {"date": date, "pnl_yen": 0.0, "trades": 0})
        bucket["pnl_yen"] += pnl
        bucket["trades"] += 1

    cumulative = 0.0
    out = []
    for date in sorted(grouped):
        item = dict(grouped[date])
        cumulative += item["pnl_yen"]
        item["cum_pnl_yen"] = cumulative
        out.append(item)
    return out


def _recent_trade(record: dict) -> dict:
    return {
        "date": _date_key(record) or None,
        "ticker": record.get("ticker") or record.get("code"),
        "name": record.get("name"),
        "side": record.get("side"),
        "result": record.get("result"),
        "exit_reason": exit_reason(record),
        "pnl_yen": _num(record.get("pnl_yen")),
        "r": _num(record.get("r") if record.get("r") is not None else record.get("R")),
        "mfe": _num(record.get("MFE")),
        "mae": _num(record.get("MAE")),
    }


def compute_lane(tab: str, mode: str, rows: list[dict]) -> dict:
    realized = [row for row in rows if is_realized(row)]
    realized = sorted(realized, key=_sort_key)

    pnl_values = [_num(row.get("pnl_yen")) for row in realized]
    pnl_values = [value for value in pnl_values if value is not None]

    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    flats = [value for value in pnl_values if value == 0]

    gain_sum = sum(wins)
    loss_abs = abs(sum(losses))

    if loss_abs > 0:
        pf = gain_sum / loss_abs
        pf_status = "FINITE"
    elif gain_sum > 0:
        pf = None
        pf_status = "NO_LOSSES"
    elif pnl_values:
        pf = None
        pf_status = "NO_GAIN_NO_LOSS"
    else:
        pf = None
        pf_status = "NO_REALIZED_TRADES"

    r_values = []
    mfe_values = []
    mae_values = []
    for row in realized:
        r_value = _num(row.get("r") if row.get("r") is not None else row.get("R"))
        if r_value is not None:
            r_values.append(r_value)
        mfe = _num(row.get("MFE"))
        mae = _num(row.get("MAE"))
        if mfe is not None:
            mfe_values.append(mfe)
        if mae is not None:
            mae_values.append(mae)

    daily = _daily_series(realized)
    streak_count, streak_type = _streak(realized)

    return {
        "tab": tab,
        "label": TAB_LABELS.get(tab, tab),
        "mode": mode,
        "source_status": "connected" if rows else "unknown",
        "raw_record_count": len(rows),
        "sample_count": len(realized),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_rate": (len(wins) / len(realized) * 100.0) if realized else None,
        "pnl_yen": sum(pnl_values) if realized else None,
        "pf": pf,
        "pf_status": pf_status,
        "avg_r": (sum(r_values) / len(r_values)) if r_values else None,
        "max_drawdown_yen": _max_drawdown(pnl_values) if realized else None,
        "mfe_avg": (sum(mfe_values) / len(mfe_values)) if mfe_values else None,
        "mae_avg": (sum(mae_values) / len(mae_values)) if mae_values else None,
        "current_streak": streak_count,
        "current_streak_type": streak_type,
        "unresolved_count": sum(1 for row in rows if exit_reason(row) == "OPEN_MARK"),
        "not_triggered_count": sum(1 for row in rows if exit_reason(row) == "NOT_TRIGGERED"),
        "daily_series": daily,
        "cumulative_series": [
            {
                "date": item["date"],
                "pnl_yen": item["pnl_yen"],
                "cum_pnl_yen": item["cum_pnl_yen"],
            }
            for item in daily
        ],
        "recent_trades": [_recent_trade(row) for row in realized[-20:]],
    }


def build_dashboard(rows: list[dict], *, updated_at: Optional[str] = None) -> dict:
    lanes: dict[tuple[str, str], list[dict]] = defaultdict(list)
    unclassified = []
    unknown_mode_count = 0

    for row in rows:
        tab = classify_tab(row)
        if tab is None:
            unclassified.append(row)
            continue
        mode = classify_mode(row)
        if mode == "unknown":
            unknown_mode_count += 1
        lanes[(tab, mode)].append(row)

    strategies = [
        compute_lane(tab, mode, lane_rows)
        for (tab, mode), lane_rows in sorted(lanes.items())
    ]

    represented_tabs = {item["tab"] for item in strategies}
    missing_tabs = [
        {"tab": tab, "label": label, "source_status": "unknown"}
        for tab, label in TAB_LABELS.items()
        if tab not in represented_tabs
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": updated_at,
        "record_count": len(rows),
        "classified_record_count": len(rows) - len(unclassified),
        "unclassified_record_count": len(unclassified),
        "unknown_mode_record_count": unknown_mode_count,
        "strategies": strategies,
        "missing_strategy_tabs": missing_tabs,
    }


def write_dashboard(input_path: Path, output_path: Path, *, updated_at: Optional[str] = None) -> dict:
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("history root must be a JSON array")

    if updated_at is None:
        updated_at = datetime.now().astimezone().isoformat()

    dashboard = build_dashboard(rows, updated_at=updated_at)
    output_path.write_text(
        json.dumps(dashboard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dashboard


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("paper_trade_history.json"))
    parser.add_argument("--output", type=Path, default=Path("performance_by_strategy.json"))
    args = parser.parse_args()
    write_dashboard(args.input, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
