"""Offline, read-only structure/quality audit for MS2 daily records CSVs.

Does not attest feed origin, exchange sequencing, completeness, point-in-time
availability, fills or trading expectancy. Never emits raw rows/values/paths.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import re

SCHEMA_VERSION = "ms2-records-quality-offline-v1"
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_ROWS = 2_000_000
CSV_FIELD_LIMIT = 1024 * 1024

HEADERS = {
    "ticks.csv": "captured_at,ticker,name,exchange_time,price,direction_estimate,bid,ask,note",
    "market_snapshots.csv": "captured_at,ticker,name,price,volume,vwap,bid,ask,bid_qty,ask_qty,market_sell,market_buy,over,under",
    "condition_log.csv": "captured_at,ticker,name,price,vwap,ema9,ema20,trend_long,trend_short,or5_high,or5_low,or15_high,or15_low,bar_burst,flow_bias,whipsaw,chase_guard,or5_long,or5_short,or15_long,or15_short,pullback_long,pullback_short,signal,strategy",
    "under_over.csv": "captured_at,ticker,name,price,over,under,under_ratio,over_under_change,vwap",
    "trade_signals.csv": "captured_at,ticker,name,signal,strategy,signal_bar,entry,stop,target1,target2,market_state,breadth_pct,sector_breadth_pct,hold_signal,hold_score",
}
HEADERS = {name: tuple(columns.split(",")) for name, columns in HEADERS.items()}
NUMERIC_FIELDS = {
    "price", "volume", "vwap", "bid", "ask", "bid_qty", "ask_qty",
    "market_sell", "market_buy", "over", "under", "under_ratio",
    "over_under_change", "ema9", "ema20", "or5_high", "or5_low",
    "or15_high", "or15_low", "bar_burst", "flow_bias", "entry",
    "stop", "target1", "target2", "breadth_pct", "sector_breadth_pct",
    "hold_score",
}
NONNEGATIVE_FIELDS = {
    "volume", "vwap", "bid", "ask", "bid_qty", "ask_qty",
    "market_sell", "market_buy", "over", "under", "ema9", "ema20",
    "or5_high", "or5_low", "or15_high", "or15_low", "bar_burst",
    "entry", "stop", "target1", "target2",
}
RESEARCH_USES = {
    "ticks.csv": "PRICE_OBSERVATION_ONLY_NO_FILL_OR_TRADE_VOLUME",
    "market_snapshots.csv": "MARKET_STATE_CANDIDATE_ONLY",
    "condition_log.csv": "DERIVED_FEATURE_CANDIDATE_ONLY",
    "under_over.csv": "QUOTE_PRESSURE_CANDIDATE_ONLY",
    "trade_signals.csv": "HISTORICAL_SIGNAL_CANDIDATE_ONLY",
}


def _reason(reasons: dict[str, int], code: str) -> None:
    reasons[code] = reasons.get(code, 0) + 1


def _link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _stat_key(stat) -> tuple[int, int, int, int, int]:
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _check_numeric(row: dict[str, str], reasons: dict[str, int]) -> None:
    for key in sorted(NUMERIC_FIELDS.intersection(row)):
        value = row[key]
        if value == "":
            if key == "price":
                _reason(reasons, "PRICE_MISSING")
            continue  # other missing values stay missing; never imputed as zero
        try:
            parsed = Decimal(value)
            if not parsed.is_finite():
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            _reason(reasons, "NONFINITE_OR_INVALID_NUMERIC")
            continue
        if key == "price" and parsed <= 0:
            _reason(reasons, "PRICE_NONPOSITIVE")
        if key in NONNEGATIVE_FIELDS and parsed < 0:
            _reason(reasons, "NEGATIVE_QUANTITY_OR_LEVEL")


def _audit_file(root: Path, file_name: str, date_name: str) -> dict:
    path = root / file_name
    report = {
        "status": "BLOCKED", "records_parsed": 0, "reason_counts": {},
        "same_tick_key_ambiguous": 0, "use": RESEARCH_USES[file_name],
        "source_authenticated": False, "pit_eligible": False,
    }
    reasons = report["reason_counts"]
    try:
        if _link(path):
            _reason(reasons, "LINK_REFUSED")
            return report
        before = path.stat()
        if not path.is_file():
            _reason(reasons, "NOT_REGULAR_FILE")
            return report
        if before.st_size > MAX_FILE_BYTES:
            _reason(reasons, "FILE_TOO_LARGE")
            return report
        if before.st_size == 0:
            _reason(reasons, "EMPTY_FILE")
            return report
        previous: dict[str, datetime] = {}
        tick_seen: set[tuple[str, str, str]] = set()
        original_limit = csv.field_size_limit()
        try:
            csv.field_size_limit(CSV_FIELD_LIMIT)
            with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as stream:
                fd_before = _stat_key(os.fstat(stream.fileno()))
                reader = csv.reader(stream, strict=True)
                header = next(reader, None)
                if header != list(HEADERS[file_name]):
                    _reason(reasons, "HEADER_CONTRACT_MISMATCH")
                    return report
                for values in reader:
                    report["records_parsed"] += 1
                    if report["records_parsed"] > MAX_ROWS:
                        _reason(reasons, "ROW_LIMIT_EXCEEDED")
                        break
                    if len(values) != len(header):
                        _reason(reasons, "ROW_SHAPE_INVALID")
                        continue
                    row = dict(zip(header, values))
                    ticker = row["ticker"]
                    if not ticker.strip():
                        _reason(reasons, "TICKER_MISSING")
                    stamp = None
                    try:
                        if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", row["captured_at"]):
                            raise ValueError("LOCAL_TIME_FORMAT_INVALID")
                        stamp = datetime.fromisoformat(row["captured_at"])
                        if stamp.tzinfo is not None or stamp.strftime("%Y-%m-%d") != date_name:
                            _reason(reasons, "CAPTURE_DATE_OR_TIME_INVALID")
                            stamp = None
                    except (ValueError, TypeError):
                        _reason(reasons, "CAPTURE_DATE_OR_TIME_INVALID")
                    if stamp is not None and ticker:
                        if ticker in previous and stamp < previous[ticker]:
                            _reason(reasons, "TICKER_LOCAL_CLOCK_REVERSE")
                        previous[ticker] = stamp
                    _check_numeric(row, reasons)
                    if file_name == "ticks.csv":
                        try:
                            datetime.strptime(row["exchange_time"], "%H:%M:%S")
                        except ValueError:
                            _reason(reasons, "EXCHANGE_TIME_FORMAT_INVALID")
                        # Repeated key may be multiple real executions.
                        # Count ambiguity; never deduplicate or label duplicates.
                        key = (ticker, row["exchange_time"], row["price"])
                        if key in tick_seen:
                            report["same_tick_key_ambiguous"] += 1
                        else:
                            tick_seen.add(key)
                fd_after = _stat_key(os.fstat(stream.fileno()))
        finally:
            csv.field_size_limit(original_limit)
        after = path.stat()
        # Bind path and open-descriptor observations to the same file identity.
        # Individually stable views do not rule out a pathname/open race.
        # Windows can expose different timestamp representations through path
        # stat and handle fstat. Preserve complete stability checks within each
        # API, and bind the two views using stable file identity and size.
        path_before = _stat_key(before)
        path_after = _stat_key(after)
        if (path_before != path_after or fd_before != fd_after
                or path_before[:3] != fd_before[:3]
                or path_after[:3] != fd_after[:3]):
            _reason(reasons, "FILE_CHANGED_DURING_READ")
        if report["records_parsed"] == 0:
            _reason(reasons, "NO_DATA_ROWS")
        if not reasons:
            report["status"] = "Q1_PARSED_ONLY"
        return report
    except FileNotFoundError:
        _reason(reasons, "MISSING")
    except (PermissionError, OSError):
        _reason(reasons, "FILE_READ_FAILED")
    except (UnicodeError, csv.Error):
        _reason(reasons, "CSV_OR_ENCODING_INVALID")
    except (ValueError, OverflowError):
        _reason(reasons, "PARSE_FAILED")
    return report


def audit(day_directory: str | Path) -> dict:
    """Explicit one-day folder only. No recursive traversal, writes or network."""
    root = Path(day_directory)
    out = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED", "files": {}, "research_only": True,
        "source_authenticated": False, "pit_research_eligible": False,
        "shadow_forward_eligible": False, "performance_eligible": False,
        "eligible_observed_n": 0, "fill_confirmed": False,
        "real_submit_allowed": False, "promotion_eligible": False,
        "statistical_edge_confirmed": False,
    }
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", root.name):
        out["block_reason"] = "DAY_DIRECTORY_NAME_INVALID"
        return out
    try:
        datetime.strptime(root.name, "%Y-%m-%d")
        if _link(root) or not root.is_dir():
            out["block_reason"] = "DAY_DIRECTORY_INVALID_OR_LINK"
            return out
        for filename in HEADERS:
            out["files"][filename] = _audit_file(root, filename, root.name)
    except (OSError, ValueError):
        out["block_reason"] = "DAY_DIRECTORY_READ_FAILED"
        return out
    if all(v["status"] == "Q1_PARSED_ONLY" for v in out["files"].values()):
        out["status"] = "Q1_PARSED_ONLY"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Private MS2 records structural audit, offline and read-only")
    parser.add_argument("--day-dir", required=True, help="Explicit YYYY-MM-DD directory; not printed")
    args = parser.parse_args()
    result = audit(args.day_dir)
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0 if result["status"] == "Q1_PARSED_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
