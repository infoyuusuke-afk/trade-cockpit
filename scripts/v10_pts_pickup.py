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


def write_pickup(records: Path, target: Path, *, now: datetime) -> dict:
    view = build(records, now=now)
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
