"""Night PTS (JNX) -> next-morning watch candidates, from the Collector's own records.

The Collector writes every watched issue's JNX PTS snapshot during the PTS
session into records/<day>/kioxia_jnx_pts.csv (the file name is historical;
it holds all watched issues). This module takes the latest snapshot per
issue from the most recent recorded PTS evening (not later than now) and
keeps issues that moved and traded:

- |PTS gap vs TSE close| >= MIN_GAP_PCT,
- PTS turnover >= MIN_TURNOVER_YEN,
- PTS spread <= MAX_SPREAD_PCT.

The morning screen puts them next to the MS2 pre-open quotes. They are watch
candidates only: not a trade signal, no orders. Whether a PTS move carries to
the next session has not been verified yet; the number of recorded PTS
evenings is reported with every list so the evidence can be judged.
Thresholds are PROVISIONAL.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys

SCHEMA = "100b-v10-pts-pickup-v1"
JST = timezone(timedelta(hours=9))
PTS_FILE = "kioxia_jnx_pts.csv"
MIN_GAP_PCT = 1.0               # PROVISIONAL
MIN_TURNOVER_YEN = 10_000_000   # PROVISIONAL
MAX_SPREAD_PCT = 1.0            # PROVISIONAL
MAX_ROWS = 20


def _num(raw):
    try:
        v = float(str(raw).replace(",", ""))
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def evenings(records: Path, *, now: datetime) -> list[str]:
    """Days whose PTS file has at least one snapshot, up to now (JST)."""
    today = now.astimezone(JST).date().isoformat()
    out = []
    for d in sorted(p for p in records.iterdir() if p.is_dir() and p.name <= today):
        f = d / PTS_FILE
        if f.is_file() and f.stat().st_size > 0:
            with open(f, newline="", encoding="utf-8-sig") as fh:
                if next(csv.DictReader(fh), None) is not None:
                    out.append(d.name)
    return out


def latest_per_issue(path: Path, *, not_after: datetime) -> dict:
    cutoff = not_after.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S")
    last = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("captured_at", "")) > cutoff:
                continue
            last[r.get("ticker", "")] = r
    return last


def build(records: Path, *, now: datetime) -> dict:
    days = evenings(records, now=now)
    rows = []
    session = days[-1] if days else None
    if session:
        for ticker, r in latest_per_issue(records / session / PTS_FILE, not_after=now).items():
            gap, turnover, spread = _num(r.get("gap_pct")), _num(r.get("turnover")), _num(r.get("spread_pct"))
            if None in (gap, turnover, spread):
                continue
            if abs(gap) < MIN_GAP_PCT or turnover < MIN_TURNOVER_YEN or spread > MAX_SPREAD_PCT:
                continue
            rows.append({
                "pts_ticker": ticker, "ticker": ticker.replace(".JNX", ".T"), "name": r.get("name", ""),
                "pts_price": _num(r.get("price")), "tse_close": _num(r.get("tse_close")),
                "pts_gap_pct": round(gap, 2), "turnover_yen": round(turnover), "spread_pct": round(spread, 3),
                "bias_score": _num(r.get("bias_score")), "stance": r.get("stance", ""),
                "direction": "UP" if gap > 0 else "DOWN", "captured_at": r.get("captured_at", ""),
            })
    rows.sort(key=lambda x: (-abs(x["pts_gap_pct"]), -x["turnover_yen"]))
    return {
        "schema_version": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "pts_session_date": session,
        "recorded_pts_evenings": len(days),
        "criteria": {"min_abs_gap_pct": MIN_GAP_PCT, "min_turnover_yen": MIN_TURNOVER_YEN,
                     "max_spread_pct": MAX_SPREAD_PCT, "status": "PROVISIONAL"},
        "verification": "UNVERIFIED: next-session outcome of PTS moves not yet measured",
        "rows": rows[:MAX_ROWS],
        "real_submit_allowed": False,
        "trade_instruction": False,
    }


# OWNER 2026-10-28 「買い　空売り　期待値　色付け」: each row gets the side and the expected value of a day trade
# (open -> close, cost included) for a gap of that size, from the local research table RuntimeDir/pts_gap_ev_v1.json
# (built on the PC from 3 years of daily bars). The stock's own numbers are used when it has 20 or more such days.
# Display only: no signal, no order. Without the table the rows carry no side.
EV_FILE = "pts_gap_ev_v1.json"
EV_SCHEMA = "100b-v10-pts-gap-ev-v1"
MIN_PF, MIN_N = 1.5, 30
EV_BUCKETS = (("+3%以上", 3, 99), ("+2〜3%", 2, 3), ("+1〜2%", 1, 2), ("−1〜−2%", -2, -1), ("−2〜−3%", -3, -2), ("−3%以下", -99, -3))


def load_ev(path: Path):
    try:
        ev = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(ev, dict) or ev.get("schema_version") != EV_SCHEMA or ev.get("real_submit_allowed") is not False:
        return None
    return ev


def attach_ev(rows: list, ev) -> None:
    for r in rows:
        g = r["pts_gap_pct"]
        b = next((name for name, lo, hi in EV_BUCKETS if lo <= g < hi), None)
        if ev is None or b is None:
            continue
        code = r["ticker"].replace(".T", "")
        own = (ev.get("per_stock") or {}).get(code, {}).get(b)
        # OWNER 2026-10-28 「PF1.5以上・回数30以上の時だけ買い・空売りの札にして、銘柄ごとの成績も回数を確かめて」
        if own and min((own.get(k) or {}).get("n") or 0 for k in ("buy", "short")) < MIN_N:
            own = None
        allb = (ev.get("overall") or {}).get(b) or {}
        side = allb.get("side", "SKIP")
        src = own if own else allb
        pick = src.get("buy") if side == "BUY" else src.get("short") if side == "SHORT" else None
        if pick is not None and (pick["ev_pct"] <= 0 or (pick.get("n") or 0) < MIN_N
                                 or (pick.get("pf") is not None and pick["pf"] < MIN_PF)):
            side, pick = "SKIP", None
        buy, short = src.get("buy") or {}, src.get("short") or {}
        r["ev_side"] = side
        r["ev_bucket"] = b
        r["ev_pct"] = pick["ev_pct"] if pick else None
        r["ev_pf"] = pick["pf"] if pick else None
        r["ev_n"] = (pick or buy or short).get("n")
        r["ev_buy_pct"] = buy.get("ev_pct")
        r["ev_short_pct"] = short.get("ev_pct")
        r["ev_basis"] = "この銘柄" if own else "全体"


def write_pickup(records: Path, target: Path, *, now: datetime) -> dict:
    view = build(records, now=now)
    attach_ev(view["rows"], load_ev(Path(records).parent / EV_FILE))
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    return view


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Night PTS -> next-morning watch candidates")
    ap.add_argument("--records", required=True, type=Path)
    args = ap.parse_args(argv)
    view = build(args.records, now=datetime.now(timezone.utc))
    print(json.dumps({k: view[k] for k in ("pts_session_date", "recorded_pts_evenings")} | {"rows": len(view["rows"])},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
