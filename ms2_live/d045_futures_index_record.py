"""D-045: local-only, research-only six-series futures/index CSV recorder.

STDIN protocol is a synthetic-testable snapshot from the optional PowerShell
sidecar. No MarketSpeed data is accessed here, no network/API, no trading.
Writes require three explicit gates (D-019 rights, D-035, OWNER release).
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = "100b-d045-six-series-snapshot-v1"
JST = timezone(timedelta(hours=9))
EXPECTED = {
    "N225_MINI_F": ("FOP", None),
    "TOPIX_F": ("FOP", None),
    "GROWTH250_F": ("FOP", None),
    "N225_I": ("INDEX", "N225"),
    "TOPIX_I": ("INDEX", "TOPX"),
    "GROWTH250_I": ("INDEX", "MTHR"),
}
OUTPUT = "d045_futures_index.csv"
HEADER = [
    "decision_id", "instrument_id", "kind", "symbol", "contract_month",
    "observed_at_jst", "source_date", "source_time", "source_precision",
    "source_event_at_jst", "price", "volume", "vwap",
    "best_bid", "best_ask", "best_bid_size", "best_ask_size",
    "source_time_verified", "real_time_verified", "record_only",
    "real_submit_allowed",
]
MAX_IN = 16000
MAX_DAILY = 25_000_000
MAX_AGE = timedelta(hours=36)


class Blocked(ValueError):
    pass


def _datetime(value: object) -> datetime:
    if type(value) is not str:
        raise Blocked("OBSERVED_AT_INVALID")
    try:
        d = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Blocked("OBSERVED_AT_INVALID") from exc
    if d.utcoffset() != timedelta(hours=9):
        raise Blocked("OBSERVED_AT_NOT_JST")
    return d


def _num(value: object, *, integral=False, positive=False) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or type(value) not in (float, int):
        raise Blocked("NUMERIC_FIELD_INVALID")
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise Blocked("NUMERIC_FIELD_INVALID")
    if integral:
        if int(value) != value:
            raise Blocked("INTEGER_FIELD_INVALID")
        return int(value)
    return float(value)


def _iso_event(day: str, clock: str, kind: str) -> tuple[str, str]:
    if type(day) is not str or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", day):
        raise Blocked("SOURCE_DATE_MISSING_OR_INVALID")
    if type(clock) is not str:
        raise Blocked("SOURCE_TIME_MISSING")
    precision = "SECOND" if kind == "FOP" else "MINUTE"
    pattern = r"\d\d:\d\d:\d\d" if kind == "FOP" else r"\d\d:\d\d"
    if re.fullmatch(pattern, clock) is None:
        raise Blocked("SOURCE_TIME_PRECISION_INVALID")
    try:
        d = datetime.strptime(day + " " + clock, "%Y/%m/%d %H:%M:%S" if kind == "FOP" else "%Y/%m/%d %H:%M")
    except ValueError as exc:
        raise Blocked("SOURCE_DATE_TIME_INVALID") from exc
    return d.replace(tzinfo=JST).isoformat(), precision


def validate_snapshot(snapshot: dict, *, now: datetime | None = None) -> tuple[list[dict], list[dict]]:
    """Return (valid records, rejected metadata). Reject unknown schema and types."""
    if type(snapshot) is not dict or set(snapshot) != {"schema_version", "observed_at_jst", "rows", "real_submit_allowed"}:
        raise Blocked("SNAPSHOT_SCHEMA_INVALID")
    if snapshot["schema_version"] != SCHEMA or snapshot["real_submit_allowed"] is not False:
        raise Blocked("SNAPSHOT_SAFETY_INVALID")
    observed = _datetime(snapshot["observed_at_jst"])
    now = now or datetime.now(JST)
    if now.utcoffset() != timedelta(hours=9):
        raise Blocked("CLOCK_OFFSET_INVALID")
    if observed - now > timedelta(seconds=60) or now - observed > timedelta(minutes=2):
        raise Blocked("SAMPLE_OBSERVATION_TIME_UNVERIFIED")
    rows = snapshot["rows"]
    if type(rows) is not list or len(rows) != 6 or set(
        item.get("instrument_id") for item in rows if type(item) is dict
    ) != set(EXPECTED):
        raise Blocked("SIX_SERIES_UNIVERSE_INVALID")
    valid, rejected = [], []
    exact = {"instrument_id", "kind", "symbol", "contract_month", "source_date",
             "source_time", "price", "volume", "vwap", "best_bid", "best_ask",
             "best_bid_size", "best_ask_size"}
    for item in rows:
        sid = item["instrument_id"]
        try:
            if set(item) != exact:
                raise Blocked("ROW_FIELDS_INVALID")
            kind, expected_symbol = EXPECTED[sid]
            if item["kind"] != kind or type(item["symbol"]) is not str:
                raise Blocked("ROW_KIND_OR_SYMBOL_INVALID")
            month = item["contract_month"]
            if kind == "FOP":
                if not re.fullmatch(r"\d{9}", item["symbol"]):
                    raise Blocked("FOP_CODE_UNVERIFIED")
                if type(month) is not str or not re.fullmatch(r"20\d{2}(03|06|09|12)", month):
                    raise Blocked("CONTRACT_MONTH_UNVERIFIED")
                if month < observed.strftime("%Y%m"):
                    raise Blocked("EXPIRED_CONTRACT_MONTH")
            else:
                if item["symbol"] != expected_symbol or month is not None:
                    raise Blocked("INDEX_CODE_OR_MONTH_INVALID")
                if any(item[k] is not None for k in ("vwap", "best_bid", "best_ask", "best_bid_size", "best_ask_size")):
                    raise Blocked("UNSUPPORTED_INDEX_FIELD")
            source_event, precision = _iso_event(item["source_date"], item["source_time"], kind)
            t = datetime.fromisoformat(source_event)
            # The INDEX update clock is only minute-precision: never infer
            # second-level futures lead/lag from it.
            if t - observed > timedelta(seconds=60):
                raise Blocked("FUTURE_SOURCE_EVENT")
            if observed - t > MAX_AGE:
                raise Blocked("SOURCE_EVENT_TOO_OLD")
            price = _num(item["price"], positive=True)
            if price is None:
                raise Blocked("PRICE_UNAVAILABLE")
            volume = _num(item["volume"], integral=True)
            vwap = _num(item["vwap"], positive=True)
            bid = _num(item["best_bid"], positive=True)
            ask = _num(item["best_ask"], positive=True)
            bsize = _num(item["best_bid_size"], integral=True)
            asize = _num(item["best_ask_size"], integral=True)
            if kind == "FOP" and vwap is None:
                # Partial fields permitted, but never fabricate VWAP.
                pass
            out = dict(zip(HEADER, [
                "D-045", sid, kind, item["symbol"], month or "",
                observed.isoformat(), item["source_date"], item["source_time"], precision,
                source_event, price, volume if volume is not None else "",
                vwap if vwap is not None else "", bid if bid is not None else "",
                ask if ask is not None else "", bsize if bsize is not None else "",
                asize if asize is not None else "", "UNVERIFIED",
                "UNVERIFIED", "true", "false",
            ]))
            valid.append(out)
        except Blocked as exc:
            rejected.append({"instrument_id": sid, "reason": str(exc)})
    return valid, rejected


def _private_root(root: str) -> Path:
    p = Path(root)
    if not p.is_absolute() or str(p).startswith(("\\\\", "//")) or ".." in p.parts:
        raise Blocked("PRIVATE_DIR_NOT_LOCAL_ABSOLUTE")
    if not p.is_dir():
        raise Blocked("PRIVATE_DIR_MUST_PREEXIST")
    for check in (p, *p.parents):
        if check.is_symlink():
            raise Blocked("PRIVATE_DIR_SYMLINK")
    repo_root = Path(__file__).resolve().parent.parent
    rp = p.resolve()
    if rp == repo_root or repo_root in rp.parents:
        raise Blocked("PRIVATE_DIR_INSIDE_GITHUB_REPOSITORY")
    if os.name != "nt" and (stat.S_IMODE(rp.stat().st_mode) & 0o077) != 0:
        raise Blocked("PRIVATE_DIR_PERMISSIONS_UNSAFE")
    return rp


def append_records(root: str, snapshot: dict, records: list[dict]) -> int:
    base = _private_root(root)
    if not records:
        return 0
    day = _datetime(snapshot["observed_at_jst"]).strftime("%Y-%m-%d")
    path = base / day
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink():
        raise Blocked("DAY_DIR_SYMLINK")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise Blocked("DAY_DIR_PERMISSIONS_UNSAFE")
    target = path / OUTPUT
    if target.is_symlink():
        raise Blocked("OUTPUT_SYMLINK")
    lock = path / ".d045_record.lock"
    try:
        handle = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise Blocked("SINGLE_WRITER_ALREADY_ACTIVE_OR_STALE_LOCK") from exc
    os.close(handle)
    try:
        prior = set()
        if target.exists():
            if target.stat().st_size > MAX_DAILY:
                raise Blocked("DAILY_FILE_SIZE_LIMIT")
            with target.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames != HEADER:
                    raise Blocked("EXISTING_CSV_HEADER_MISMATCH")
                for row in reader:
                    prior.add((row["instrument_id"], row["source_date"], row["source_time"],
                               row["price"], row["volume"]))
        unseen = []
        for row in records:
            key = (row["instrument_id"], row["source_date"], row["source_time"],
                   str(row["price"]), str(row["volume"]))
            if key not in prior:
                unseen.append(row)
                prior.add(key)
        if not unseen:
            return 0
        f = io.StringIO(newline="")
        writer = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        if not target.exists() or target.stat().st_size == 0:
            writer.writeheader()
        writer.writerows(unseen)
        data = f.getvalue().encode("utf-8")
        if len(data) + (target.stat().st_size if target.exists() else 0) > MAX_DAILY:
            raise Blocked("DAILY_FILE_SIZE_LIMIT")
        fd = os.open(str(target), os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return len(unseen)
    finally:
        lock.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-dir")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--rights-reviewed", action="store_true")
    ap.add_argument("--d035-accepted", action="store_true")
    ap.add_argument("--owner-release-approved", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.write and not all((args.rights_reviewed, args.d035_accepted, args.owner_release_approved)):
            raise Blocked("D019_D035_OWNER_RELEASE_GATE_NOT_MET")
        raw = sys.stdin.buffer.read(MAX_IN + 1)
        if len(raw) > MAX_IN:
            raise Blocked("INPUT_TOO_LARGE")
        doc = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(Blocked("NONFINITE_JSON")))
        records, rejected = validate_snapshot(doc)
        if args.write:
            if not args.private_dir:
                raise Blocked("PRIVATE_DIR_REQUIRED")
            written = append_records(args.private_dir, doc, records)
        else:
            written = 0
        # NEVER print prices or proprietary rows to stdout or CI.
        print(json.dumps({"state": "VALIDATED_OFFLINE" if not args.write else "RECORD_ONLY",
                          "valid": len(records), "rejected": rejected, "written": written,
                          "real_time_verified": False, "real_submit_allowed": False},
                         ensure_ascii=False))
        return 0 if not rejected else 2
    except (Blocked, ValueError, UnicodeError, TypeError, KeyError) as exc:
        print(json.dumps({"state": "BLOCKED", "reason": str(exc) if isinstance(exc, Blocked) else "INPUT_UNVERIFIED",
                          "real_submit_allowed": False}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
