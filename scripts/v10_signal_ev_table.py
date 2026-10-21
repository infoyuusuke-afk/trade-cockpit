"""Expected value of the cockpit's own signals, from its recorded MS2 data.

Backtest only (OWNER 2026-10-21: old data is for backtesting, never for an
entry). For every buy/short signal the Collector logged in
records/<day>/trade_signals.csv, the same day's recorded MS2 ticks of that
ticker are replayed from the signal time:

- fill: the first tick at or through the signal's entry price within
  FILL_WINDOW (buy: price >= entry, short: price <= entry); otherwise NOT_FILLED
  and left out of the expected value;
- exit: target1 or stop, whichever is touched first by a later tick; otherwise
  the last tick at or before 15:20 JST;
- return: side * (exit / entry - 1) - 2 * COST_PER_SIDE.

Ticks are recorded on change, not every trade, so a touch between two ticks
can be missed; results are an estimate from this sampling. Statistics are
grouped by strategy+side and by strategy+side+ticker; a group with fewer than
MIN_N filled trades is marked INSUFFICIENT and must not be ranked.
No order path; nothing here is a trade instruction.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

SCHEMA = "100b-v10-signal-ev-table-v1"
JST = timezone(timedelta(hours=9))
FILL_WINDOW = timedelta(minutes=30)       # PROVISIONAL
EXIT_TIME = "15:20:00"
COST_PER_SIDE = 0.001                     # PROVISIONAL: 0.1 % per side
MIN_N = 20
SIDES = {"買いサイン": 1, "空売りサイン": -1}


def _f(raw):
    try:
        v = float(str(raw).replace(",", ""))
    except ValueError:
        return None
    return v if math.isfinite(v) and v > 0 else None


def load_ticks(path: Path) -> dict:
    out = {}
    if not path.is_file():
        return out
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            price = _f(r.get("price"))
            t = (r.get("exchange_time") or "").strip()
            if price is None or len(t) != 8:
                continue
            out.setdefault(r.get("ticker", ""), []).append((t, price))
    for rows in out.values():
        rows.sort()
    return out


def replay(signal: dict, ticks: list) -> dict | None:
    side = SIDES.get(signal.get("signal"))
    entry, stop, target = _f(signal.get("entry")), _f(signal.get("stop")), _f(signal.get("target1"))
    try:
        at = datetime.strptime(signal["captured_at"], "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError):
        return None
    if side is None or None in (entry, stop, target):
        return None
    if (side > 0 and not stop < entry < target) or (side < 0 and not target < entry < stop):
        return None
    start, fill_until = at.strftime("%H:%M:%S"), (at + FILL_WINDOW).strftime("%H:%M:%S")
    filled_at = None
    for t, p in ticks:
        if t < start:
            continue
        if filled_at is None:
            if t > fill_until or t > EXIT_TIME:
                return {"state": "NOT_FILLED"}
            if (side > 0 and p >= entry) or (side < 0 and p <= entry):
                filled_at = t
            continue
        if t > EXIT_TIME:
            break
        if (side > 0 and p >= target) or (side < 0 and p <= target):
            return _result(side, entry, target, "TARGET")
        if (side > 0 and p <= stop) or (side < 0 and p >= stop):
            return _result(side, entry, stop, "STOP")
        last = p
    if filled_at is None:
        return {"state": "NOT_FILLED"}
    closes = [p for t, p in ticks if filled_at <= t <= EXIT_TIME]
    return _result(side, entry, closes[-1] if closes else entry, "TIME_EXIT")


def _result(side, entry, exit_price, how):
    gross = side * (exit_price / entry - 1)
    return {"state": "FILLED", "exit": how, "gross_pct": gross * 100, "return_pct": (gross - 2 * COST_PER_SIDE) * 100}


def stats(trades: list[dict]) -> dict:
    """Net of the provisional cost (ev_pct, win_rate_pct, pf) and gross (before cost)."""
    returns = [t["return_pct"] for t in trades]
    n = len(returns)
    if not n:
        return {"n": 0, "status": "INSUFFICIENT"}
    gross = [t["gross_pct"] for t in trades]
    exits = {}
    for t in trades:
        exits[t["exit"]] = exits.get(t["exit"], 0) + 1
    wins = [r for r in returns if r > 0]
    loss = -sum(r for r in returns if r < 0)
    return {
        "n": n, "win_rate_pct": round(len(wins) / n * 100, 1),
        "ev_pct": round(sum(returns) / n, 3),
        "pf": round(sum(wins) / loss, 2) if loss > 0 else None,
        "gross_ev_pct": round(sum(gross) / n, 3),
        "gross_win_rate_pct": round(sum(1 for g in gross if g > 0) / n * 100, 1),
        "exits": exits,
        "status": "OK" if n >= MIN_N else "INSUFFICIENT",
    }


def build(records: Path, *, now: datetime, days: list[str] | None = None) -> dict:
    by_strategy, by_ticker, counts, used_days = {}, {}, {"signals": 0, "filled": 0, "not_filled": 0, "invalid": 0}, []
    today = now.astimezone(JST).date().isoformat()
    for day_dir in sorted(p for p in records.iterdir() if p.is_dir()):
        day = day_dir.name
        if (days and day not in days) or day >= today:   # only completed past days
            continue
        sig_path = day_dir / "trade_signals.csv"
        if not sig_path.is_file():
            continue
        ticks = load_ticks(day_dir / "ticks.csv")
        if not ticks:
            continue
        used_days.append(day)
        with open(sig_path, newline="", encoding="utf-8-sig") as f:
            for s in csv.DictReader(f):
                counts["signals"] += 1
                got = replay(s, ticks.get(s.get("ticker", ""), []))
                if got is None:
                    counts["invalid"] += 1
                    continue
                if got["state"] != "FILLED":
                    counts["not_filled"] += 1
                    continue
                counts["filled"] += 1
                key = s["strategy"] + "|" + s["signal"]
                by_strategy.setdefault(key, []).append(got)
                by_ticker.setdefault(key + "|" + s["ticker"], []).append(got)
    return {
        "schema_version": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "basis": "BACKTEST_OF_RECORDED_COCKPIT_SIGNALS_ON_RECORDED_MS2_TICKS",
        "days": used_days,
        "assumptions": {"fill_window_minutes": FILL_WINDOW.total_seconds() / 60, "exit_time_jst": EXIT_TIME,
                        "cost_pct_per_side": COST_PER_SIDE * 100, "min_n": MIN_N,
                        "status": "PROVISIONAL (fill window and cost are not OWNER decisions)"},
        "counts": counts,
        "by_strategy": {k: stats(v) for k, v in sorted(by_strategy.items())},
        "by_strategy_ticker": {k: stats(v) for k, v in sorted(by_ticker.items())},
        "real_submit_allowed": False,
        "trade_instruction": False,
    }


def write_table(records: Path, target: Path, *, now: datetime) -> dict:
    table = build(records, now=now)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(table, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    return table


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest expected value of recorded cockpit signals")
    ap.add_argument("--records", required=True, type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    table = write_table(args.records, args.output, now=now) if args.output else build(args.records, now=now)
    print(json.dumps({"days": len(table["days"]), "counts": table["counts"], "by_strategy": table["by_strategy"]},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
