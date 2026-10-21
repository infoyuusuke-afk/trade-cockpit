"""100B: reconcile the private paid-attempt ledger with OpenAI Usage (read-only).

The ledger counts local reservations ($1 per run, $8 lifetime). It is not a
provider-side spending stop. This report compares it with an OpenAI Usage
export the OWNER downloads by hand (CSV with a date column and a cost column in
USD). No network, no API key, no write.

    python scripts/agent_paid_ledger_report.py --ledger <ledger> [--usage-csv <export.csv>]

Flags:
  USAGE_WITHOUT_RESERVATION  provider cost on a JST day with no ledger reservation
                             (spend outside this pipeline, or a ledger that was replaced)
  USAGE_OVER_RESERVATION     a day's provider cost is above that day's reservations
  TOTAL_OVER_PREPAID_CREDIT  total provider cost above the $10 prepaid credit
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import json
from pathlib import Path
import sqlite3
import sys

PREPAID_CREDIT_CENTS = 1000  # OWNER: $10 prepaid, auto-reload off (2026-10-20/21)
DATE_COLUMNS = ("date", "day", "start_date", "start_time", "bucket_start")
COST_COLUMNS = ("cost_usd", "amount_usd", "cost", "amount", "amount_value")


def ledger_days(path: Path) -> dict:
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(paid_attempts)")}
        if not cols:
            return {}
        day = "jst_day" if "jst_day" in cols else "substr(reserved_at,1,10)"
        rows = conn.execute("SELECT %s, COUNT(*), SUM(reserved_cents) FROM paid_attempts GROUP BY 1" % day).fetchall()
    return {str(d): {"runs": n, "reserved_cents": int(c or 0)} for d, n, c in rows}


def usage_days(path: Path) -> dict:
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = {k.lower().strip(): k for k in reader.fieldnames or []}
        dcol = next((fields[c] for c in DATE_COLUMNS if c in fields), None)
        ccol = next((fields[c] for c in COST_COLUMNS if c in fields), None)
        if not dcol or not ccol:
            raise ValueError("USAGE_CSV_COLUMNS_NOT_FOUND")
        for row in reader:
            day = str(row[dcol]).strip()[:10]
            cents = round(float(str(row[ccol]).replace("$", "").strip() or 0) * 100)
            out[day] = out.get(day, 0) + cents
    return out


def reconcile(ledger: dict, usage: dict | None) -> dict:
    report = {"ledger": ledger, "reserved_cents_total": sum(v["reserved_cents"] for v in ledger.values()),
              "flags": [], "real_submit_allowed": False}
    if usage is None:
        report["usage"] = "NOT_PROVIDED"
        return report
    report["usage_cents_by_day"] = usage
    report["usage_cents_total"] = sum(usage.values())
    for day, cents in sorted(usage.items()):
        reserved = ledger.get(day, {}).get("reserved_cents", 0)
        if cents > 0 and reserved == 0:
            report["flags"].append("USAGE_WITHOUT_RESERVATION:" + day)
        elif cents > reserved:
            report["flags"].append("USAGE_OVER_RESERVATION:" + day)
    if report["usage_cents_total"] > PREPAID_CREDIT_CENTS:
        report["flags"].append("TOTAL_OVER_PREPAID_CREDIT")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only paid ledger vs OpenAI Usage reconciliation")
    ap.add_argument("--ledger", required=True, type=Path)
    ap.add_argument("--usage-csv", type=Path)
    args = ap.parse_args(argv)
    try:
        out = reconcile(ledger_days(args.ledger), usage_days(args.usage_csv) if args.usage_csv else None)
        print(json.dumps(out, sort_keys=True))
        return 0 if not out["flags"] else 1
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(json.dumps({"state": "BLOCKED", "reason": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
