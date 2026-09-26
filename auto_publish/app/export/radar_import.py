"""Read-only importer for Opportunity Radar ``condition_log.csv``.

Source format (written by the MS2 collector, which this module never imports or
touches): UTF-8 with BOM, every value double-quoted, header ``EXPECTED_HEADER``.
One row per ticker per snapshot cycle; a row's boolean flags say whether a
condition held at that moment.

Output is split in two, and the split is the point:

* PUBLIC events (``daily_summary.radar_events``): ticker, name, JST time, event
  type, direction, price at detection, price-vs-VWAP relation, public basis
  codes, source, event_id and a source_ref. Nothing else.
* INTERNAL records (``internal/radar_internal.json``, local only): the raw
  indicator values, guard flags and the collector's signal/strategy labels,
  keyed by event_id, for "why was this chosen" explanations. Never published.

Events are the FIRST row where a flag is true for (ticker, event type) in the
session -- the same condition held over many snapshots is one event, not many.
event_id = sha256(session|ticker|event|captured_at) -> stable across re-imports.

The log is append-only and may still be growing while we read it: we parse one
snapshot of bytes, hash exactly those bytes, and afterwards require the file to
still START with them (appends are fine, any rewrite is fail-closed).
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import date, datetime, time

from ..clock import JST
from ..errors import EvidenceError, ValidationError
from ..hashing import sha256_bytes

FILE_NAME = "condition_log.csv"
EXPECTED_HEADER = [
    "captured_at", "ticker", "name", "price", "vwap", "ema9", "ema20", "trend_long", "trend_short", "or5_high",
    "or5_low", "or15_high", "or15_low", "bar_burst", "flow_bias", "whipsaw", "chase_guard", "or5_long", "or5_short",
    "or15_long", "or15_short", "pullback_long", "pullback_short", "signal", "strategy",
]
# flag column -> (public event type, direction, public basis codes)
EVENT_FLAGS = {
    "or5_long": ("or5_breakout", "up", ["close_above_or5_high", "price_above_vwap"]),
    "or5_short": ("or5_breakdown", "down", ["close_below_or5_low", "price_below_vwap"]),
    "or15_long": ("or15_breakout", "up", ["close_above_or15_high", "price_above_vwap"]),
    "or15_short": ("or15_breakdown", "down", ["close_below_or15_low", "price_below_vwap"]),
    "pullback_long": ("or15_retest_hold", "up", ["retest_of_or15_high_held", "price_above_vwap"]),
    "pullback_short": ("or15_retest_reject", "down", ["retest_of_or15_low_rejected", "price_below_vwap"]),
}
PUBLIC_EVENT_KEYS = {"event_id", "ticker", "name_ja", "time_jst", "detected_at_jst", "event", "direction", "price",
                     "vwap_relation", "basis", "source", "source_ref"}
INTERNAL_FIELDS = ["vwap", "ema9", "ema20", "trend_long", "trend_short", "or5_high", "or5_low", "or15_high",
                   "or15_low", "bar_burst", "flow_bias", "whipsaw", "chase_guard", "signal", "strategy"]
BOOL_COLS = ["trend_long", "trend_short", "whipsaw", "chase_guard", *EVENT_FLAGS]
NUM_COLS = ["price", "vwap", "ema9", "ema20", "or5_high", "or5_low", "or15_high", "or15_low", "bar_burst", "flow_bias"]
TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2})$")
TICKER_RE = re.compile(r"^[0-9A-Z]{4}\.T$")
SESSION_OPEN, SESSION_CLOSE = time(9, 0), time(15, 30)


def _bool(v: str, where: str) -> bool:
    if v == "True":
        return True
    if v == "False":
        return False
    raise ValidationError(f"{where}: expected True/False, got {v!r}", code="INVALID_VALUE")


def _num(v: str, where: str) -> float | None:
    if v == "":
        return None
    try:
        x = float(v)
    except ValueError as exc:
        raise ValidationError(f"{where}: not a number {v!r}", code="INVALID_VALUE") from exc
    if not math.isfinite(x):
        raise ValidationError(f"{where}: non-finite {v!r}", code="INVALID_VALUE")
    return x


def event_id_for(session_date: str, ticker: str, event: str, captured_at: str) -> str:
    return "rv_" + sha256_bytes(f"{session_date}|{ticker}|{event}|{captured_at}".encode())[:16]


def parse_condition_log(raw: bytes, session_date: str) -> dict:
    """Pure: bytes -> public events + internal records. Raises fail-closed on any anomaly."""
    file_sha = sha256_bytes(raw)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{FILE_NAME} is not UTF-8: {exc}", code="SCHEMA_INVALID") from exc
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValidationError(f"{FILE_NAME} is empty", code="SCHEMA_INVALID")
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        raise ValidationError(f"{FILE_NAME} is empty", code="SCHEMA_INVALID") from None
    if header != EXPECTED_HEADER:
        raise ValidationError(f"{FILE_NAME} header changed; refusing to guess column meaning",
                              code="SCHEMA_INVALID",
                              details={"missing": sorted(set(EXPECTED_HEADER) - set(header)),
                                       "unexpected": sorted(set(header) - set(EXPECTED_HEADER))})
    sess = date.fromisoformat(session_date)
    first: dict[tuple[str, str], dict] = {}
    seen_rows: set[str] = set()
    duplicate_rows = 0
    rows = 0
    last_ts: datetime | None = None
    prev_line = reader.line_num
    for row in reader:
        lineno = reader.line_num
        if lineno != prev_line + 1:
            raise ValidationError(f"{FILE_NAME}:{lineno}: multi-line record (embedded newline) not allowed",
                                  code="SCHEMA_INVALID")
        prev_line = lineno
        if not row or row == [""]:
            continue
        where = f"{FILE_NAME}:{lineno}"
        if len(row) != len(EXPECTED_HEADER):
            raise ValidationError(f"{where}: {len(row)} columns (expected {len(EXPECTED_HEADER)})", code="SCHEMA_INVALID")
        rec = dict(zip(EXPECTED_HEADER, row))
        m = TS_RE.match(rec["captured_at"])
        if not m:
            raise ValidationError(f"{where}: captured_at {rec['captured_at']!r} invalid", code="SCHEMA_INVALID")
        try:
            ts = datetime.fromisoformat(rec["captured_at"]).replace(tzinfo=JST)
        except ValueError as exc:
            raise ValidationError(f"{where}: captured_at not a real time", code="SCHEMA_INVALID") from exc
        if ts.date() != sess:
            raise ValidationError(f"{where}: row dated {ts.date()} in log for {session_date}", code="DATE_MISMATCH")
        if last_ts is not None and ts < last_ts:
            raise ValidationError(f"{where}: captured_at goes backwards (log is append-only)", code="LOG_NOT_MONOTONIC")
        last_ts = ts
        if not TICKER_RE.match(rec["ticker"]):
            raise ValidationError(f"{where}: ticker {rec['ticker']!r} invalid", code="SCHEMA_INVALID")
        if not rec["name"].strip():
            raise ValidationError(f"{where}: name empty", code="SCHEMA_INVALID")
        flags = {c: _bool(rec[c], f"{where}.{c}") for c in BOOL_COLS}
        nums = {c: _num(rec[c], f"{where}.{c}") for c in NUM_COLS}
        rows += 1
        raw_line = lines[lineno - 1] if lineno - 1 < len(lines) else ""
        key = raw_line.rstrip("\r\n")
        if key in seen_rows:
            duplicate_rows += 1
            continue
        seen_rows.add(key)
        in_session = SESSION_OPEN <= ts.time() <= SESSION_CLOSE
        for flag, (event, direction, basis) in EVENT_FLAGS.items():
            if not flags[flag]:
                continue
            if not in_session:
                raise ValidationError(f"{where}: {flag}=True outside the trading session", code="INVALID_VALUE")
            if (rec["ticker"], event) in first:
                continue  # same condition still holding: not a new event
            price, vwap = nums["price"], nums["vwap"]
            if price is None or price <= 0 or vwap is None or vwap <= 0:
                raise ValidationError(f"{where}: event row needs positive price and vwap", code="INVALID_VALUE")
            relation = "above" if price > vwap else "below" if price < vwap else "at"
            expected = "above" if direction == "up" else "below"
            if relation != expected:
                raise ValidationError(f"{where}: {flag} but price is {relation} VWAP (contradiction)",
                                      code="INVALID_VALUE")
            eid = event_id_for(session_date, rec["ticker"], event, rec["captured_at"])
            first[(rec["ticker"], event)] = {
                "public": {
                    "event_id": eid,
                    "ticker": rec["ticker"],
                    "name_ja": rec["name"].strip(),
                    "time_jst": ts.strftime("%H:%M"),
                    "detected_at_jst": ts.isoformat(),
                    "event": event,
                    "direction": direction,
                    "price": price,
                    "vwap_relation": relation,
                    "basis": basis,
                    "source": "opportunity_radar",
                    "source_ref": {"file": FILE_NAME, "sha256": file_sha, "row": lineno,
                                   "row_sha256": sha256_bytes(key.encode("utf-8")), "flag": flag},
                },
                "internal": {
                    "event_id": eid, "visibility": "internal",
                    "row": lineno, "captured_at": rec["captured_at"],
                    "values": {c: (flags[c] if c in flags else nums[c] if c in nums else rec[c])
                               for c in INTERNAL_FIELDS},
                },
            }
    events = sorted(first.values(), key=lambda e: (e["public"]["detected_at_jst"], e["public"]["ticker"],
                                                   e["public"]["event"]))
    for e in events:
        assert set(e["public"]) <= PUBLIC_EVENT_KEYS
    return {
        "file_sha256": file_sha,
        "bytes": len(raw),
        "rows": rows,
        "duplicate_rows": duplicate_rows,
        "public": [e["public"] for e in events],
        "internal": [e["internal"] for e in events],
    }


def read_snapshot(path) -> bytes:
    """Read the whole file once, read-only."""
    from pathlib import Path
    p = Path(path)
    if not p.is_file():
        raise EvidenceError(f"{FILE_NAME} not found", code="EXPORT_INPUT_MISSING")
    if p.is_symlink():
        raise EvidenceError(f"{FILE_NAME} must not be a symlink", code="EVIDENCE_SYMLINK")
    with open(p, "rb") as fh:
        return fh.read()


def verify_prefix_unchanged(path, snapshot: bytes) -> None:
    """The collector may keep appending; anything else (rewrite/truncate) is fail-closed."""
    with open(path, "rb") as fh:
        now = fh.read(len(snapshot))
    if now != snapshot:
        raise EvidenceError(f"{FILE_NAME} was rewritten or truncated during import",
                            code="EVIDENCE_CHANGED_DURING_INGEST")
