"""Private, read-only ingress from MS2 observation files to the virtual fill audit.

Issue #344. This module does not change the collector, the 15-second
resampler, the shadow fill model, or canonical execution hashes. It does
not submit orders and it does not write market data back.

The live watcher persists three local files. None of them is a
point-in-time quote contract:

- ``kioxia_ticks_YYYYMMDD.csv`` from ``Write-TickLogDiff``:
  ``recorded_at,tick_time,price,volume,poll_seq``.
  ``tick_time`` is the RssTickList clock at second resolution and has no
  date. ``recorded_at`` is the watcher PC's ``Get-Date`` when the row was
  appended, formatted ``yyyy-MM-dd HH:mm:ss`` with no offset. ``poll_seq``
  increments once per poll, before the window is scanned. Several new
  prints can share one ``poll_seq``. That is poll order, not exchange
  order. There is no symbol, event id, bid, ask, quantity, freshness,
  timezone, or ``available_at``.
- ``kioxia_tick_diag_YYYYMMDD.csv``:
  ``poll_time,window_size,overlap_with_prev,new_appended,suspected_gap``.
  ``suspected_gap`` is true when the previous poll's keys disappeared from
  the 300-print window. It is not joined onto a print or a 15-second bar.
- ``kioxia_15s_YYYYMMDD.csv``:
  ``bucket_start,open,high,low,close,volume,tick_count``.
  Empty buckets are omitted. The resampler states that order inside a
  bucket follows ``recorded_at`` then ``poll_seq`` only.
- ``気配値ログ.csv`` stores a minute clock, aggregate OVER/UNDER size, and
  the top bid/ask prices. It does not store top-of-book quantities, an
  offset, or ``available_at``.

Those clocks are not the same instant:

- exchange print time, as MS2 presented it (``tick_time``, time of day);
- the moment the collector appended the row (``recorded_at``);
- the moment BRAIN could use the row (not recorded).

RssTickList does not store a separate receive time from the append time.

A print price is never copied into bid or ask. A missing timezone is
never filled with JST. A missing timestamp is never copied from another
clock. Bytes are not repaired.

The only records forwarded to ``scripts.timeseries_fill_audit`` are
explicit ``ms2-pit-observation-0.1`` JSONL rows whose own fields already
carry aware timestamps, a matching numeric offset, exchange sequence, and
book fields when the kind is QUOTE. That forward path is a contract
check. It is not an authenticated capture from the watcher, so
``evidence_origin=RECORDED`` is refused and observed eligible N stays 0.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from scripts.timeseries_fill_audit import (
    EVALUATOR_VERSION,
    evaluate_virtual_fill,
    summarize_cohort,
)

INGRESS_VERSION = "ms2-observation-ingress-0.1"
SCHEMA_VERSION = "ms2-pit-observation-0.1"
PRIVATE_PARTS = ("data", "private", "ms2_observations")
MAX_BYTES = 8 * 1024 * 1024
TICK_HEADER = ("recorded_at", "tick_time", "price", "volume", "poll_seq")
DIAG_HEADER = ("poll_time", "window_size", "overlap_with_prev", "new_appended", "suspected_gap")
BAR_HEADER = ("bucket_start", "open", "high", "low", "close", "volume", "tick_count")
BOARD_HEADER = (
    "日付", "時刻", "OVER気配数量", "UNDER気配数量", "UNDER比率",
    "最良売気配値", "最良買気配値", "状態",
)
QUOTE_BOOK = ("bid", "ask", "bid_qty", "ask_qty", "last_trade_price", "last_trade_qty", "tick_size")

SOURCE_FIELD_CATALOG = (
    {
        "field": "symbol",
        "recorded_in": "none of the watcher CSV files",
        "meaning": "RssTickList and RssMarket calls in the watcher are hardcoded to 285A.T. The CSV row does not carry a symbol.",
        "missing_treatment": "Do not infer 285A from the file name or from the script.",
    },
    {
        "field": "source",
        "recorded_in": "not a column",
        "meaning": "The producer is Kioxia_RSS_Live_Watcher.ps1 Write-TickLogDiff, Read-TickList, Read-BoardDepth, or Resample_Kioxia_Ticks_15s.ps1.",
        "missing_treatment": "Do not stamp a source id onto a legacy row.",
    },
    {
        "field": "event_id",
        "recorded_in": "absent",
        "meaning": "RssTickList has no exchange trade id. The watcher dedupes with tick_time|price|volume, so identical prints in the same second collapse.",
        "missing_treatment": "Do not mint an id from poll_seq or from the row number.",
    },
    {
        "field": "event_time",
        "recorded_in": "tick_time on the tick log; bucket_start on the 15-second file; 時刻 on the board log",
        "meaning": "tick_time is HH:mm:ss from RssTickList (OADate rendered to a clock). It has no date. bucket_start is the bucket clock, not a print time. Board 時刻 is HH:mm.",
        "missing_treatment": "Do not copy the date or the clock from recorded_at. Do not treat the clock as an aware instant.",
    },
    {
        "field": "available_at",
        "recorded_in": "absent",
        "meaning": "The time at which BRAIN could use the observation is not written.",
        "missing_treatment": "Do not substitute recorded_at, poll_time, or the file mtime.",
    },
    {
        "field": "received_at",
        "recorded_in": "absent as its own column",
        "meaning": "The Excel read and the append are not stored as separate instants. recorded_at is only the append clock.",
        "missing_treatment": "Do not rename recorded_at to received_at.",
    },
    {
        "field": "recorded_at",
        "recorded_in": "tick log column 1; diag poll_time is the same Get-Date style",
        "meaning": "Watcher local clock when the new print key was appended, yyyy-MM-dd HH:mm:ss, no offset. It orders the collector's append, not the exchange.",
        "missing_treatment": "Keep it unqualified. Do not assign JST and do not use it as event order.",
    },
    {
        "field": "timezone",
        "recorded_in": "absent",
        "meaning": "No offset is stored on tick_time, recorded_at, bucket_start, or the board clock.",
        "missing_treatment": "Do not assume Asia/Tokyo or +09:00.",
    },
    {
        "field": "poll_seq",
        "recorded_in": "tick log column 5",
        "meaning": "Process-local counter incremented once per watcher loop, before the window scan. Prints discovered in that loop share it. File order within the poll is RssTickList row order.",
        "missing_treatment": "Do not treat poll_seq, or recorded_at then poll_seq, as exchange execution order.",
    },
    {
        "field": "price",
        "recorded_in": "tick log price; 15-second OHLC; board top prices are separate cells",
        "meaning": "Tick price is a trade print. A 15-second open/high/low/close does not order the prints inside the bucket.",
        "missing_treatment": "Do not invent a print. Do not copy a print into bid or ask.",
    },
    {
        "field": "volume",
        "recorded_in": "tick log volume; 15-second volume is a sum",
        "meaning": "Tick volume is the RssTickList size for that print. Bar volume adds sizes after dropping non-positive rows in the resampler; this ingress does not repeat that drop.",
        "missing_treatment": "Do not fill a missing size with zero.",
    },
    {
        "field": "bid",
        "recorded_in": "board log 最良買気配値 only, minute clock",
        "meaning": "Top bid price from RssMarket at a minute stamp. Not aligned to a tick. Not present on the tick log or the 15-second file.",
        "missing_treatment": "Do not use the print price as the bid.",
    },
    {
        "field": "ask",
        "recorded_in": "board log 最良売気配値 only, minute clock",
        "meaning": "Top ask price from RssMarket at a minute stamp. Not present on the tick log.",
        "missing_treatment": "Do not use the print price as the ask.",
    },
    {
        "field": "bid_qty",
        "recorded_in": "absent from every persisted CSV",
        "meaning": "Read-BoardDepth sees 最良買気配数量 in Excel and does not write it. OVER/UNDER on the board log are aggregate market-order sizes, not top-of-book quantity.",
        "missing_treatment": "Do not use OVER or UNDER as bid_qty or ask_qty.",
    },
    {
        "field": "ask_qty",
        "recorded_in": "absent from every persisted CSV",
        "meaning": "Best-ask quantity stays in the live sheet. It is not in the tick, diag, 15-second, or board CSV.",
        "missing_treatment": "Do not invent a visible quantity.",
    },
    {
        "field": "suspected_gap",
        "recorded_in": "diag CSV only",
        "meaning": "True when the previous poll's keys have no overlap with the current RssTickList window. Poll-level suspicion, not a per-print flag, and not copied onto 15-second bars.",
        "missing_treatment": "A missing diag does not mean there was no gap. A False flag is not joined to a print and does not prove a complete sequence.",
    },
    {
        "field": "data_freshness",
        "recorded_in": "absent",
        "meaning": "The shadow fill model expects OK, STALE, MISSING, or FUTURE from the caller. The watcher CSVs do not record it.",
        "missing_treatment": "Do not default the legacy file to OK.",
    },
)


def source_field_catalog() -> list[dict]:
    """Return the producer semantics audited from the watcher and resampler."""
    return [dict(row) for row in SOURCE_FIELD_CATALOG]


def _safety() -> dict:
    return {
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "rss_order_enabled": False,
        "writes_performed": False,
        "legacy_history_modified": False,
        "source_authenticated": False,
    }


def _rollup(synthetic_n: int = 0) -> dict:
    return {
        "eligible_observed_n": 0,
        "synthetic_n": synthetic_n,
        "expectancy_yen": None,
        "profit_factor": None,
        "max_drawdown_yen": None,
        "verified_net_pnl_yen": None,
        "reasons": ["NO_ELIGIBLE_OBSERVED_SAMPLE"],
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }


def _report(*, status: str, state: str, reasons: list[str], producer_id: str,
            bytes_read: int = 0, input_sha256: str | None = None,
            row_count: int = 0, forwarded: bool = False, decision=None,
            forwarded_event_ids: list[str] | None = None) -> dict:
    synthetic_n = 1 if forwarded else 0
    return {
        "ingress_version": INGRESS_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "status": status,
        "state": state,
        "reasons": sorted(set(reasons)),
        "producer_id": producer_id,
        "forwarded_to_evaluator": forwarded,
        "forwarded_event_ids": list(forwarded_event_ids or []),
        "quote_fields_invented": False,
        "timezone_imputed": False,
        "dates_joined_from_recorded_at": False,
        "exchange_order_assumed_from_poll": False,
        "bytes_read": bytes_read,
        "input_sha256": input_sha256,
        "row_count": row_count,
        "eligible_observed_n": 0,
        "synthetic_decision_n": synthetic_n,
        "decision": decision,
        "rollup": _rollup(synthetic_n),
        "safety": _safety(),
    }


def _offset_text(value: datetime) -> str | None:
    offset = value.utcoffset()
    if offset is None:
        return None
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if seconds:
        return None
    return f"{sign}{hours:02d}:{minutes:02d}"


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def resolve_private_input(repo_root, relative: str) -> Path:
    """Resolve one opted-in file under data/private/ms2_observations.

    Symlinks and paths outside that directory are refused before a read.
    """
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("PRIVATE_PATH_INVALID")
    root = Path(repo_root).resolve(strict=True)
    allowed = root.joinpath(*PRIVATE_PARTS)
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or "." in rel.parts:
        raise ValueError("PRIVATE_PATH_INVALID")
    if len(rel.parts) != 4 or tuple(rel.parts[:3]) != PRIVATE_PARTS:
        raise ValueError("PRIVATE_PATH_INVALID")
    if rel.suffix.lower() not in {".csv", ".jsonl"}:
        raise ValueError("PRIVATE_PATH_INVALID")
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("PRIVATE_PATH_LINK")
    if not current.is_file():
        raise ValueError("PRIVATE_PATH_NOT_FOUND")
    resolved = current.resolve(strict=True)
    if not allowed.exists() or not resolved.is_relative_to(allowed.resolve()):
        raise ValueError("PRIVATE_PATH_INVALID")
    if resolved.stat().st_size > MAX_BYTES:
        raise ValueError("PRIVATE_FILE_TOO_LARGE")
    return resolved


def _read_stable_snapshot(path: Path) -> bytes:
    """Read two independent views; reject concurrent private file mutation.

    Offline read consistency is NOT fsync proof, authenticated source evidence,
    a producer available_at timestamp, or real-market eligibility.
    """
    try:
        if path.is_symlink():
            raise ValueError("PRIVATE_PATH_LINK")
        before = path.stat()
        if before.st_size > MAX_BYTES:
            raise ValueError("PRIVATE_FILE_TOO_LARGE")
        first = path.read_bytes()
        middle = path.stat()
        if len(first) > MAX_BYTES:
            raise ValueError("PRIVATE_FILE_TOO_LARGE")
        second = path.read_bytes()
        after = path.stat()
        if path.is_symlink():
            raise ValueError("PRIVATE_PATH_LINK")
    except OSError as exc:
        raise ValueError("SOURCE_READ_FAILED") from exc
    if len(second) > MAX_BYTES:
        raise ValueError("PRIVATE_FILE_TOO_LARGE")
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    if identity(before) != identity(middle) or identity(middle) != identity(after) or first != second:
        raise ValueError("SOURCE_CHANGED_DURING_READ")
    return second


def independent_consumer_readback(repo_root, relative_path: str | None) -> dict:
    """Offline read-only proof of when *this consumer* finished reading bytes.

    This is neither exchange provenance nor market available_at. No promotion
    or submit route is reachable from this metadata-only reader.
    """
    if not relative_path:
        return {"state": "BLOCKED", "reason": "PRIVATE_PATH_UNSET",
                "eligible_observed_n": 0, "real_submit_allowed": False}
    try:
        path = resolve_private_input(repo_root, relative_path)
        raw = _read_stable_snapshot(path)
    except (ValueError, OSError) as exc:
        code = str(exc) if isinstance(exc, ValueError) else "SOURCE_READ_FAILED"
        return {"state": "BLOCKED", "reason": code,
                "eligible_observed_n": 0, "real_submit_allowed": False}
    completed = datetime.now(timezone.utc).isoformat()
    return {
        "state": "READBACK_OBSERVED_ONLY",
        "reason": "SOURCE_PROVENANCE_NOT_AUTHENTICATED",
        "consumer_readback_completed_at": completed,
        "consumer_clock_basis": "LOCAL_UTC_POST_READBACK",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "bytes_read": len(raw),
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
    }


def reconcile_writer_consumer_receipts(writer_receipt, consumer_receipt) -> dict:
    """Compare existing offline publication and independent readback evidence.

    This checks byte identity and local-clock order, not producer identity,
    authenticated receipt signatures, exchange timing, or durable generation.
    """
    result = {"state": "BLOCKED", "reason": "RECEIPT_INVALID",
              "eligible_observed_n": 0, "real_submit_allowed": False}
    if not isinstance(writer_receipt, dict) or not isinstance(consumer_receipt, dict):
        return result
    if (writer_receipt.get("transition") != "APPENDED"
            or writer_receipt.get("writes_performed") is not True
            or writer_receipt.get("eligible_observed_n") != 0
            or writer_receipt.get("real_submit_allowed") is not False
            or consumer_receipt.get("state") != "READBACK_OBSERVED_ONLY"
            or consumer_receipt.get("eligible_observed_n") != 0
            or consumer_receipt.get("real_submit_allowed") is not False):
        return {**result, "reason": "RECEIPT_UNVERIFIED"}
    published = writer_receipt.get("file_sha256")
    consumed = consumer_receipt.get("input_sha256")
    bytes_written = writer_receipt.get("bytes_written")
    bytes_read = consumer_receipt.get("bytes_read")
    if (not isinstance(published, str) or len(published) != 64
            or any(c not in "0123456789abcdef" for c in published)
            or not isinstance(consumed, str) or len(consumed) != 64
            or any(c not in "0123456789abcdef" for c in consumed)
            or type(bytes_written) is not int or type(bytes_read) is not int
            or bytes_written <= 0 or bytes_written != bytes_read or published != consumed):
        return {**result, "reason": "PUBLICATION_READBACK_MISMATCH"}
    if (writer_receipt.get("writer_readback_clock_basis") != "WRITER_LOCAL_UTC_AFTER_READBACK"
            or consumer_receipt.get("consumer_clock_basis") != "LOCAL_UTC_POST_READBACK"):
        return {**result, "reason": "CLOCK_EVIDENCE_ABSENT"}
    try:
        writer_at = datetime.fromisoformat(writer_receipt["writer_readback_completed_at"])
        consumer_at = datetime.fromisoformat(consumer_receipt["consumer_readback_completed_at"])
        if (not _aware(writer_at) or not _aware(consumer_at)
                or writer_at.utcoffset() != timezone.utc.utcoffset(writer_at)
                or consumer_at.utcoffset() != timezone.utc.utcoffset(consumer_at)
                or consumer_at < writer_at):
            return {**result, "reason": "CLOCK_ORDER_UNVERIFIED"}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {**result, "reason": "CLOCK_ORDER_UNVERIFIED"}
    return {"state": "READBACK_MATCH_ONLY",
            "reason": "SOURCE_PROVENANCE_NOT_AUTHENTICATED",
            "published_sha256": published, "bytes_verified": bytes_read,
            "consumer_readback_completed_at": consumer_receipt["consumer_readback_completed_at"],
            "eligible_observed_n": 0, "real_submit_allowed": False}


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("DATA_CORRUPT") from exc


def _csv_table(raw: bytes) -> tuple[tuple[str, ...], list[list[str]]]:
    text = _decode(raw)
    if "\x00" in text:
        raise ValueError("DATA_CORRUPT")
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise ValueError("DATA_CORRUPT") from exc
    if not rows or not any(cell.strip() for cell in rows[0]):
        raise ValueError("EMPTY_INPUT")
    header = tuple(cell.strip() for cell in rows[0])
    if len(header) != len(set(header)) or any(not name for name in header):
        raise ValueError("DATA_CORRUPT")
    body = []
    for row in rows[1:]:
        if len(row) == 0 or (len(row) == 1 and row[0] == ""):
            raise ValueError("DATA_CORRUPT")
        if len(row) != len(header):
            raise ValueError("DATA_CORRUPT")
        body.append(row)
    return header, body


def _legacy_reasons(header: tuple[str, ...], body: list[list[str]], diag_raw: bytes | None) -> tuple[str, list[str], int]:
    if header == TICK_HEADER:
        reasons = [
            "AVAILABLE_AT_ABSENT",
            "BOOK_ABSENT",
            "EVENT_ID_ABSENT",
            "EVENT_TIME_DATE_ABSENT",
            "FRESHNESS_ABSENT",
            "POLL_SEQUENCE_IS_NOT_EXCHANGE_ORDER",
            "PRINT_IS_NOT_A_QUOTE",
            "RECORDED_AT_IS_COLLECTOR_CLOCK",
            "SYMBOL_ABSENT",
            "TIMEZONE_ABSENT",
        ]
        if diag_raw is None:
            reasons.append("GAP_DIAGNOSTIC_ABSENT")
        else:
            diag_header, diag_body = _csv_table(diag_raw)
            if diag_header != DIAG_HEADER:
                reasons.append("GAP_DIAGNOSTIC_SCHEMA_MISMATCH")
            elif not diag_body:
                reasons.append("GAP_DIAGNOSTIC_EMPTY")
            else:
                saw_gap = False
                for row in diag_body:
                    flag = row[4].strip()
                    if flag in {"True", "true"}:
                        saw_gap = True
                    elif flag not in {"False", "false"}:
                        reasons.append("SUSPECTED_GAP_FLAG_INVALID")
                if saw_gap:
                    reasons.append("SUSPECTED_GAP")
                reasons.append("GAP_NOT_JOINED_TO_PRINT")
        return "ms2_live.kioxia_tick_log", reasons, len(body)
    if header == BAR_HEADER:
        return "ms2_live.kioxia_15s", [
            "AVAILABLE_AT_ABSENT",
            "BAR_15S_INTRABAR_ORDER_UNKNOWN",
            "BUCKET_CLOCK_IS_NOT_EVENT_TIME",
            "EMPTY_BUCKETS_OMITTED",
            "TIMEZONE_ABSENT",
        ], len(body)
    if header == BOARD_HEADER:
        return "ms2_live.board_log", [
            "AVAILABLE_AT_ABSENT",
            "BOARD_QTY_ABSENT",
            "BOOK_LOG_IS_NOT_A_QUOTE",
            "MINUTE_CLOCK_ONLY",
            "TIMEZONE_ABSENT",
        ], len(body)
    if header == DIAG_HEADER:
        return "ms2_live.kioxia_tick_diag", ["DIAGNOSTIC_IS_NOT_AN_EVENT_STREAM"], len(body)
    return "ms2_live.unknown", ["UNKNOWN_MS2_SCHEMA"], len(body)


def _pairs(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("DATA_CORRUPT")
    return dict(pairs)


def _jsonl_records(raw: bytes) -> list[dict]:
    text = _decode(raw)
    if not text.strip():
        raise ValueError("EMPTY_INPUT")
    records = []
    for line in text.splitlines():
        if not line.strip():
            raise ValueError("DATA_CORRUPT")
        try:
            item = json.loads(line, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("DATA_CORRUPT") from exc
        if not isinstance(item, dict):
            raise ValueError("DATA_CORRUPT")
        records.append(item)
    # Keep malformed JSON's existing DATA_CORRUPT reason. A syntactically
    # complete last object is still uncommitted without its newline.
    if not raw.endswith(b"\n"):
        raise ValueError("PARTIAL_PUBLISHED_JSONL")
    return records


def _parse_aware(raw, *, missing: str, reasons: list[str]) -> datetime | None:
    if raw is None:
        reasons.append(missing)
        return None
    if not isinstance(raw, str) or not raw.strip():
        reasons.append("TIMESTAMP_INVALID")
        return None
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        reasons.append("TIMESTAMP_INVALID")
        return None
    if not _aware(value):
        reasons.append("TIMEZONE_UNKNOWN")
        return None
    return value


def _check_timezone(declared, instants: list[datetime], reasons: list[str]) -> None:
    if not isinstance(declared, str) or not declared.strip():
        reasons.append("TIMEZONE_UNKNOWN")
        return
    label = declared.strip()
    if label in {"JST", "Asia/Tokyo", "Japan"}:
        reasons.append("TIMEZONE_UNKNOWN")
        return
    for instant in instants:
        if _offset_text(instant) != label:
            reasons.append("TIMEZONE_MISMATCH")
            return


def _fingerprint(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _prepare_jsonl(records: list[dict], *, evidence_origin: str) -> tuple[list[str], list[dict]]:
    reasons: list[str] = []
    if evidence_origin == "RECORDED":
        return ["RECORDED_PROVENANCE_NOT_AUTHENTICATED"], []
    if evidence_origin != "SYNTHETIC":
        return ["EVIDENCE_ORIGIN_INVALID"], []
    prepared = []
    fingerprints: dict[str, str] = {}
    for record in records:
        if record.get("schema_version") != SCHEMA_VERSION:
            reasons.append("SCHEMA_VERSION_UNKNOWN")
            continue
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            reasons.append("EVENT_ID_ABSENT")
            continue
        kind = record.get("kind")
        if not isinstance(kind, str) or kind not in {"QUOTE", "ORDERED_PRINT", "OHLCV_BAR"}:
            reasons.append("KIND_INVALID")
            continue
        local: list[str] = []
        # JSON values can be unhashable (e.g. arrays/dicts). Reject invalid
        # market values before building the mixed-market set.
        market = record.get("market")
        if "market" in record and (not isinstance(market, str) or market not in {"TSE", "JNX"}):
            local.append("MARKET_INVALID")
        if not isinstance(record.get("source"), str) or not str(record.get("source")).strip():
            local.append("SOURCE_ABSENT")
        if not isinstance(record.get("symbol"), str) or not str(record.get("symbol")).strip():
            local.append("SYMBOL_ABSENT")
        event_time = _parse_aware(record.get("event_time"), missing="EVENT_TIME_ABSENT", reasons=local)
        available_at = _parse_aware(record.get("available_at"), missing="AVAILABLE_AT_ABSENT", reasons=local)
        instants = [item for item in (event_time, available_at) if item is not None]
        end_raw = record.get("event_time_end") if kind == "OHLCV_BAR" else None
        event_time_end = None
        if kind == "OHLCV_BAR" and end_raw not in (None, ""):
            event_time_end = _parse_aware(end_raw, missing="TIMESTAMP_INVALID", reasons=local)
            if event_time_end is not None:
                instants.append(event_time_end)
        for key in ("received_at", "recorded_at"):
            if key not in record or record.get(key) in (None, ""):
                continue
            parsed = _parse_aware(record.get(key), missing="TIMESTAMP_INVALID", reasons=local)
            if parsed is not None:
                instants.append(parsed)
        if event_time is None and record.get("recorded_at") not in (None, ""):
            local.append("RECORDED_AT_NOT_USED_AS_EVENT_TIME")
        if instants:
            _check_timezone(record.get("timezone"), instants, local)
        basis = record.get("sequence_basis")
        if basis == "POLL":
            local.append("POLL_ORDER_NOT_EXCHANGE_ORDER")
        elif basis != "EXCHANGE" or record.get("order_proven") is not True:
            local.append("SEQUENCE_BASIS_UNKNOWN")
        sequence = record.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            local.append("EXCHANGE_SEQUENCE_INVALID")
        if "suspected_gap" not in record or not isinstance(record.get("suspected_gap"), bool):
            local.append("SUSPECTED_GAP_UNKNOWN")
        if "data_freshness" not in record:
            local.append("FRESHNESS_ABSENT")
        if kind == "QUOTE":
            if any(key not in record for key in QUOTE_BOOK):
                local.append("BOOK_INCOMPLETE")
        if kind == "ORDERED_PRINT" and "price" not in record:
            local.append("PRICE_ABSENT")
        reasons.extend(local)
        if local:
            continue
        observation = {
            "event_id": event_id.strip(),
            "source": record["source"].strip(),
            "symbol": record["symbol"].strip(),
            "kind": kind,
            "event_time": event_time,
            "available_at": available_at,
            "sequence": sequence,
            "data_freshness": record.get("data_freshness"),
            "suspected_gap": record.get("suspected_gap"),
        }
        if "session" in record:
            observation["session"] = record.get("session")
        if "received_at" in record and record.get("received_at") not in (None, ""):
            observation["received_at"] = _parse_aware(record.get("received_at"), missing="TIMESTAMP_INVALID", reasons=[])
        if kind == "QUOTE":
            for key in QUOTE_BOOK:
                observation[key] = record.get(key)
        elif kind == "ORDERED_PRINT":
            observation["price"] = record.get("price")
            if "volume" in record:
                observation["volume"] = record.get("volume")
        else:
            for key in ("open", "high", "low", "close", "volume", "bar_seconds"):
                if key in record:
                    observation[key] = record.get(key)
            if event_time_end is not None:
                observation["event_time_end"] = event_time_end
        token = _fingerprint(record)
        prior = fingerprints.get(observation["event_id"])
        if prior is not None and prior != token:
            reasons.append("CONFLICTING_EVENT_ID")
            continue
        fingerprints[observation["event_id"]] = token
        if "market" in record:
            observation["market"] = record.get("market")
        prepared.append(observation)
    markets = {item.get("market") for item in prepared if "market" in item}
    if len(markets) > 1:
        reasons.append("MIXED_MARKET")
    unique_events = {}
    for item in prepared:
        unique_events.setdefault(item["event_id"], item)
    sequences = [item["sequence"] for item in unique_events.values() if isinstance(item.get("sequence"), int)]
    if len(sequences) != len(set(sequences)):
        reasons.append("EXCHANGE_SEQUENCE_INVALID")
    ordered = sorted(
        (
            item for item in unique_events.values()
            if _aware(item.get("event_time")) and isinstance(item.get("sequence"), int)
        ),
        key=lambda item: (item["event_time"], item["sequence"]),
    )
    previous_time = None
    previous_sequence = None
    for item in ordered:
        if previous_time is not None and item["event_time"] > previous_time and item["sequence"] <= previous_sequence:
            reasons.append("SEQUENCE_TIME_CONFLICT")
            break
        if previous_time is None or item["event_time"] > previous_time:
            previous_time = item["event_time"]
            previous_sequence = item["sequence"]
        elif item["sequence"] > previous_sequence:
            previous_sequence = item["sequence"]
    blocking = {
        "RECORDED_PROVENANCE_NOT_AUTHENTICATED",
        "EVIDENCE_ORIGIN_INVALID",
        "SCHEMA_VERSION_UNKNOWN",
        "EVENT_ID_ABSENT",
        "KIND_INVALID",
        "MARKET_INVALID",
        "SOURCE_ABSENT",
        "SYMBOL_ABSENT",
        "EVENT_TIME_ABSENT",
        "AVAILABLE_AT_ABSENT",
        "TIMESTAMP_INVALID",
        "TIMEZONE_UNKNOWN",
        "TIMEZONE_MISMATCH",
        "POLL_ORDER_NOT_EXCHANGE_ORDER",
        "SEQUENCE_BASIS_UNKNOWN",
        "EXCHANGE_SEQUENCE_INVALID",
        "SEQUENCE_TIME_CONFLICT",
        "SUSPECTED_GAP_UNKNOWN",
        "FRESHNESS_ABSENT",
        "BOOK_INCOMPLETE",
        "PRICE_ABSENT",
        "CONFLICTING_EVENT_ID",
        "MIXED_MARKET",
        "DATA_CORRUPT",
        "EMPTY_INPUT",
    }
    if any(code in blocking for code in reasons):
        return sorted(set(reasons)), []
    for item in prepared:
        item.pop("sequence", None)
        item.pop("market", None)
    return [], prepared


def _forward(signal, observations, *, as_of, evidence_origin, cost) -> dict:
    decision = evaluate_virtual_fill(
        signal if isinstance(signal, dict) else {},
        observations,
        as_of=as_of,
        evidence_origin=evidence_origin,
        cost=cost,
    )
    decision["real_submit_allowed"] = False
    decision["promotion_eligible"] = False
    decision["statistical_edge_confirmed"] = False
    decision["real_fill"] = False
    return decision


def audit_private_observation(repo_root, relative_path: str | None, *, signal=None, as_of=None,
                              evidence_origin: str = "SYNTHETIC", cost=None,
                              diag_relative_path: str | None = None,
                              expected_sha256: str | None = None,
                              writer_receipt: dict | None = None) -> dict:
    """Read one opted-in private file, or read nothing when the path is unset.

    The same bytes and the same caller arguments produce the same report.
    This function does not create, repair, or overwrite files.
    """
    if relative_path is None or relative_path == "":
        return _report(
            status="NOT_READ",
            state="UNKNOWN",
            reasons=["PRIVATE_PATH_UNSET"],
            producer_id="none",
        )
    try:
        path = resolve_private_input(repo_root, relative_path)
        diag_path = None
        if diag_relative_path not in (None, ""):
            diag_path = resolve_private_input(repo_root, diag_relative_path)
    except ValueError as exc:
        code = str(exc)
        if code not in {
            "PRIVATE_PATH_INVALID",
            "PRIVATE_PATH_LINK",
            "PRIVATE_PATH_NOT_FOUND",
            "PRIVATE_FILE_TOO_LARGE",
        }:
            code = "PRIVATE_PATH_INVALID"
        return _report(status="BLOCKED", state="BLOCKED", reasons=[code], producer_id="none")
    except OSError:
        return _report(status="BLOCKED", state="BLOCKED", reasons=["PRIVATE_PATH_INVALID"], producer_id="none")

    try:
        raw = _read_stable_snapshot(path)
        diag_raw = _read_stable_snapshot(diag_path) if diag_path is not None else None
        # Reading two individually stable files is not an atomic pair.
        # Refuse a changed primary while reading the gap diagnostic, even
        # when the current primary bytes are syntactically valid.
        if diag_path is not None and _read_stable_snapshot(path) != raw:
            raise ValueError("SOURCE_CHANGED_DURING_READ")
    except ValueError as exc:
        return _report(status="BLOCKED", state="BLOCKED",
                       reasons=[str(exc)], producer_id="none")
    digest = hashlib.sha256(raw).hexdigest()
    # The existing Writer report is diagnostic, never independent provenance.
    # Accept only a completed APPENDED publication, then compare the receipt
    # digest against the independently read file. No observed promotion.
    if writer_receipt is not None:
        if not isinstance(writer_receipt, dict):
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["WRITER_RECEIPT_INVALID"], producer_id="none",
                           bytes_read=len(raw), input_sha256=digest)
        if (writer_receipt.get("transition") != "APPENDED"
                or writer_receipt.get("writes_performed") is not True
                or writer_receipt.get("writer_status") not in {"ADMITTED_INCOMPLETE", "PROJECTABLE_SYNTHETIC"}
                or writer_receipt.get("real_submit_allowed") is not False
                or writer_receipt.get("eligible_observed_n") != 0):
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["WRITER_PUBLICATION_UNVERIFIED"], producer_id="none",
                           bytes_read=len(raw), input_sha256=digest)
        # A digest alone does not bind the reported publication length.
        # The Writer's APPENDED receipt contains bytes_written for the full
        # published file. A missing/false/bool length must fail closed.
        receipt_size = writer_receipt.get("bytes_written")
        if (isinstance(receipt_size, bool) or not isinstance(receipt_size, int)
                or receipt_size != len(raw)):
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["WRITER_PUBLICATION_SIZE_MISMATCH"],
                           producer_id="none", bytes_read=len(raw), input_sha256=digest)
        receipt_hash = writer_receipt.get("file_sha256")
        if (not isinstance(receipt_hash, str) or len(receipt_hash) != 64
                or any(c not in "0123456789abcdef" for c in receipt_hash)):
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["WRITER_RECEIPT_INVALID"], producer_id="none",
                           bytes_read=len(raw), input_sha256=digest)
        if receipt_hash != digest:
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["PUBLISHED_SHA256_MISMATCH"], producer_id="none",
                           bytes_read=len(raw), input_sha256=digest)
    # Only a caller-supplied, independently obtained publication digest can
    # cross-check this read. Do not infer provenance or available_at from it.
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, str)
                or len(expected_sha256) != 64
                or any(c not in "0123456789abcdef" for c in expected_sha256)):
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["EXPECTED_SHA256_INVALID"],
                           producer_id="none", bytes_read=len(raw), input_sha256=digest)
        if digest != expected_sha256:
            return _report(status="BLOCKED", state="BLOCKED",
                           reasons=["PUBLISHED_SHA256_MISMATCH"],
                           producer_id="none", bytes_read=len(raw), input_sha256=digest)
    stripped = raw.lstrip(b"\xef\xbb\xbf").lstrip()
    try:
        if stripped.startswith(b"{") or path.suffix.lower() == ".jsonl":
            if diag_raw is not None:
                return _report(
                    status="BLOCKED", state="BLOCKED", reasons=["DIAGNOSTIC_NOT_APPLICABLE"],
                    producer_id="ms2_pit_jsonl", bytes_read=len(raw), input_sha256=digest,
                )
            records = _jsonl_records(raw)
            block_reasons, observations = _prepare_jsonl(records, evidence_origin=evidence_origin)
            if block_reasons or not observations:
                reasons = block_reasons or ["NO_OBSERVATIONS"]
                return _report(
                    status="BLOCKED", state="BLOCKED", reasons=reasons,
                    producer_id="ms2_pit_jsonl", bytes_read=len(raw), input_sha256=digest,
                    row_count=len(records),
                )
            decision = _forward(signal, observations, as_of=as_of, evidence_origin="SYNTHETIC", cost=cost)
            return _report(
                status="FORWARDED",
                state=decision["state"],
                reasons=list(decision["reasons"]),
                producer_id="ms2_pit_jsonl",
                bytes_read=len(raw),
                input_sha256=digest,
                row_count=len(records),
                forwarded=True,
                decision=decision,
                forwarded_event_ids=sorted(item["event_id"] for item in observations),
            )
        header, body = _csv_table(raw)
        if diag_raw is not None and header != TICK_HEADER:
            producer, reasons, row_count = _legacy_reasons(header, body, None)
            reasons.append("DIAGNOSTIC_NOT_APPLICABLE")
        else:
            producer, reasons, row_count = _legacy_reasons(header, body, diag_raw)
    except ValueError as exc:
        code = str(exc) if str(exc) in {"DATA_CORRUPT", "EMPTY_INPUT", "PARTIAL_PUBLISHED_JSONL"} else "DATA_CORRUPT"
        return _report(
            status="BLOCKED", state="BLOCKED", reasons=[code],
            producer_id="ms2_live.unreadable", bytes_read=len(raw), input_sha256=digest,
        )
    if evidence_origin == "RECORDED":
        reasons.append("RECORDED_PROVENANCE_NOT_AUTHENTICATED")
    return _report(
        status="BLOCKED", state="BLOCKED", reasons=reasons, producer_id=producer,
        bytes_read=len(raw) + (len(diag_raw) if diag_raw is not None else 0),
        input_sha256=digest, row_count=row_count,
    )


def cohort_report(decisions: list[dict]) -> dict:
    """Keep TRAIN, TEST, SHADOW, and synthetic closes out of observed EV."""
    summary = summarize_cohort(decisions)
    observed = summary.get("observed_eligible_n") or 0
    origins = {row.get("evidence_origin") for row in decisions}
    if observed == 0 or summary.get("mixed_cohort") or origins != {"RECORDED"}:
        summary["expectancy_yen"] = None
        summary["profit_factor"] = None
        summary["max_drawdown_yen"] = None
        summary["verified_net_pnl_yen"] = None
        reasons = list(summary.get("reasons") or [])
        if observed == 0:
            reasons.append("NO_ELIGIBLE_OBSERVED_SAMPLE")
        summary["reasons"] = sorted(set(reasons))
    summary["eligible_observed_n"] = observed if origins == {"RECORDED"} else 0
    summary["statistical_edge_confirmed"] = False
    summary["promotion_eligible"] = False
    summary["real_submit_allowed"] = False
    return summary


def redact_for_export(report: dict) -> dict:
    """Drop fill prices and the evaluator payload from a local text export."""
    hidden = {"decision"}
    exported = {key: value for key, value in report.items() if key not in hidden}
    decision = report.get("decision")
    exported["decision_state"] = None if not isinstance(decision, dict) else decision.get("state")
    exported["decision_reasons"] = None if not isinstance(decision, dict) else list(decision.get("reasons") or [])
    return exported


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Read-only private MS2 observation admission")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--input", default="", help="data/private/ms2_observations/<file> or empty to read nothing")
    parser.add_argument("--diag", default="")
    args = parser.parse_args(argv)
    report = audit_private_observation(
        args.repo_root,
        args.input or None,
        diag_relative_path=args.diag or None,
    )
    json.dump(redact_for_export(report), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0
