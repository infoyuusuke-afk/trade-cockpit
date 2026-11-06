#!/usr/bin/env python3
"""Turn the local trade records into the pass gate's trade list. Research only. No order, no account file.

OWNER 2026-11-07 「門は本番に入れない。記録を門の形に変える部分をリポジトリに入れ、④⑤の前半件数が11/6の照合と揃うか確かめる」

The contract with the gate (scripts/v10_pass_gate.py):
- gross_pct is signed for the trade: positive when the trade made money, short or long. The gate never multiplies by side.
- cost_pct is the round-trip cost still to be taken, before the gate's slippage. A ledger whose value is already after
  its own cost passes that value as gross_pct with cost_pct 0, so nothing is taken twice.
- Only finished trades are CLOSED. A trade still open keeps status OPEN and the gate ignores it.

Paths come from the arguments; no record or ledger belongs in this repository.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
import glob
import json
from pathlib import Path

try:
    from scripts import v10_pass_gate as gate
    from scripts import v10_signal_ev_table as ev
except ImportError:  # run as a file
    import v10_pass_gate as gate
    import v10_signal_ev_table as ev


def from_replay(got: dict, day: str, rule: str) -> dict | None:
    """One filled replay of ev.replay. An unfilled signal is not a trade."""
    if not got or got.get("state") != "FILLED":
        return None
    return {"status": gate.CLOSED, "day": day, "rule": rule, "side": got["side"], "gross_pct": got["gross_pct"],
            "price": got["fill_price"], "cost_pct": ev.cost_pct(got["side"])}


def from_r09_row(row: dict) -> dict | None:
    """R09 ledger: net_pct is signed and already after R09's own cost. All R09 trades are short."""
    if row.get("status") != "TRADE" or not row.get("net_pct") or not row.get("E"):
        return None
    return {"status": gate.CLOSED, "day": row["date"], "rule": "R09", "side": -1, "gross_pct": float(row["net_pct"]), "price": float(row["E"]), "cost_pct": 0.0}


def from_h2_row(row: dict) -> dict | None:
    """H2 ledger: net_pct is signed and already after its own cost. OPEN stays open; a CANDIDATE was never bought."""
    if row.get("status") not in ("OPEN", "CLOSED") or not row.get("entry"):
        return None
    return {"status": row["status"], "day": row["entry_day"], "rule": row["rule"], "side": 1, "gross_pct": float(row.get("net_pct") or 0),
            "price": float(row["entry"]), "cost_pct": 0.0}


def load_ticks(path: Path, day: str, want: set) -> dict:
    """ticks.csv rows of the day, in time order. Rows captured before 09:00 or in another hour than their print are stale."""
    out = defaultdict(list)
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("ticker") not in want:
                continue
            at = r.get("captured_at") or ""
            printed = str(r.get("exchange_time") or "")[:8]
            if at[:10] != day or at[11:13] < "09" or printed < "09:00:00" or printed[:2] != at[11:13]:
                continue
            try:
                out[r["ticker"]].append((printed, at, float(r["price"])))
            except (TypeError, ValueError):
                continue
    for rows in out.values():
        rows.sort(key=lambda x: (x[0], x[1]))
    return out


def rule_trades(records: Path) -> list[dict]:
    """Replays every recorded rule signal the way v10_positions_live does (filled trades only)."""
    trades = []
    for d in sorted(p for p in Path(records).iterdir() if (p / "brain_rule_signals.csv").is_file() and (p / "ticks.csv").is_file()):
        signals = list(csv.DictReader(open(d / "brain_rule_signals.csv", encoding="utf-8-sig", errors="replace", newline="")))
        ticks = load_ticks(d / "ticks.csv", d.name, {s["ticker"] for s in signals})
        seen = set()
        for s in signals:
            rule = ev.RULES.get(s.get("rule") or "") or {}
            if not rule or (rule.get("once_per_ticker_day") and (s["rule"], s["ticker"]) in seen):
                continue
            sig = {"signal": s.get("signal"), "entry": s.get("entry"), "stop": s.get("stop"), "target1": s.get("target"),
                   "captured_at": s.get("captured_at"), "signal_bar": s.get("signal_bar")}
            trade = from_replay(ev.replay(sig, ticks.get(s["ticker"], []), max_hold_minutes=rule.get("max_hold_minutes")), d.name, s["rule"])
            if trade:
                seen.add((s["rule"], s["ticker"]))
                trades.append(trade)
    return trades


def read_csv(path) -> list[dict]:
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records")
    ap.add_argument("--r09-dir")
    ap.add_argument("--r09-from", default="2026-10-28")
    ap.add_argument("--h2-ledger")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    groups = defaultdict(list)
    calendar = []
    if a.records:
        rows = rule_trades(Path(a.records))
        calendar = sorted({t["day"] for t in rows})
        for t in rows:
            groups[t["rule"]].append(t)
    if a.r09_dir:
        for f in sorted(glob.glob(str(Path(a.r09_dir) / "ledger_*.csv"))):
            for r in read_csv(f):
                t = from_r09_row(r)
                if t and t["day"] >= a.r09_from:
                    groups["R09"].append(t)
    if a.h2_ledger:
        for r in read_csv(a.h2_ledger):
            t = from_h2_row(r)
            if t:
                groups[t["rule"]].append(t)
    result = {"days": calendar, "methods": {}}
    for k, v in sorted(groups.items()):
        result["methods"][k] = {"own_days": gate.evaluate(v), "shared_days": gate.evaluate(v, calendar=calendar) if calendar and k[0] == "R" and k != "R09" else None}
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok", len(groups))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
