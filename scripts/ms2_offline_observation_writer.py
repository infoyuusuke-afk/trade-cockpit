"""Offline writer for an already-captured MS2 board snapshot.

Issue #348. The live watcher reads ten board levels with forty sequential
``Value2`` calls inside ``Read-BoardDepth`` and keeps that list in ``$board``.
It does not persist the levels. This module turns a snapshot the caller
already holds into a private ``ms2-watcher-sidecar-0.1`` line.

It does not open Excel, does not call COM, and does not import or edit
``Kioxia_RSS_Live_Watcher.ps1``. A failure returns a report. It does not
raise into a poll loop.

Clocks are written only when the caller measured them. A naive watcher
``Get-Date`` string is not given an offset. ``poll_seq`` stays the loop
counter. Missing sizes stay null. ``available_at`` is not copied from the
watcher clock. Nothing here is a virtual close.

The lock is non-blocking and owned by one process. POSIX uses ``flock``.
Windows uses ``LockFileEx`` and does not import ``fcntl``. A temp file is
created in the same directory and replaces the published JSONL only after
flush and read-back. A crash before that replace leaves the published bytes
in place. Power-loss durability is not claimed.
"""
from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import stat
import time
from datetime import datetime
from pathlib import Path

from scripts.ms2_watcher_sidecar_contract import (
    BOARD_FIELDS,
    CURRENT_WATCHER_SOURCE,
    GAP_DIAG_FIELDS,
    GAP_FIELDS,
    LEVEL_FIELDS,
    MAX_BYTES,
    PIT_SCHEMA_VERSION,
    PRIVATE_PARTS,
    SAFETY_KEYS,
    SCHEMA_VERSION,
    TICK_FIELDS,
    TOP_FIELDS,
    _FILE_RE,
    _NAME_RE,
    audit_sidecar_bytes,
    validate_record,
)

WRITER_VERSION = "ms2-offline-observation-writer-0.1"
SOURCE_DEFAULT = WRITER_VERSION
WRITER_DEFAULT_ENABLED = False
WATCHER_INTEGRATION_APPLIED = False
LOCK_NAME = ".writer.lock"
_PATH_CODES = {"PRIVATE_PATH_INVALID", "PRIVATE_PATH_LINK"}
_KINDS = {"BOARD_SNAPSHOT", "TICK_PRINT", "GAP_DIAG"}
_CLOCK_NAMES = ("event_time", "watcher_observed_at", "received_at", "available_at", "read_started_at", "read_finished_at")
_CAPTURE_COMMON = {
    "symbol", "market", "poll_seq", "kind", "observation_id", "source",
    "watcher_observed_at", "event_time", "event_time_basis",
    "received_at", "received_at_basis", "available_at", "available_at_basis",
    "timezone", "clock_source", "clock_quality",
    "sequence_basis", "order_proven", "exchange_sequence",
    "data_freshness", "freshness_bound_ms", "quote_age_ms",
    "poll_window_ms", "capture_authenticated", "fill_missing_with_zero",
}
_CAPTURE_BOARD = _CAPTURE_COMMON | {
    "levels", "read_method", "snapshot_atomic", "bulk_read_evidenced",
    "read_started_at", "read_finished_at", "gap",
    "over_qty", "under_qty", "last_trade_price", "last_trade_qty", "tick_size",
}
_CAPTURE_TICK = _CAPTURE_COMMON | {
    "price", "volume", "gap", "read_method", "snapshot_atomic",
    "read_started_at", "read_finished_at", "read_skew_ms",
}
_CAPTURE_GAP = _CAPTURE_COMMON | {
    "window_size", "overlap_with_prev", "prev_poll_nonempty", "new_appended", "suspected_gap",
    "read_method",
}
_GAP_KEYS = {
    "window_size", "overlap_with_prev", "prev_poll_nonempty", "new_appended", "suspected_gap", "poll_seq",
}
_LEVEL_KEYS = {
    "Level", "level", "AskPrice", "ask", "BidPrice", "bid",
    "AskQty", "ask_qty", "BidQty", "bid_qty", "ask_qty_known", "bid_qty_known",
    "read_at", "ReadAt",
}


def producer_trace() -> dict:
    """Where the current watcher leaves the board, and what this writer will not add."""
    return {
        "watcher": "ms2_live/Kioxia_RSS_Live_Watcher.ps1",
        "audited_sidecar_commit": "ce2f43b66cbb138320da8813d90f59b8cb909da0",
        "latest_main_sha": "1243ef1dd7001d36b789c4855e0626e8e896cce5",
        "board_reader": "Read-BoardDepth",
        "board_reader_lines": "342-355",
        "board_call": "$board = @(Read-BoardDepth $rss)",
        "board_call_line": 602,
        "board_com_reads_per_poll": 40,
        "extra_com_reads_added_by_this_module": 0,
        "tick_writer": "Write-TickLogDiff",
        "tick_writer_lines": "276-307",
        "tick_call_line": 601,
        "gap_result_returned_to_caller": False,
        "loop_clock_line": 586,
        "loop_clock_format": "Get-Date with no numeric offset; tick CSV uses yyyy-MM-dd HH:mm:ss",
        "poll_sleep_line": 901,
        "stop_finally_lines": "903-906",
        "snapshot_atomic": False,
        "sidecar_writer_in_watcher": False,
    }


def watcher_integration_proposal() -> dict:
    """Future Windows edit. Not applied. Not an approval to edit the watcher."""
    return {
        "applied": WATCHER_INTEGRATION_APPLIED,
        "approval": "separate OWNER go-ahead required before any watcher edit",
        "default_enabled": False,
        "com_reads_added": 0,
        "autostart": False,
        "real_submit_allowed": False,
        "retries_inside_poll": 0,
        "blocking_lock": False,
        "shutoff_elapsed_ms": 50,
        "max_bytes": MAX_BYTES,
        "touch_points": [
            "Do not edit Read-BoardDepth. Reuse the list already returned at line 602.",
            "Do not edit Write-TickLogDiff in the same change. Its gap counts are local and are not available to pass in until a later approved return value exists.",
            "A later patch may call record_captured_observation in its own try after line 602 and before the B4 price read. Catch every failure and do not rethrow. Do not Start-Sleep and do not retry inside the 2-second poll.",
            "Stamp read_started_at and read_finished_at only with Get-Date calls wrapped around that existing Read-BoardDepth call. Those are local clocks, not a second board read. Omit them until that patch exists.",
            "Do not append +09:00 to the naive loop Get-Date. Pass watcher_observed_at only when a numeric offset was actually measured. Until then leave it null.",
            "Pass $script:tickPollSeq as poll_seq. Do not copy it into exchange_sequence.",
            "Keep the call out of the dashboard, audio, and sign try path so a full disk does not skip the price update.",
            "If writer elapsed_ms exceeds shutoff_elapsed_ms, or any writer status is BLOCKED, set a process-local flag off for the rest of the session.",
        ],
        "risks": [
            "fsync once per poll can stretch the 2-second loop on a busy disk. CPU of one JSON object is not the risk. Excel COM contention is unchanged only while no extra Value2 reads are added.",
            "Placing the write in the outer poll catch skips the rest of that cycle, including the sign, after a disk error.",
            "Inventing +09:00, available_at, or an exchange sequence would make later fill audits look ordered when they are not.",
            "Returning gap fields from Write-TickLogDiff is a watcher change and is outside this patch.",
        ],
        "stop_and_rollback": [
            "This patch has no watcher delta. Rollback is: do not deploy a watcher patch.",
            "If a later patch is live and COM errors, a frozen sign, or a poll gap appear: Ctrl+C the watcher console only. The existing finally sets RSS接続!B16 to 停止 and saves the workbook. Excel stays open.",
            "Do not Stop-Process Excel.",
            "Restore Kioxia_RSS_Live_Watcher.ps1 from main. Leave kioxia_ticks, kioxia_tick_diag, and 気配値ログ.csv in place. Do not delete them.",
            "A corrupt sidecar is left in place. Copy it aside under data/private/ms2_sidecar if a quarantine copy is needed. Do not append to it and do not delete tick or diagnostic logs to recover.",
        ],
        "windows_acceptance": [
            {"id": "W1", "status": "NOT_VERIFIED", "check": "Current watcher, sidecar flag absent. Private jsonl unchanged. Tick and board CSV headers unchanged. Dashboard price still updates."},
            {"id": "W2", "status": "NOT_VERIFIED", "check": "After a separate approval, off session, flag on. Record poll spacing, com_error_diag growth, and whether the existing 40 cell reads plus one fsync exceed the loop. Do not upload the private file."},
            {"id": "W3", "status": "NOT_VERIFIED", "check": "Ctrl+C. B16 becomes 停止. Excel stays up. Force-killing Excel is a failed stop."},
            {"id": "W4", "status": "NOT_VERIFIED", "check": "On COM errors, a frozen sign, a poll gap, or a sidecar exception: flag off, Ctrl+C, restore the audited watcher. Do not keep trading from a stale dashboard."},
        ],
        "durable_writer_owner_pc": "NOT_VERIFIED",
        "power_loss_durability": "NOT_VERIFIED",
        "durable_plan": "docs/MS2_WINDOWS_DURABLE_WRITER.md",
    }


