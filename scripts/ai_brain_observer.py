"""V10 independent local BRAIN observation engine (read-only, NO orders).

Consumes only the Controller's private live_ms2.json. Produces an isolated
local status file with coarse OR15/VWAP watch observations, not tradable
signals or verified profitability. Collector publication time is NOT a
verified exchange tick time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time

SCHEMA = "ai-brain-observer-1"
SOURCE = "MarketSpeed II RSS / local PC"
WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
MAX_INPUT_BYTES = 8_000_000
MAX_AGE_SECONDS = 60
ALLOWED = {"OR15_ABOVE_VWAP_WATCH", "OR15_BELOW_VWAP_WATCH"}
MAX_OBSERVATIONS = 5


def _aware(value):
    if not isinstance(value, str) or not value:
        raise ValueError("TIMESTAMP_MISSING")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("TIMESTAMP_INVALID") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("TIMESTAMP_TZ_MISSING")
    return result.astimezone(timezone.utc)


def _number(value):
    return (isinstance(value, (float, int)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _safe_symbol(value):
    if not isinstance(value, str) or not (3 <= len(value) <= 20):
        return False
    return all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.T" for c in value)


def analyze(snapshot, *, now, file_modified_at):
    """Strict data-quality gate plus deterministic informational observations."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DECISION_TIME_WITHOUT_TZ")
    reasons = []
    if not isinstance(snapshot, dict):
        reasons.append("INPUT_NOT_OBJECT")
        snapshot = {}
    if snapshot.get("schema_version") != "ms2-common-1.0":
        reasons.append("WRONG_INPUT_SCHEMA")
    if snapshot.get("source") != SOURCE or snapshot.get("source_mode") != "MS2_RSS_WORKBOOK":
        reasons.append("SOURCE_IDENTITY_UNVERIFIED")
    if snapshot.get("real_submit_allowed") is not False:
        reasons.append("REAL_ORDER_FLAG_UNSAFE")
    if snapshot.get("data_conflict") is not False or snapshot.get("stale") is not False:
        reasons.append("DATA_CONFLICT_OR_STALE")
    if snapshot.get("live_values_available") is not True or snapshot.get("price_source_status") != "OK":
        reasons.append("PRICE_SOURCE_UNVERIFIED")
    if snapshot.get("timestamp_timezone") != "Asia/Tokyo":
        reasons.append("PUBLICATION_TIMEZONE_UNVERIFIED")
    publication_at = None
    try:
        publication_at = _aware(snapshot.get("observed_at_offset"))
        if publication_at.utcoffset() != timezone.utc.utcoffset(publication_at):
            raise ValueError("PUBLICATION_TIMESTAMP_ERROR")
        age = (now.astimezone(timezone.utc) - publication_at).total_seconds()
        if age < -1 or age > MAX_AGE_SECONDS:
            reasons.append("PUBLICATION_STALE_OR_FUTURE")
        # Offset of the original string, not the normalized UTC timestamp.
        original = datetime.fromisoformat(snapshot["observed_at_offset"].replace("Z", "+00:00"))
        if original.utcoffset().total_seconds() != 9 * 3600:
            reasons.append("PUBLICATION_JST_OFFSET_INVALID")
    except ValueError:
        reasons.append("PUBLICATION_TIMESTAMP_INVALID")
    if file_modified_at is None or file_modified_at.tzinfo is None or file_modified_at.utcoffset() is None:
        reasons.append("INPUT_FILE_TIME_UNVERIFIED")
    else:
        age = (now.astimezone(timezone.utc) - file_modified_at.astimezone(timezone.utc)).total_seconds()
        if age < -1 or age > MAX_AGE_SECONDS:
            reasons.append("INPUT_FILE_STALE_OR_FUTURE")
    diag = snapshot.get("live_price_diagnostics")
    if not isinstance(diag, dict):
        reasons.append("DIAGNOSTICS_MISSING")
    else:
        if diag.get("workbook_name") != WORKBOOK or diag.get("workbook_identity_verified") is not True:
            reasons.append("WORKBOOK_IDENTITY_UNVERIFIED")
        if diag.get("source_mode") != "MS2_RSS_WORKBOOK" or diag.get("price_source_status") != "OK":
            reasons.append("DIAGNOSTICS_SOURCE_UNVERIFIED")
        if diag.get("data_conflict") is not False or diag.get("live_values_available") is not True:
            reasons.append("DIAGNOSTICS_CONFLICT")
        for key in ("collector_count", "watcher_count"):
            if type(diag.get(key)) is not int or diag[key] != 1:
                reasons.append("PROCESS_COUNT_UNVERIFIED")
    rows = snapshot.get("all_targets")
    valid_count = snapshot.get("valid")
    if (not isinstance(rows, list) or len(rows) < 90 or len(rows) > 110 or
            type(valid_count) is not int or valid_count < 90 or valid_count > 110):
        reasons.append("UNIVERSE_COVERAGE_UNVERIFIED")
    unique = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or not _safe_symbol(row.get("ticker")):
                reasons.append("ROW_IDENTITY_INVALID")
                continue
            sym = row["ticker"]
            if sym in unique or row.get("sheet_code") != sym or row.get("data") != "LIVE":
                reasons.append("ROW_IDENTITY_INVALID")
            unique.add(sym)
    watch = []
    counts = {name: 0 for name in sorted(ALLOWED)}
    non_fresh_rows = 0
    if not reasons and isinstance(rows, list):
        for row in rows:
            # Only a row the Collector judged FRESH this cycle (own quote time,
            # same day, within 120 s) is observed; a stale, undated or
            # unknown row is counted and skipped, never read as current.
            if row.get("aggregate_row_fresh") is not True:
                non_fresh_rows += 1
                continue
            price, vwap, high, low = (row.get("price"), row.get("vwap"),
                                      row.get("or_high"), row.get("or_low"))
            # Incomplete OR15 and missing VWAP are not signs.
            if not all(_number(n) for n in (price, vwap, high, low)) or high <= low:
                continue
            kind = None
            if price > high and price > vwap:
                kind = "OR15_ABOVE_VWAP_WATCH"
            elif price < low and price < vwap:
                kind = "OR15_BELOW_VWAP_WATCH"
            if kind:
                counts[kind] += 1
                if len(watch) < MAX_OBSERVATIONS:
                    watch.append({"symbol": row["ticker"], "observation": kind})
    status = "OBSERVATION_ONLY" if not reasons else "BLOCKED"
    return {
        "state": status,
        "reasons": sorted(set(reasons)),
        "source_publication_at": publication_at.isoformat() if publication_at else None,
        "last_market_data_at": None,  # source_timestamp is time-only, not an absolute exchange-time receipt
        "exchange_tick_date_verified": False,
        "signal_provenance_verified": False,
        "tested_expectancy_available": False,
        "observed_rows": len(rows) - non_fresh_rows if status == "OBSERVATION_ONLY" else 0,
        "non_fresh_rows_skipped": non_fresh_rows if status == "OBSERVATION_ONLY" else 0,
        "watch_counts": counts if status == "OBSERVATION_ONLY" else {name: 0 for name in sorted(ALLOWED)},
        "watch_observations": watch,
    }


def status_snapshot(result, *, now, pid):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("DECISION_TIME_WITHOUT_TZ")
    return {
        "schema_version": SCHEMA,
        "component_role": "INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE",
        "engine_pid": pid,
        "updated_at": now.astimezone(timezone.utc).isoformat(),
        "state": result["state"],
        "reasons": result["reasons"],
        "source_publication_at": result["source_publication_at"],
        "last_market_data_at": None,
        "exchange_tick_date_verified": False,
        "signal_provenance_verified": False,
        "observed_rows": result["observed_rows"],
        "watch_counts": result["watch_counts"],
        "watch_observations": result["watch_observations"],
        "tested_expectancy_available": False,
        "source_authenticated": False,
        "cross_source_join_allowed": False,
        "promotion_eligible": False,
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
    }


def read_snapshot(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("INPUT_FILE_UNAVAILABLE")
    stat = path.stat()
    if not 2 <= stat.st_size <= MAX_INPUT_BYTES:
        raise ValueError("INPUT_SIZE_INVALID")
    with path.open("r", encoding="utf-8-sig") as f:
        content = json.load(f)
    if not isinstance(content, dict):
        raise ValueError("INPUT_NOT_OBJECT")
    return content, datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


def write_status(path: Path, status: dict):
    # Never touch original market CSV, Excel, or live_ms2.json.
    if not path.parent.is_dir() or path.parent.is_symlink() or path.is_symlink():
        raise ValueError("UNTRUSTED_STATUS_DESTINATION")
    if path.name != "ai_brain_observer_status_v1.json":
        raise ValueError("STATUS_PATH_NOT_CANONICAL")
    content = json.dumps(status, sort_keys=True, ensure_ascii=True).encode("ascii")
    if len(content) > 65536:
        raise ValueError("STATUS_TOO_LARGE")
    temp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    if temp.exists() or temp.is_symlink():
        raise ValueError("TEMP_STATUS_FILE_EXISTS")
    try:
        with temp.open("xb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def run_once(live_path: Path, status_path: Path, *, now=None, pid=None):
    now = now or datetime.now(timezone.utc)
    pid = pid if pid is not None else os.getpid()
    try:
        data, mtime = read_snapshot(live_path)
        result = analyze(data, now=now, file_modified_at=mtime)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        # Never reveal raw values or private paths in the status.
        result = analyze({}, now=now, file_modified_at=None)
        result["reasons"] = sorted(set(result["reasons"] + ["INPUT_UNAVAILABLE_OR_INVALID"]))
    status = status_snapshot(result, now=now, pid=pid)
    write_status(status_path, status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only independent V10 BRAIN observation processor")
    parser.add_argument("--live", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if not 2 <= args.interval <= 60:
        parser.error("interval must be between 2 and 60 seconds")
    live, status_path = Path(args.live), Path(args.status)
    if args.once:
        run_once(live, status_path)
        return 0
    while True:
        run_once(live, status_path)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