def _safety_report() -> dict:
    return {
        "writer_version": WRITER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "pit_schema_version": PIT_SCHEMA_VERSION,
        "eligible_observed_n": 0,
        "synthetic_n": 0,
        "pit_count": 0,
        "pit_evidence_origin": None,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "rss_order_enabled": False,
        "autostart": False,
        "watcher_modified": False,
        "com_reads_added": 0,
        "legacy_history_modified": False,
        "closed_eligible": False,
        "exchange_order_proven": False,
        "snapshot_atomic_guaranteed": False,
        "expectancy_yen": None,
        "profit_factor": None,
        "max_drawdown_yen": None,
        "verified_net_pnl_yen": None,
        "remaining_to_10b_yen": None,
        "writes_performed": False,
        "bytes_written": 0,
        "file_sha256": None,
        "row_count": 0,
        "elapsed_ms": 0,
        "lock_wait_s": 0,
        "lock_backend": "windows-lockfileex" if os.name == "nt" else "posix-flock",
        "same_directory_replace": True,
        "crash_consistency": "PUBLISHED_BYTES_STABLE_UNTIL_REPLACE",
        "power_loss_durability": "NOT_VERIFIED",
        "directory_fsync": "WINDOWS_NOT_SUPPORTED" if os.name == "nt" else "POSIX_WHEN_REPLACE_SUCCEEDS",
        "live_watcher_connection": "P0_BLOCKED",
        "owner_pc_acceptance": "NOT_VERIFIED",
        "recovery_transitions": [],
    }


def _report(*, writer_status: str, contract_status: str, decision_state: str, close_state: str,
            transition: str, reasons: list[str], **extra) -> dict:
    payload = _safety_report()
    payload.update({
        "writer_status": writer_status,
        "contract_status": contract_status,
        "decision_state": decision_state,
        "close_state": close_state,
        "transition": transition,
        "reasons": sorted(set(reasons)),
    })
    payload.update(extra)
    payload["eligible_observed_n"] = 0
    payload["real_submit_allowed"] = False
    payload["promotion_eligible"] = False
    payload["statistical_edge_confirmed"] = False
    payload["closed_eligible"] = False
    payload["exchange_order_proven"] = False
    payload["snapshot_atomic_guaranteed"] = False
    payload["com_reads_added"] = 0
    payload["watcher_modified"] = False
    return payload


def _blocked(reasons: list[str], *, transition: str = "REFUSED") -> dict:
    return _report(
        writer_status="BLOCKED",
        contract_status="BLOCKED",
        decision_state="BLOCKED",
        close_state="NOT_CLOSED",
        transition=transition,
        reasons=reasons,
    )


def _offset_text(value: datetime) -> str | None:
    offset = value.utcoffset()
    if offset is None:
        return None
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if seconds != 0 or hours > 14:
        return None
    return f"{sign}{hours:02d}:{minutes:02d}"


def _canonical(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _parse_caller_clock(value, errors: list[str]) -> tuple[str | None, datetime | None]:
    if value is None:
        return None, None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z") or "JST" in text or "Tokyo" in text or "Japan" in text:
            errors.append("TIMEZONE_UNKNOWN")
            return None, None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            errors.append("TIMESTAMP_INVALID")
            return None, None
    else:
        errors.append("TIMESTAMP_INVALID")
        return None, None
    if parsed.tzinfo is None or parsed.utcoffset() is None or _offset_text(parsed) is None:
        errors.append("TIMEZONE_UNKNOWN")
        return None, None
    if parsed.microsecond % 1000 != 0:
        errors.append("SUBMILLISECOND_UNRECORDED")
        return None, None
    trimmed = parsed.replace(microsecond=(parsed.microsecond // 1000) * 1000)
    return trimmed.isoformat(timespec="milliseconds"), trimmed


def _delta_ms(later: datetime, earlier: datetime) -> int | None:
    delta = later - earlier
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    if micros % 1000 != 0:
        return None
    return micros // 1000


def _finite(value, *, positive: bool, errors: list[str], type_code: str, invalid_code: str | None = None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(type_code)
        return None
    if isinstance(value, float) and not math.isfinite(value):
        errors.append("NON_FINITE_REFUSED")
        return None
    if positive and value <= 0:
        errors.append(invalid_code or "BOOK_PRICE_INVALID")
        return None
    if not positive and value < 0:
        errors.append(invalid_code or "BOOK_QTY_NEGATIVE_REFUSED")
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _pick(payload: dict, keys: tuple[str, ...]):
    found = [(key, payload[key]) for key in keys if key in payload]
    return found


def _clock_block(capture: dict, errors: list[str]) -> dict:
    parsed: dict[str, datetime | None] = {}
    text: dict[str, str | None] = {}
    for name in ("event_time", "watcher_observed_at", "received_at", "available_at"):
        raw = capture.get(name)
        stamp, moment = _parse_caller_clock(raw, errors)
        text[name] = stamp
        parsed[name] = moment
    present = [item for item in parsed.values() if item is not None]
    offsets = {_offset_text(item) for item in present}
    timezone = capture.get("timezone")
    if timezone is not None and not isinstance(timezone, str):
        errors.append("TIMEZONE_UNKNOWN")
        timezone = None
    if isinstance(timezone, str) and (timezone in {"JST", "Asia/Tokyo"} or "Tokyo" in timezone or "Japan" in timezone):
        errors.append("TIMEZONE_UNKNOWN")
    if present:
        if len(offsets) != 1:
            errors.append("TIMEZONE_MISMATCH")
        else:
            only = next(iter(offsets))
            if timezone is None:
                timezone = only
            elif timezone != only:
                errors.append("TIMEZONE_MISMATCH")
    elif timezone is not None:
        errors.append("TIMEZONE_WITHOUT_TIMESTAMP")
        timezone = None
    named = [item for item in (parsed["event_time"], parsed["watcher_observed_at"], parsed["received_at"], parsed["available_at"]) if item is not None]
    for index, left in enumerate(named):
        for right in named[index + 1:]:
            if left == right:
                errors.append("CLOCKS_NOT_DISTINGUISHED")
    if text["event_time"] is None:
        event_basis = "ABSENT"
        if capture.get("event_time_basis") not in (None, "ABSENT"):
            errors.append("EVENT_TIME_BASIS_CONTRADICTION")
    else:
        event_basis = capture.get("event_time_basis")
        if event_basis != "EXCHANGE_SUPPLIED":
            errors.append("EVENT_TIME_BASIS_CONTRADICTION")
    if text["watcher_observed_at"] is None:
        watcher_basis = "ABSENT"
        clock_source = "UNKNOWN"
        clock_quality = "UNKNOWN"
        if capture.get("watcher_observed_at_basis") not in (None, "ABSENT"):
            errors.append("CLOCK_BASIS_CONTRADICTION")
        if capture.get("clock_quality") not in (None, "UNKNOWN"):
            errors.append("CLOCK_BASIS_CONTRADICTION")
    else:
        watcher_basis = "GET_DATE_LOCAL"
        clock_source = capture.get("clock_source", "OTHER_LOCAL")
        if clock_source not in {"WINDOWS_LOCAL", "OTHER_LOCAL"}:
            errors.append("CLOCK_BASIS_CONTRADICTION")
            clock_source = "OTHER_LOCAL"
        clock_quality = capture.get("clock_quality", "UNSYNCHRONIZED_LOCAL")
        if clock_quality == "NTP_ASSERTED":
            errors.append("CLOCK_QUALITY_UNPROVEN")
        elif clock_quality != "UNSYNCHRONIZED_LOCAL":
            errors.append("CLOCK_BASIS_CONTRADICTION")
    if text["received_at"] is None:
        received_basis = "NOT_SEPARATELY_EVIDENCED"
        if capture.get("received_at_basis") not in (None, "NOT_SEPARATELY_EVIDENCED"):
            errors.append("RECEIVED_AT_NOT_SEPARATE")
    else:
        received_basis = capture.get("received_at_basis")
        if received_basis != "SEPARATE_EVIDENCE":
            errors.append("RECEIVED_AT_NOT_SEPARATE")
    if text["available_at"] is None:
        available_basis = "NOT_DEMONSTRATED"
        if capture.get("available_at_basis") not in (None, "NOT_DEMONSTRATED"):
            errors.append("AVAILABLE_AT_BASIS_CONTRADICTION")
    else:
        available_basis = capture.get("available_at_basis")
        if available_basis != "DURABLE_CONSUMER_READ":
            errors.append("INVENTED_AVAILABLE_AT")
    if parsed["event_time"] is not None and parsed["watcher_observed_at"] is not None:
        age = _delta_ms(parsed["watcher_observed_at"], parsed["event_time"])
        if age is None or age <= 0:
            errors.append("TIME_ORDER_CONTRADICTION")
    if parsed["available_at"] is not None and parsed["watcher_observed_at"] is not None:
        gap = _delta_ms(parsed["available_at"], parsed["watcher_observed_at"])
        if gap is None or gap <= 0:
            errors.append("TIME_ORDER_CONTRADICTION")
    return {
        "text": text,
        "parsed": parsed,
        "timezone": timezone if present else None,
        "event_time_basis": event_basis,
        "watcher_observed_at_basis": watcher_basis,
        "clock_source": clock_source,
        "clock_quality": clock_quality,
        "received_at_basis": received_basis,
        "available_at_basis": available_basis,
    }


def _freshness(capture: dict, clocks: dict, errors: list[str]) -> tuple:
    freshness = capture.get("data_freshness", "UNKNOWN")
    if freshness not in {"OK", "STALE", "MISSING", "FUTURE", "UNKNOWN"}:
        errors.append("FRESHNESS_INVALID")
        freshness = "UNKNOWN"
    given_age = capture.get("quote_age_ms")
    bound = capture.get("freshness_bound_ms")
    if freshness != "OK":
        if given_age is not None or bound is not None:
            errors.append("FRESHNESS_CONTRADICTION")
        basis = {
            "STALE": "STALE_DECLARED",
            "MISSING": "MISSING_DECLARED",
            "FUTURE": "FUTURE_DECLARED",
            "UNKNOWN": "NOT_EVIDENCED",
        }[freshness]
        return freshness, basis, None, None
    event = clocks["parsed"]["event_time"]
    watcher = clocks["parsed"]["watcher_observed_at"]
    if event is None or watcher is None or not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0:
        errors.append("FRESHNESS_CONTRADICTION")
        return freshness, "EXCHANGE_AGE_WITHIN_BOUND", None, None
    measured = _delta_ms(watcher, event)
    if measured is None:
        errors.append("SUBMILLISECOND_UNRECORDED")
        return freshness, "EXCHANGE_AGE_WITHIN_BOUND", None, bound
    if given_age is not None and given_age != measured:
        errors.append("FRESHNESS_AGE_MISMATCH")
    if measured > bound:
        errors.append("FRESHNESS_BOUND_EXCEEDED")
    return freshness, "EXCHANGE_AGE_WITHIN_BOUND", measured, bound


def _sequence(capture: dict, errors: list[str]) -> tuple:
    poll = capture.get("poll_seq")
    if isinstance(poll, bool) or not isinstance(poll, int) or not 1 <= poll <= 10**12:
        errors.append("POLL_SEQ_INVALID")
        poll = None
    basis = capture.get("sequence_basis", "POLL")
    proven = capture.get("order_proven", False)
    sequence = capture.get("exchange_sequence", None)
    if basis not in {"POLL", "EXCHANGE", "UNKNOWN"}:
        errors.append("SEQUENCE_BASIS_INVALID")
    if not isinstance(proven, bool):
        errors.append("ORDER_PROVEN_INVALID")
    if sequence is not None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0 or sequence > 10**12:
            errors.append("EXCHANGE_SEQUENCE_INVALID")
        elif poll is not None and sequence == poll:
            errors.append("POLL_SEQ_REUSED_AS_EXCHANGE_SEQUENCE")
        if basis != "EXCHANGE":
            errors.append("EXCHANGE_SEQUENCE_PRESENT_ON_POLL")
    elif basis == "EXCHANGE":
        errors.append("EXCHANGE_SEQUENCE_ABSENT")
    if basis == "POLL" and proven is True:
        errors.append("POLL_ORDER_NOT_EXCHANGE_ORDER")
    if basis == "EXCHANGE" and proven is not True:
        errors.append("SEQUENCE_BASIS_CONTRADICTION")
    if basis == "UNKNOWN" and proven is True:
        errors.append("SEQUENCE_BASIS_CONTRADICTION")
    return poll, basis, proven if isinstance(proven, bool) else False, sequence


def _gap_components(payload: dict, errors: list[str]) -> tuple[bool | None, dict | None]:
    window = payload.get("window_size")
    overlap = payload.get("overlap_with_prev")
    prev = payload.get("prev_poll_nonempty")
    new = payload.get("new_appended")
    if (
        isinstance(window, bool) or not isinstance(window, int) or window < 0
        or isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0
        or not isinstance(prev, bool)
        or isinstance(new, bool) or not isinstance(new, int) or new < 0
        or overlap > window or new > window
    ):
        errors.append("GAP_DIAG_INVALID")
        return None, None
    return bool(prev is True and overlap == 0 and window > 0), {
        "window_size": window,
        "overlap_with_prev": overlap,
        "prev_poll_nonempty": prev,
        "new_appended": new,
    }


def _nested_gap(capture: dict, poll, errors: list[str]) -> tuple:
    if "gap" not in capture or capture.get("gap") is None:
        return None, "NOT_ATTACHED", None
    gap = capture.get("gap")
    if not isinstance(gap, dict) or not set(gap).issubset(_GAP_KEYS):
        errors.append("GAP_DIAG_INVALID")
        return None, "NOT_ATTACHED", None
    if "poll_seq" in gap and gap.get("poll_seq") != poll:
        errors.append("GAP_DIAG_INVALID")
    expected, parts = _gap_components(gap, errors)
    if parts is None:
        return None, "ATTACHED", None
    if "suspected_gap" in gap and gap.get("suspected_gap") is not expected:
        errors.append("GAP_FLAG_CONTRADICTION")
    parts["poll_seq"] = poll
    if set(parts) != GAP_DIAG_FIELDS:
        errors.append("GAP_DIAG_INVALID")
    return expected, "ATTACHED", parts


def _qty_cell(payload: dict, keys: tuple[str, ...], known_key: str, errors: list[str]) -> tuple[bool, object, bool]:
    found = _pick(payload, keys)
    if not found:
        if known_key in payload and payload.get(known_key) is not False:
            errors.append("BOOK_QTY_KNOWN_FLAG_CONTRADICTION")
        return False, None, False
    values = [item[1] for item in found]
    if any(item != values[0] for item in values[1:]):
        errors.append("BOOK_VALUE_TYPE_INVALID")
    raw = values[0]
    if raw is None:
        if known_key in payload and payload.get(known_key) is not False:
            errors.append("BOOK_QTY_KNOWN_FLAG_CONTRADICTION")
        return True, None, False
    number = _finite(raw, positive=False, errors=errors, type_code="BOOK_VALUE_TYPE_INVALID")
    if number is None:
        return True, None, False
    if known_key in payload and payload.get(known_key) is not True:
        errors.append("BOOK_QTY_KNOWN_FLAG_CONTRADICTION")
    return True, number, True


def _price_cell(payload: dict, keys: tuple[str, ...], errors: list[str]):
    found = _pick(payload, keys)
    if not found:
        return None
    values = [item[1] for item in found]
    if any(item != values[0] for item in values[1:]):
        errors.append("BOOK_VALUE_TYPE_INVALID")
        return None
    raw = values[0]
    if raw is None:
        return None
    return _finite(raw, positive=True, errors=errors, type_code="BOOK_VALUE_TYPE_INVALID")


def _levels(capture: dict, errors: list[str]) -> tuple[list[dict], bool]:
    raw_levels = capture.get("levels")
    if not isinstance(raw_levels, list):
        errors.append("BOARD_INPUT_INVALID")
        return [], False
    if len(raw_levels) > 10:
        errors.append("DEPTH_LIMIT")
        return [], False
    parsed = []
    qty_seen = False
    numbers = []
    moments = []
    for item in raw_levels:
        if not isinstance(item, dict) or not set(item).issubset(_LEVEL_KEYS):
            errors.append("LEVEL_INVALID")
            return [], False
        if "Level" in item and "level" in item and item["Level"] != item["level"]:
            errors.append("LEVEL_INVALID")
        if "Level" in item:
            number = item["Level"]
        elif "level" in item:
            number = item["level"]
        else:
            errors.append("LEVEL_NUMBER_ABSENT")
            number = None
        if isinstance(number, bool) or not isinstance(number, int):
            errors.append("LEVEL_NUMBER_ABSENT")
            number = None
        else:
            numbers.append(number)
        present_bid, bid_qty, bid_known = _qty_cell(item, ("BidQty", "bid_qty"), "bid_qty_known", errors)
        present_ask, ask_qty, ask_known = _qty_cell(item, ("AskQty", "ask_qty"), "ask_qty_known", errors)
        qty_seen = qty_seen or present_bid or present_ask
        read_raw = item.get("read_at", item.get("ReadAt"))
        read_text, read_moment = _parse_caller_clock(read_raw, errors) if read_raw is not None or "read_at" in item or "ReadAt" in item else (None, None)
        if read_raw is None and ("read_at" in item or "ReadAt" in item):
            read_text, read_moment = None, None
        level = {
            "level": number,
            "bid": _price_cell(item, ("BidPrice", "bid"), errors),
            "ask": _price_cell(item, ("AskPrice", "ask"), errors),
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "bid_qty_known": bid_known,
            "ask_qty_known": ask_known,
            "read_at": read_text,
        }
        if read_moment is not None:
            moments.append(read_moment)
        parsed.append(level)
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        errors.append("LEVEL_SEQUENCE_GAP")
    timed = [level["read_at"] for level in parsed if level["read_at"] is not None]
    if timed and len(timed) != len(parsed):
        errors.append("LEVEL_CLOCK_PARTIAL")
    if len(moments) == len(parsed) and len(moments) > 1:
        for earlier, later in zip(moments, moments[1:]):
            if later < earlier:
                errors.append("TIME_ORDER_CONTRADICTION")
                break
    return parsed, qty_seen


def _read_span(capture: dict, levels: list[dict], errors: list[str]) -> tuple:
    method = capture.get("read_method", "SEQUENTIAL_CELL")
    claimed_atomic = capture.get("snapshot_atomic")
    evidenced = capture.get("bulk_read_evidenced", False)
    if method == "SEQUENTIAL_CELL":
        if claimed_atomic is True:
            errors.append("SNAPSHOT_ATOMIC_CONTRADICTION")
        atomic = False
    elif method == "BULK_RANGE":
        if evidenced is not True:
            errors.append("BULK_READ_NOT_EVIDENCED")
        if claimed_atomic is False:
            errors.append("SNAPSHOT_ATOMIC_CONTRADICTION")
        atomic = True
    else:
        errors.append("SNAPSHOT_ATOMIC_CONTRADICTION")
        atomic = False
    explicit_start, _start_moment = _parse_caller_clock(capture.get("read_started_at"), errors) if "read_started_at" in capture else (None, None)
    explicit_finish, _finish_moment = _parse_caller_clock(capture.get("read_finished_at"), errors) if "read_finished_at" in capture else (None, None)
    if "read_started_at" in capture and capture.get("read_started_at") is None:
        explicit_start = None
    if "read_finished_at" in capture and capture.get("read_finished_at") is None:
        explicit_finish = None
    level_times = [level["read_at"] for level in levels if level.get("read_at")]
    if level_times and len(level_times) == len(levels) and levels:
        derived_start = min(level_times)
        derived_finish = max(level_times)
        if explicit_start is not None and explicit_start != derived_start:
            errors.append("SKEW_CONTRADICTION")
        if explicit_finish is not None and explicit_finish != derived_finish:
            errors.append("SKEW_CONTRADICTION")
        started, finished = derived_start, derived_finish
    elif (explicit_start is None) ^ (explicit_finish is None):
        errors.append("SKEW_CONTRADICTION")
        started, finished = explicit_start, explicit_finish
    else:
        started, finished = explicit_start, explicit_finish
    skew = None
    if started is not None and finished is not None:
        start_parsed = datetime.fromisoformat(started)
        finish_parsed = datetime.fromisoformat(finished)
        skew = _delta_ms(finish_parsed, start_parsed)
        if skew is None:
            errors.append("SUBMILLISECOND_UNRECORDED")
        elif skew < 0:
            errors.append("TIME_ORDER_CONTRADICTION")
        if method == "BULK_RANGE" and (skew != 0 or started != finished):
            errors.append("SNAPSHOT_ATOMIC_CONTRADICTION")
    elif capture.get("read_skew_ms") is not None:
        errors.append("SKEW_CONTRADICTION")
    return method if method in {"SEQUENTIAL_CELL", "BULK_RANGE"} else "SEQUENTIAL_CELL", atomic, started, finished, skew


def _optional_qty(capture: dict, key: str, errors: list[str]):
    if key not in capture or capture.get(key) is None:
        return None
    return _finite(capture.get(key), positive=False, errors=errors, type_code="BOOK_VALUE_TYPE_INVALID")


def _trade_and_tick(capture: dict, errors: list[str]) -> dict:
    price = capture.get("last_trade_price")
    qty = capture.get("last_trade_qty")
    if price is None and qty is None:
        trade_known = False
        trade_price = None
        trade_qty = None
    elif price is None or qty is None:
        errors.append("TRADE_PARTIAL")
        trade_known = False
        trade_price = None
        trade_qty = None
    else:
        trade_price = _finite(price, positive=True, errors=errors, type_code="BOOK_VALUE_TYPE_INVALID")
        trade_qty = _finite(qty, positive=False, errors=errors, type_code="BOOK_VALUE_TYPE_INVALID")
        trade_known = trade_price is not None and trade_qty is not None
    if "tick_size" not in capture or capture.get("tick_size") is None:
        tick = None
        tick_known = False
    else:
        tick = _finite(capture.get("tick_size"), positive=True, errors=errors, type_code="BOOK_VALUE_TYPE_INVALID")
        tick_known = tick is not None
    return {
        "last_trade_price": trade_price if trade_known else None,
        "last_trade_qty": trade_qty if trade_known else None,
        "last_trade_known": trade_known,
        "tick_size": tick if tick_known else None,
        "tick_size_known": tick_known,
    }


def _identity(capture: dict, kind: str, errors: list[str]) -> dict:
    symbol = capture.get("symbol")
    market = capture.get("market")
    if not isinstance(symbol, str) or not _NAME_RE.fullmatch(symbol):
        errors.append("SYMBOL_ABSENT")
        symbol = None
    if market not in {"TSE", "JNX"}:
        errors.append("MARKET_INVALID")
        market = None
    source = capture.get("source", SOURCE_DEFAULT)
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        errors.append("SOURCE_ABSENT")
    elif source == CURRENT_WATCHER_SOURCE:
        errors.append("WATCHER_SOURCE_HAS_NO_SIDECAR")
    if capture.get("capture_authenticated") not in (None, False):
        errors.append("CAPTURE_AUTHENTICATION_REFUSED")
    if "fill_missing_with_zero" in capture and capture.get("fill_missing_with_zero") is not False:
        errors.append("QTY_ZERO_FILL_REFUSED")
    window = capture.get("poll_window_ms", None)
    if window is not None and (isinstance(window, bool) or not isinstance(window, int) or window <= 0 or window > 60_000):
        errors.append("POLL_WINDOW_INVALID")
        window = None
    poll, basis, proven, sequence = _sequence(capture, errors)
    observation_id = capture.get("observation_id")
    if observation_id is None and symbol and market and poll is not None:
        prefix = {"BOARD_SNAPSHOT": "board", "TICK_PRINT": "tick", "GAP_DIAG": "gap"}[kind]
        observation_id = f"{prefix}-{market}-{symbol}-{poll}"
    if not isinstance(observation_id, str) or not _NAME_RE.fullmatch(observation_id):
        errors.append("OBSERVATION_ID_ABSENT")
    return {
        "observation_id": observation_id,
        "source": source if isinstance(source, str) else SOURCE_DEFAULT,
        "symbol": symbol,
        "market": market,
        "poll_seq": poll,
        "poll_seq_basis": "WATCHER_LOOP",
        "sequence_basis": basis,
        "order_proven": proven,
        "exchange_sequence": sequence,
        "poll_window_ms": window,
        "capture_authenticated": False,
    }


def _shared(capture: dict, kind: str, errors: list[str]) -> dict | None:
    if SAFETY_KEYS.intersection(capture):
        errors.append("SAFETY_FLAG_REFUSED")
    if SCHEMA_VERSION != "ms2-watcher-sidecar-0.1":
        errors.append("SCHEMA_VERSION_UNKNOWN")
    identity = _identity(capture, kind, errors)
    clocks = _clock_block(capture, errors)
    freshness, freshness_basis, age, bound = _freshness(capture, clocks, errors)
    record = {
        "schema_version": SCHEMA_VERSION,
        **identity,
        "kind": kind,
        "event_time": clocks["text"]["event_time"],
        "event_time_basis": clocks["event_time_basis"],
        "watcher_observed_at": clocks["text"]["watcher_observed_at"],
        "watcher_observed_at_basis": clocks["watcher_observed_at_basis"],
        "clock_source": clocks["clock_source"],
        "clock_quality": clocks["clock_quality"],
        "timezone": clocks["timezone"],
        "received_at": clocks["text"]["received_at"],
        "received_at_basis": clocks["received_at_basis"],
        "available_at": clocks["text"]["available_at"],
        "available_at_basis": clocks["available_at_basis"],
        "data_freshness": freshness,
        "freshness_basis": freshness_basis,
        "quote_age_ms": age,
        "freshness_bound_ms": bound,
    }
    return record


def _reject_unknown(capture: dict, allowed: set[str], errors: list[str]) -> None:
    extra = set(capture) - allowed - SAFETY_KEYS
    if extra:
        errors.append("UNKNOWN_CAPTURE_FIELD")


def build_captured_record(capture: dict) -> dict:
    """Map one in-memory capture to a sidecar object. This does not touch disk or Excel."""
    errors: list[str] = []
    if not isinstance(capture, dict):
        return {"ok": False, "record": None, "reasons": ["BOARD_INPUT_INVALID"]}
    kind = capture.get("kind", "BOARD_SNAPSHOT")
    if kind not in _KINDS:
        errors.append("KIND_INVALID")
        kind = "BOARD_SNAPSHOT"
    allowed = {"BOARD_SNAPSHOT": _CAPTURE_BOARD, "TICK_PRINT": _CAPTURE_TICK, "GAP_DIAG": _CAPTURE_GAP}[kind]
    _reject_unknown(capture, allowed, errors)
    shared = _shared(capture, kind, errors)
    if kind == "BOARD_SNAPSHOT":
        levels, qty_seen = _levels(capture, errors)
        method, atomic, started, finished, skew = _read_span(capture, levels, errors)
        suspected, evidence, diag = _nested_gap(capture, shared["poll_seq"] if shared else None, errors)
        top = {
            "bid": levels[0]["bid"] if levels else None,
            "ask": levels[0]["ask"] if levels else None,
            "bid_qty": levels[0]["bid_qty"] if levels else None,
            "ask_qty": levels[0]["ask_qty"] if levels else None,
            "bid_qty_known": levels[0]["bid_qty_known"] if levels else False,
            "ask_qty_known": levels[0]["ask_qty_known"] if levels else False,
        }
        record = {
            **shared,
            "snapshot_atomic": atomic,
            "read_method": method,
            "read_started_at": started,
            "read_finished_at": finished,
            "read_skew_ms": skew,
            "suspected_gap": suspected,
            "gap_evidence": evidence,
            "gap_diag": diag,
            "book_qty_source": "RSS_LEVEL_QTY" if qty_seen else "UNKNOWN",
            "top": top,
            "levels": [{key: level[key] for key in ("level", "bid", "ask", "bid_qty", "ask_qty", "bid_qty_known", "ask_qty_known", "read_at")} for level in levels],
            "depth_claimed": len(levels),
            "over_qty": _optional_qty(capture, "over_qty", errors),
            "under_qty": _optional_qty(capture, "under_qty", errors),
            **_trade_and_tick(capture, errors),
        }
        if levels and set(record["levels"][0]) != LEVEL_FIELDS:
            errors.append("LEVEL_INVALID")
        if set(top) != TOP_FIELDS:
            errors.append("BOOK_SHAPE_INVALID")
    elif kind == "TICK_PRINT":
        if capture.get("read_method") not in (None, "NOT_APPLICABLE") or capture.get("snapshot_atomic") not in (None,):
            errors.append("PRINT_IS_NOT_A_QUOTE")
        if any(capture.get(key) is not None for key in ("read_started_at", "read_finished_at", "read_skew_ms")):
            errors.append("PRINT_IS_NOT_A_QUOTE")
        price = capture.get("price")
        volume = capture.get("volume")
        if price is None:
            price_out = None
        else:
            price_out = _finite(price, positive=True, errors=errors, type_code="PRICE_INVALID", invalid_code="PRICE_INVALID")
        if volume is None:
            volume_out = None
        else:
            volume_out = _finite(volume, positive=True, errors=errors, type_code="VOLUME_INVALID", invalid_code="VOLUME_INVALID")
        suspected, evidence, diag = _nested_gap(capture, shared["poll_seq"] if shared else None, errors)
        record = {
            **shared,
            "snapshot_atomic": None,
            "read_method": "NOT_APPLICABLE",
            "read_started_at": None,
            "read_finished_at": None,
            "read_skew_ms": None,
            "suspected_gap": suspected,
            "gap_evidence": evidence,
            "gap_diag": diag,
            "price": price_out,
            "volume": volume_out,
        }
    else:
        expected, parts = _gap_components(capture, errors)
        if "suspected_gap" in capture and parts is not None and capture.get("suspected_gap") is not expected:
            errors.append("GAP_FLAG_CONTRADICTION")
        if capture.get("read_method") not in (None, "NOT_APPLICABLE"):
            errors.append("SNAPSHOT_ATOMIC_CONTRADICTION")
        record = {
            **shared,
            "read_method": "NOT_APPLICABLE",
            "suspected_gap": expected,
            "gap_evidence": "ATTACHED",
            "window_size": None if parts is None else parts["window_size"],
            "overlap_with_prev": None if parts is None else parts["overlap_with_prev"],
            "prev_poll_nonempty": None if parts is None else parts["prev_poll_nonempty"],
            "new_appended": None if parts is None else parts["new_appended"],
        }
    if record.get("kind") == "BOARD_SNAPSHOT" and set(record) != BOARD_FIELDS:
        errors.append("MISSING_FIELD")
    if record.get("kind") == "TICK_PRINT" and set(record) != TICK_FIELDS:
        errors.append("MISSING_FIELD")
    if record.get("kind") == "GAP_DIAG" and set(record) != GAP_FIELDS:
        errors.append("MISSING_FIELD")
    if errors:
        return {"ok": False, "record": None, "reasons": sorted(set(errors))}
    checked = validate_record(record)
    if checked["reject"]:
        return {"ok": False, "record": None, "reasons": checked["reject"]}
    return {"ok": True, "record": record, "reasons": checked["incomplete"]}


def _is_reparse(path: Path) -> bool:
    """True for a symlink, a Windows junction, or any other reparse point."""
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
    except OSError:
        return True
    if os.name != "nt":
        return False
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_write_path(repo_root, relative: str) -> Path:
    """Resolve a new or existing jsonl path under data/private/ms2_sidecar."""
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or "\\" in relative:
        raise ValueError("PRIVATE_PATH_INVALID")
    parts = Path(relative).parts
    if ".." in parts or parts[:3] != PRIVATE_PARTS or len(parts) != 4 or not _FILE_RE.fullmatch(parts[3]):
        raise ValueError("PRIVATE_PATH_INVALID")
    root = Path(repo_root).resolve()
    current = root
    for part in parts[:-1]:
        current = current / part
        if _is_reparse(current):
            raise ValueError("PRIVATE_PATH_LINK")
        if current.exists() and not current.is_dir():
            raise ValueError("PRIVATE_PATH_INVALID")
    target = current / parts[-1]
    if _is_reparse(target):
        raise ValueError("PRIVATE_PATH_LINK")
    allowed = (root / "data" / "private" / "ms2_sidecar").resolve()
    if _is_reparse(target.parent) or target.parent.resolve() != allowed:
        raise ValueError("PRIVATE_PATH_INVALID")
    return target


def _io_reason(exc: OSError) -> str:
    winerror = getattr(exc, "winerror", None)
    # 32/33 are sharing and lock violations. Replace of a file another handle
    # still has open is often access denied (5) rather than 32.
    if winerror in {32, 33} or (type(exc) is _ReplaceFailed and winerror == 5):
        return "WINDOWS_SHARING_VIOLATION"
    if isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
        return "WRITE_FAILED"
    if exc.errno == errno.ENOSPC:
        return "DISK_FULL"
    return "WRITE_FAILED"


class _ReadbackMismatch(Exception):
    def __init__(self, published: bool = False):
        super().__init__("readback mismatch")
        self.published = published


class _PublishOutcomeUnknown(OSError):
    """The replace may have published the new bytes, but that is not proven.

    Never reported as a refusal: the caller leaves it for independent readback.
    """

    def __init__(self, detail: str):
        super().__init__(errno.EIO, detail)


class _ReplaceFailed(OSError):
    """The published file was not replaced. Its previous bytes stay in place."""

    def __init__(self, exc: OSError):
        super().__init__(exc.errno or 0, exc.strerror or "replace failed")
        self.winerror = getattr(exc, "winerror", None)


# POSIX flock operation bits. Injected hooks still receive these values.
_FLOCK_EX_NB = 2 | 4
_FLOCK_UN = 8


def _lock_windows(fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped),
    ]
    kernel.LockFileEx.restype = wintypes.BOOL
    overlapped = _Overlapped()
    exclusive_now = 0x00000002 | 0x00000001
    held = kernel.LockFileEx(msvcrt.get_osfhandle(fd), exclusive_now, 0, 1, 0, ctypes.byref(overlapped))
    if held:
        return
    error = ctypes.get_last_error()
    if error in {32, 33}:
        raise BlockingIOError(errno.EAGAIN, "writer lock held")
    raised = OSError(error, "LockFileEx failed")
    raised.winerror = error
    raise raised


def _unlock_windows(fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = [
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.UnlockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(_Overlapped),
    ]
    kernel.UnlockFileEx.restype = wintypes.BOOL
    overlapped = _Overlapped()
    kernel.UnlockFileEx(msvcrt.get_osfhandle(fd), 0, 1, 0, ctypes.byref(overlapped))


def _lock_native(fd: int) -> None:
    if os.name == "nt":
        _lock_windows(fd)
        return
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_native(fd: int) -> None:
    if os.name == "nt":
        _unlock_windows(fd)
        return
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_UN)


def _fsync_directory(directory: Path) -> str:
    """Persist the directory entry after replace when the platform allows it.

    Windows exposes file flush, not this directory flush. Either result is
    still short of a proven power-loss guarantee.
    """
    if os.name == "nt":
        return "WINDOWS_NOT_SUPPORTED"
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return "POSIX_FSYNC"


# Windows FileRenameInfoEx flags and the errors that mean "not supported here".
_FILE_RENAME_INFO_EX = 22
_RENAME_REPLACE_IF_EXISTS = 0x1
_RENAME_POSIX_SEMANTICS = 0x2
_RENAME_UNSUPPORTED = frozenset({1, 50, 87})  # INVALID_FUNCTION, NOT_SUPPORTED, INVALID_PARAMETER


def _win_kernel():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _posix_rename_win(src, dst) -> int:
    """Rename ``src`` over ``dst`` with POSIX semantics. Returns 0 or a Win32 error.

    Readers that opened ``dst`` sharing delete keep reading the complete old
    file; readers that refuse delete sharing make this fail (32), unchanged.
    """
    import ctypes
    from ctypes import wintypes

    class _FileRenameInfo(ctypes.Structure):
        # union { BOOLEAN ReplaceIfExists; DWORD Flags; } is DWORD-sized.
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    kernel = _win_kernel()
    delete, synchronize = 0x00010000, 0x00100000
    share_all = 0x1 | 0x2 | 0x4
    open_existing, open_reparse_point = 3, 0x00200000
    handle = kernel.CreateFileW(
        os.fspath(src), delete | synchronize, share_all, None, open_existing, open_reparse_point, None,
    )
    if handle is None or handle == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error() or 5
    try:
        name = os.path.abspath(os.fspath(dst))
        encoded = name.encode("utf-16-le")
        offset = _FileRenameInfo.FileName.offset
        size = max(ctypes.sizeof(_FileRenameInfo), offset + len(encoded) + 2)
        buffer = (ctypes.c_byte * size)()
        info = _FileRenameInfo.from_buffer(buffer)
        info.Flags = _RENAME_REPLACE_IF_EXISTS | _RENAME_POSIX_SEMANTICS
        info.RootDirectory = None
        info.FileNameLength = len(encoded)  # bytes, without the terminator
        ctypes.memmove(ctypes.addressof(buffer) + offset, encoded, len(encoded))
        if kernel.SetFileInformationByHandle(handle, _FILE_RENAME_INFO_EX, buffer, size):
            return 0
        return ctypes.get_last_error() or 5
    finally:
        kernel.CloseHandle(handle)


def _file_identity(item) -> tuple | None:
    try:
        st = os.stat(item, follow_symlinks=False)
    except FileNotFoundError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


def _posix_rename_unsupported(directory: Path) -> bool:
    """Confirm on two private probe files that POSIX rename is unsupported here."""
    stem = directory / f".posix-rename-probe.{os.getpid()}.{time.time_ns()}"
    first, second = Path(f"{stem}.a"), Path(f"{stem}.b")
    try:
        for item in (first, second):
            fd = os.open(item, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            os.close(fd)
        return _posix_rename_win(first, second) in _RENAME_UNSUPPORTED
    except OSError:
        return False
    finally:
        for item in (first, second):
            try:
                os.unlink(item)
            except OSError:
                pass


def _replace_published(src, dst) -> str:
    """Atomically replace ``dst`` with the fsynced same-directory temp ``src``.

    POSIX: os.replace, unchanged. Windows: os.replace refuses any destination
    that a reader holds open, even with delete sharing, so POSIX-semantics
    rename is used. Only a proven-unsupported rename whose first attempt left
    both files untouched falls back to os.replace. Every other error raises.
    """
    if os.name != "nt":
        os.replace(src, dst)
        return "OS_REPLACE"
    src_before, dst_before = _file_identity(src), _file_identity(dst)
    error = _posix_rename_win(src, dst)
    if error == 0:
        return "POSIX_RENAME"
    untouched = (src_before is not None and _file_identity(src) == src_before
                 and _file_identity(dst) == dst_before)
    if not untouched:
        raise _PublishOutcomeUnknown(f"POSIX_RENAME_ERROR_{error}_OUTCOME_UNPROVEN")
    if error in _RENAME_UNSUPPORTED and _posix_rename_unsupported(Path(dst).parent):
        os.replace(src, dst)
        return "OS_REPLACE_POSIX_UNSUPPORTED"
    raised = OSError(errno.EACCES if error in {5, 32, 33} else errno.EIO, f"POSIX rename failed ({error})")
    raised.winerror = error
    raise raised


def _atomic_write(path: Path, payload: bytes, hooks: dict) -> dict:
    """Write a temp file beside ``path`` and replace only after read-back.

    The temp name stays in the same directory, so the replace does not cross
    a volume. On Windows a destination opened without sharing for delete
    makes the replace fail and the previous published bytes remain.
    """
    open_fn = hooks.get("open", os.open)
    write_fn = hooks.get("write", os.write)
    fsync_fn = hooks.get("fsync", os.fsync)
    close_fn = hooks.get("close", os.close)
    replace_fn = hooks.get("replace", _replace_published)
    unlink_fn = hooks.get("unlink", os.unlink)
    read_fn = hooks.get("read", lambda item: Path(item).read_bytes())
    chmod_fn = hooks.get("chmod", os.chmod)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    info = {"directory_fsync": "SKIPPED", "same_directory_temp": True}
    fd = None
    try:
        fd = open_fn(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        remaining = payload
        while remaining:
            written = write_fn(fd, remaining)
            if not isinstance(written, int):
                break
            if written <= 0:
                raise OSError(errno.EIO, "short write")
            remaining = remaining[written:]
        fsync_fn(fd)
    except Exception:
        if fd is not None:
            try:
                close_fn(fd)
            except Exception:
                pass
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise
    try:
        close_fn(fd)
    except Exception:
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise
    try:
        written_back = read_fn(tmp)
    except Exception:
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise
    if written_back != payload:
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise _ReadbackMismatch()
    try:
        method = replace_fn(tmp, path)
    except _PublishOutcomeUnknown:
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise
    except OSError as exc:
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise _ReplaceFailed(exc) from exc
    except Exception:
        try:
            unlink_fn(tmp)
        except Exception:
            pass
        raise
    info["replace_method"] = method if isinstance(method, str) else "HOOK"
    # From here the new bytes may be published. A failure is not a refusal.
    try:
        try:
            chmod_fn(path, 0o600)
        except OSError:
            if os.name != "nt":
                raise
        published = read_fn(path)
    except Exception as exc:
        raise _PublishOutcomeUnknown("POST_REPLACE_READBACK_FAILED") from exc
    if published != payload:
        raise _ReadbackMismatch(published=True)
    try:
        info["directory_fsync"] = _fsync_directory(path.parent)
    except OSError:
        info["directory_fsync"] = "DIRECTORY_FSYNC_FAILED"
    return info


def _acquire_lock(directory: Path, hooks: dict) -> int:
    """Take the writer lock or fail at once. This call does not wait."""
    open_fn = hooks.get("open", os.open)
    close_fn = hooks.get("close", os.close)
    fd = open_fn(directory / LOCK_NAME, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if "flock" in hooks:
            hooks["flock"](fd, _FLOCK_EX_NB)
        else:
            _lock_native(fd)
    except BlockingIOError:
        close_fn(fd)
        raise
    return fd


def _release_lock(fd: int, hooks: dict) -> None:
    close_fn = hooks.get("close", os.close)
    try:
        if "flock" in hooks:
            hooks["flock"](fd, _FLOCK_UN)
        else:
            _unlock_native(fd)
    except OSError:
        pass
    close_fn(fd)


class exclusive_writer_lock:
    """Hold the single writer lock until the block exits. Tests use this."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.fd = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fd = _acquire_lock(self.directory, {})
        return self

    def __exit__(self, *_args):
        if self.fd is not None:
            _release_lock(self.fd, {})
            self.fd = None
        return False


def _recovery_path(path: Path) -> Path:
    return path.parent / f".{path.name}.recovery.jsonl"


def _temp_names(path: Path) -> list[Path]:
    prefix = f".{path.name}."
    found = []
    if not path.parent.exists():
        return found
    for item in path.parent.iterdir():
        if item.name.startswith(prefix) and item.name.endswith(".tmp"):
            found.append(item)
    return found


def _append_recovery(path: Path, events: list[dict]) -> None:
    """Record quarantine or refusal. This file is not an observation JSONL."""
    if not events:
        return
    journal = _recovery_path(path)
    if _is_reparse(journal):
        raise OSError(errno.EPERM, "recovery reparse")
    quarantine = path.parent / f".{path.name}.quarantine"
    journal_prefix = f".{journal.name}."
    if path.parent.exists():
        for item in list(path.parent.iterdir()):
            if not (item.name.startswith(journal_prefix) and item.name.endswith(".tmp")):
                continue
            if _is_reparse(item) or not item.is_file():
                raise OSError(errno.EPERM, "recovery temp reparse")
            if quarantine.exists() and (_is_reparse(quarantine) or not quarantine.is_dir()):
                raise OSError(errno.EPERM, "quarantine reparse")
            quarantine.mkdir(exist_ok=True)
            os.replace(item, quarantine / f"{time.time_ns()}-{item.name}")
            events = [
                {"transition": "QUARANTINED_PARTIAL", "reason": "RECOVERY_TEMP_LEFTOVER", "repaired": False},
                *events,
            ]
    existing = b""
    if journal.exists() and not _is_reparse(journal):
        existing = journal.read_bytes()
        if existing and not existing.endswith(b"\n"):
            quarantine = path.parent / f".{path.name}.quarantine"
            if _is_reparse(quarantine):
                raise OSError(errno.EPERM, "quarantine reparse")
            quarantine.mkdir(exist_ok=True)
            os.replace(journal, quarantine / f"{time.time_ns()}-recovery-partial")
            existing = b""
            events = [
                {"transition": "RECOVERY_LOG_QUARANTINED", "reason": "PARTIAL_RECOVERY_LOG", "repaired": False},
                *events,
            ]
    body = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in events
    )
    _atomic_write(journal, existing + body.encode("utf-8"), {})


def _quarantine_partials(path: Path) -> list[dict]:
    """Move leftover temp files aside. Do not merge them into the published file."""
    leftovers = _temp_names(path)
    if not leftovers:
        return []
    quarantine = path.parent / f".{path.name}.quarantine"
    if quarantine.exists() and (_is_reparse(quarantine) or not quarantine.is_dir()):
        raise OSError(errno.EPERM, "quarantine reparse")
    events = []
    published = b""
    if path.exists() and not _is_reparse(path) and path.is_file():
        published = path.read_bytes()
    digest = hashlib.sha256(published).hexdigest()
    quarantine.mkdir(exist_ok=True)
    for item in leftovers:
        if _is_reparse(item) or not item.is_file():
            raise OSError(errno.EPERM, "temp reparse")
        dest = quarantine / f"{time.time_ns()}-{item.name}"
        os.replace(item, dest)
        events.append({
            "transition": "QUARANTINED_PARTIAL",
            "reason": "TEMP_LEFTOVER",
            "repaired": False,
            "published_sha256": digest,
            "published_bytes": len(published),
            "quarantine_name": dest.name,
        })
    _append_recovery(path, events)
    return events


def _parse_existing(raw: bytes) -> list[dict] | None:
    if not raw.endswith(b"\n"):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    records = []
    for line in text.splitlines():
        if not line:
            return None
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(item, dict):
            return None
        records.append(item)
    return records


def _from_audit(audit: dict, *, writer_status: str, transition: str, reasons: list[str],
                writes_performed: bool, payload: bytes) -> dict:
    return _report(
        writer_status=writer_status,
        contract_status=audit["contract_status"],
        decision_state=audit["decision_state"],
        close_state=audit["close_state"],
        transition=transition,
        reasons=reasons,
        writes_performed=writes_performed,
        bytes_written=len(payload) if writes_performed else 0,
        file_sha256=hashlib.sha256(payload).hexdigest(),
        row_count=audit.get("row_count", 0),
        synthetic_n=audit.get("synthetic_n", 0),
        pit_count=audit.get("synthetic_n", 0),
        pit_evidence_origin=audit.get("pit_evidence_origin"),
    )


def _record(repo_root, relative, capture, *, enabled: bool, hooks: dict) -> dict:
    if enabled is not True or relative is None or relative == "":
        return _report(
            writer_status="DISABLED",
            contract_status="NOT_READ",
            decision_state="DISABLED",
            close_state="DISABLED",
            transition="DISABLED",
            reasons=["SIDECAR_DISABLED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"],
        )
    try:
        path = resolve_write_path(repo_root, relative)
    except ValueError as exc:
        code = str(exc) if str(exc) in _PATH_CODES else "PRIVATE_PATH_INVALID"
        return _blocked([code, "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"])
    except OSError as exc:
        return _blocked([_io_reason(exc), "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"])
    built = build_captured_record(capture)
    if not built["ok"]:
        return _blocked([*built["reasons"], "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN", "CAPTURE_NOT_AUTHENTICATED"])
    record = built["record"]
    line = (_canonical(record) + "\n").encode("utf-8")
    makedirs = hooks.get("makedirs", os.makedirs)
    try:
        makedirs(path.parent, exist_ok=True)
        fd = _acquire_lock(path.parent, hooks)
    except BlockingIOError:
        return _blocked(["WRITE_LOCKED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN", "CAPTURE_NOT_AUTHENTICATED"])
    except OSError as exc:
        return _blocked([_io_reason(exc), "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN", "CAPTURE_NOT_AUTHENTICATED"])
    recovery: list[dict] = []
    try:
        try:
            recovery = _quarantine_partials(path)
        except OSError as exc:
            report = _blocked([
                _io_reason(exc), "TEMP_LEFTOVER", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN",
            ])
            report["recovery_transitions"] = list(recovery)
            return report

        def finish(report: dict) -> dict:
            report["recovery_transitions"] = list(recovery)
            return report

        existing = path.read_bytes() if path.exists() else b""
        if existing:
            if len(existing) > MAX_BYTES or len(existing) + len(line) > MAX_BYTES:
                return finish(_blocked(["PRIVATE_FILE_TOO_LARGE", "EXISTING_FILE_PRESERVED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
            prior = audit_sidecar_bytes(existing)
            if prior["contract_status"] == "BLOCKED":
                reason = "DATA_CORRUPT" if "DATA_CORRUPT" in prior["reasons"] else "EXISTING_FILE_PRESERVED"
                event = {
                    "transition": "CORRUPT_PRESERVED" if reason == "DATA_CORRUPT" else "BLOCKED_PRESERVED",
                    "reason": reason,
                    "repaired": False,
                    "published_bytes": len(existing),
                    "published_sha256": hashlib.sha256(existing).hexdigest(),
                }
                try:
                    _append_recovery(path, [event])
                    recovery = [*recovery, event]
                except OSError:
                    pass
                return finish(_blocked([*prior["reasons"], "EXISTING_FILE_PRESERVED"]))
            parsed = _parse_existing(existing)
            if parsed is None:
                event = {
                    "transition": "CORRUPT_PRESERVED",
                    "reason": "DATA_CORRUPT",
                    "repaired": False,
                    "published_bytes": len(existing),
                    "published_sha256": hashlib.sha256(existing).hexdigest(),
                }
                try:
                    _append_recovery(path, [event])
                    recovery = [*recovery, event]
                except OSError:
                    pass
                return finish(_blocked(["DATA_CORRUPT", "EXISTING_FILE_PRESERVED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
            token = _canonical(record)
            for item in parsed:
                if _canonical(item) == token:
                    return finish(_from_audit(
                        prior, writer_status="IDEMPOTENT", transition="REPLAY",
                        reasons=[*prior["reasons"], "IDEMPOTENT_REPLAY"],
                        writes_performed=False, payload=existing,
                    ))
                if item.get("observation_id") == record.get("observation_id"):
                    return finish(_blocked(["DUPLICATE_CONFLICT", "NOT_APPENDED", "EXISTING_FILE_PRESERVED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
                if (item.get("symbol"), item.get("market"), item.get("kind"), item.get("poll_seq")) == (
                    record.get("symbol"), record.get("market"), record.get("kind"), record.get("poll_seq")
                ):
                    return finish(_blocked(["DUPLICATE_POLL", "NOT_APPENDED", "EXISTING_FILE_PRESERVED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
            candidate = existing + line
        else:
            if len(line) > MAX_BYTES:
                return finish(_blocked(["PRIVATE_FILE_TOO_LARGE", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
            candidate = line
        preview = audit_sidecar_bytes(candidate)
        if preview["contract_status"] not in {"ADMITTED_INCOMPLETE", "PROJECTABLE_SYNTHETIC"}:
            return finish(_blocked([*preview["reasons"], "NOT_APPENDED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
        previous = existing if existing else None
        try:
            info = _atomic_write(path, candidate, hooks)
        except _ReadbackMismatch as exc:
            if not _restore(path, previous, hooks) and exc.published:
                return finish(_unverified("READBACK_MISMATCH", "RESTORE_FAILED"))
            return finish(_blocked(["READBACK_MISMATCH", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
        except _PublishOutcomeUnknown:
            return finish(_unverified())
        except _ReplaceFailed as exc:
            return finish(_blocked([
                _io_reason(exc), "REPLACE_FAILED", "ELIGIBLE_OBSERVED_N_ZERO",
                "ECONOMICS_UNKNOWN", "CAPTURE_NOT_AUTHENTICATED",
            ]))
        except OSError as exc:
            return finish(_blocked([
                _io_reason(exc), "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN", "CAPTURE_NOT_AUTHENTICATED",
            ]))
        try:
            final = path.read_bytes()
        except OSError:
            return finish(_unverified())
        if final != candidate:
            if not _restore(path, previous, hooks):
                return finish(_unverified("READBACK_MISMATCH", "RESTORE_FAILED"))
            return finish(_blocked(["READBACK_MISMATCH", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
        confirmed = audit_sidecar_bytes(final)
        if confirmed["contract_status"] != preview["contract_status"]:
            _restore(path, previous, hooks)
            return finish(_blocked(["READBACK_MISMATCH", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"]))
        report = _from_audit(
            confirmed,
            writer_status=confirmed["contract_status"],
            transition="APPENDED",
            reasons=[*confirmed["reasons"], "WRITER_APPENDED"],
            writes_performed=True,
            payload=final,
        )
        report["directory_fsync"] = info.get("directory_fsync", report["directory_fsync"])
        report["replace_method"] = info.get("replace_method", "UNKNOWN")
        report["recovery_transitions"] = recovery
        if existing and final[:len(existing)] != existing:
            report["reasons"] = sorted(set(report["reasons"]) | {"PUBLISHED_PREFIX_LOST"})
        return report
    finally:
        _release_lock(fd, hooks)


def _restore(path: Path, previous: bytes | None, hooks: dict) -> bool:
    """Put back the previous bytes after a proven mismatch. False when not done."""
    try:
        if previous is None:
            if path.exists():
                path.unlink()
            return True
        direct = {key: value for key, value in hooks.items() if key not in {"read", "write", "replace", "open"}}
        _atomic_write(path, previous, direct)
        return True
    except Exception:
        return False


def _unverified(*extra: str) -> dict:
    """The new bytes may be published; only independent readback can tell."""
    return _blocked([*extra, "PUBLISHED_UNVERIFIED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"],
                    transition="PUBLISH_UNVERIFIED")


def record_captured_observation(repo_root, relative, capture=None, *, enabled: bool = False, hooks=None) -> dict:
    """Append one captured observation, or write nothing when disabled.

    ``enabled`` must be exactly True. The default call does not create a
    directory and does not read Excel. Disk, lock, and validation failures
    are returned as reason codes.
    """
    started = time.perf_counter()
    try:
        report = _record(repo_root, relative, capture, enabled=enabled, hooks=dict(hooks or {}))
    except Exception:
        report = _blocked(["WRITER_EXCEPTION", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"], transition="ISOLATED")
    report["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    report["com_reads_added"] = 0
    report["watcher_modified"] = False
    report["real_submit_allowed"] = False
    report["promotion_eligible"] = False
    report["statistical_edge_confirmed"] = False
    report["closed_eligible"] = False
    report["eligible_observed_n"] = 0
    report["exchange_order_proven"] = False
    report["snapshot_atomic_guaranteed"] = False
    report["power_loss_durability"] = "NOT_VERIFIED"
    report["live_watcher_connection"] = "P0_BLOCKED"
    report["owner_pc_acceptance"] = "NOT_VERIFIED"
    report["lock_wait_s"] = 0
    if hooks and "flock" in hooks:
        report["lock_backend"] = "injected-flock"
    if "ECONOMICS_UNKNOWN" not in report["reasons"] or "ELIGIBLE_OBSERVED_N_ZERO" not in report["reasons"]:
        report["reasons"] = sorted(set(report["reasons"]) | {"ECONOMICS_UNKNOWN", "ELIGIBLE_OBSERVED_N_ZERO"})
    return report


def persist_bridge_record(repo_root, relative, blob: bytes, *, enabled: bool = False, hooks=None) -> dict:
    """Persist one already packed 2048-byte bridge record.

    This does not open shared memory, a pipe, Excel, or the live watcher.
    The handoff worker still imports ``fcntl`` and is not started here.
    """
    if enabled is not True:
        report = record_captured_observation(repo_root, relative, None, enabled=False, hooks=hooks)
        report["bridge_format"] = "NBH1-2048"
        report["watcher_io"] = False
        report["handoff_worker"] = "NOT_STARTED"
        return report
    from scripts.ms2_bridge_record import RECORD_SIZE, unpack_capture

    if not isinstance(blob, (bytes, bytearray)) or len(blob) != RECORD_SIZE:
        report = _blocked(["BRIDGE_RECORD_REFUSED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"])
        report["bridge_format"] = "NBH1-2048"
        report["watcher_io"] = False
        report["handoff_worker"] = "NOT_STARTED"
        return report
    capture = unpack_capture(bytes(blob))
    if not isinstance(capture, dict):
        report = _blocked(["BRIDGE_RECORD_REFUSED", "ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"])
        report["bridge_format"] = "NBH1-2048"
        report["watcher_io"] = False
        report["handoff_worker"] = "NOT_STARTED"
        return report
    report = record_captured_observation(repo_root, relative, capture, enabled=True, hooks=hooks)
    report["bridge_format"] = "NBH1-2048"
    report["watcher_io"] = False
    report["handoff_worker"] = "NOT_STARTED"
    report["live_watcher_connection"] = "P0_BLOCKED"
    return report


def isolated_poll_boundary(board_consumer, repo_root, relative, capture, *, enabled: bool = False, hooks=None) -> dict:
    """Run the writer, then the already-captured board consumer, even when the writer fails.

    This is the call shape a future watcher patch would use. The live watcher
    does not call it.
    """
    report = record_captured_observation(repo_root, relative, capture, enabled=enabled, hooks=hooks)
    levels = capture.get("levels") if isinstance(capture, dict) else None
    try:
        board_consumer(levels)
    except Exception:
        report = dict(report)
        report["board_consumer_ran"] = False
        report["reasons"] = sorted(set(report["reasons"]) | {"BOARD_CONSUMER_ERROR_ISOLATED"})
        return report
    report = dict(report)
    report["board_consumer_ran"] = True
    return report


def redact_writer_report(report: dict) -> dict:
    hidden = {"record", "levels", "pit_records", "capture", "top"}
    return {key: value for key, value in report.items() if key not in hidden}


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Append an already-captured private MS2 observation. Default: write nothing.")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--relative", default="")
    parser.add_argument("--capture", default="", help="Local JSON object. Ignored unless --enable is set.")
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args(argv)
    capture = None
    if args.enable and args.capture:
        try:
            raw = Path(args.capture).read_bytes()
        except OSError:
            report = _blocked(["CAPTURE_UNREADABLE"])
            json.dump(redact_writer_report(report), sys.stdout, ensure_ascii=False, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        if len(raw) > MAX_BYTES:
            report = _blocked(["PRIVATE_FILE_TOO_LARGE"])
            json.dump(redact_writer_report(report), sys.stdout, ensure_ascii=False, sort_keys=True)
            sys.stdout.write("\n")
            return 0
        try:
            capture = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            report = _blocked(["DATA_CORRUPT"])
            json.dump(redact_writer_report(report), sys.stdout, ensure_ascii=False, sort_keys=True)
            sys.stdout.write("\n")
            return 0
    report = record_captured_observation(
        args.repo_root,
        args.relative or None,
        capture,
        enabled=True if args.enable else False,
    )
    json.dump(redact_writer_report(report), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
