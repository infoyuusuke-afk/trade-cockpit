"""Private MS2 watcher sidecar contract and offline fail-closed validator.

Issue #346. The live watcher already reads a 10-level RSS board, a tick
window, and a gap diagnostic inside its 2-second poll. It does not persist
an atomic, timezone-aware observation. This module defines the private
sidecar that a future approved writer would append, and it checks those
bytes without starting Excel, without changing the watcher, and without
submitting an order.

The current watcher is the producer audit below. It is not a writer of this
schema. ``Kioxia_RSS_Live_Watcher.ps1`` stays untouched.

Clocks are separate fields. A missing clock stays null. This module does
not copy ``watcher_observed_at`` into ``event_time``, ``received_at``, or
``available_at``. ``poll_seq`` is the watcher loop counter. It is not an
exchange trade sequence.

A file is projectable to the Draft PR #345 ``ms2-pit-observation-0.1``
shape only when every required clock, book quantity, gap flag, and
exchange sequence is present and consistent. Projection stays
``evidence_origin=SYNTHETIC``. This module cannot authenticate a watcher
capture, so observed eligible N stays 0 and no virtual close is emitted.
PR #345 is not imported; it is not on this branch.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

CONTRACT_VERSION = "ms2-watcher-sidecar-contract-0.1"
SCHEMA_VERSION = "ms2-watcher-sidecar-0.1"
PIT_SCHEMA_VERSION = "ms2-pit-observation-0.1"
SIDECAR_WRITER_DEFAULT_ENABLED = False
PRIVATE_PARTS = ("data", "private", "ms2_sidecar")
MAX_BYTES = 8 * 1024 * 1024
CURRENT_WATCHER_SOURCE = "Kioxia_RSS_Live_Watcher.ps1"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,80}$")
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.jsonl$")
_OFFSET_RE = re.compile(r"^[+-](?:0[0-9]|1[0-4]):[0-5][0-9]$")

TICK_HEADER = "recorded_at,tick_time,price,volume,poll_seq"
DIAG_HEADER = "poll_time,window_size,overlap_with_prev,new_appended,suspected_gap"
BAR_HEADER = "bucket_start,open,high,low,close,volume,tick_count"
BOARD_HEADER = "日付,時刻,OVER気配数量,UNDER気配数量,UNDER比率,最良売気配値,最良買気配値,状態"

SHARED_FIELDS = frozenset({
    "schema_version", "observation_id", "source", "symbol", "market", "kind",
    "poll_seq", "poll_seq_basis", "sequence_basis", "order_proven", "exchange_sequence",
    "event_time", "event_time_basis",
    "watcher_observed_at", "watcher_observed_at_basis", "clock_source", "clock_quality", "timezone",
    "received_at", "received_at_basis",
    "available_at", "available_at_basis",
    "suspected_gap", "gap_evidence",
    "data_freshness", "freshness_basis", "quote_age_ms", "freshness_bound_ms",
    "capture_authenticated", "poll_window_ms",
})
BOARD_FIELDS = SHARED_FIELDS | frozenset({
    "snapshot_atomic", "read_method", "read_started_at", "read_finished_at", "read_skew_ms",
    "gap_diag", "book_qty_source", "top", "levels", "depth_claimed",
    "over_qty", "under_qty", "last_trade_price", "last_trade_qty", "last_trade_known",
    "tick_size", "tick_size_known",
})
TICK_FIELDS = SHARED_FIELDS | frozenset({
    "snapshot_atomic", "read_method", "read_started_at", "read_finished_at", "read_skew_ms",
    "gap_diag", "price", "volume",
})
GAP_FIELDS = SHARED_FIELDS | frozenset({
    "read_method", "window_size", "overlap_with_prev", "prev_poll_nonempty", "new_appended",
})
TOP_FIELDS = frozenset({
    "bid", "ask", "bid_qty", "ask_qty", "bid_qty_known", "ask_qty_known",
})
LEVEL_FIELDS = TOP_FIELDS | frozenset({"level", "read_at"})
GAP_DIAG_FIELDS = frozenset({
    "poll_seq", "window_size", "overlap_with_prev", "prev_poll_nonempty", "new_appended",
})
SAFETY_KEYS = frozenset({
    "real_submit_allowed", "promotion_eligible", "statistical_edge_confirmed",
    "rss_order_enabled", "autostart", "enable_writer", "sidecar_writer_enabled",
})


def producer_audit() -> dict:
    """Facts traced from the current watcher. This is not a capture."""
    return {
        "watcher": "ms2_live/Kioxia_RSS_Live_Watcher.ps1",
        "audited_main_sha": "7d796f1d4f60fb81027f756401d8dbf1c065c915",
        "board_reader": "Read-BoardDepth",
        "board_cells": "A870:D879",
        "board_read_shape": "ten sequential Cells.Item Value2 reads, four cells per level, no bulk Range.Value2",
        "board_error_handling": "per-level catch continue; Get-SafeNumber returns null for non-numeric, out-of-range, NaN, and infinity",
        "board_null_qty_still_appended": True,
        "board_used_for_orders": False,
        "ten_level_qty_persisted_in_csv": False,
        "poll_sleep_seconds": 2,
        "loop_clock": "one Get-Date before chart, tick, and board reads; no offset",
        "tick_writer": "Write-TickLogDiff",
        "tick_header": TICK_HEADER,
        "tick_time_meaning": "RssTickList HH:mm:ss, no date, no offset",
        "recorded_at_meaning": "watcher local Get-Date at append, yyyy-MM-dd HH:mm:ss, no offset",
        "poll_seq_meaning": "incremented once per Write-TickLogDiff; prints in that poll share it; not an exchange sequence",
        "diag_header": DIAG_HEADER,
        "diag_gap_rule": "previous poll keys nonempty and overlap 0 and window size > 0",
        "board_log_header": BOARD_HEADER,
        "board_log_clock": "minute truncation of the loop Get-Date, not the board cell-read time",
        "over_under_are_top_of_book_qty": False,
        "available_at_persisted": False,
        "received_at_persisted": False,
        "atomic_snapshot": False,
        "sidecar_writer_present": False,
        "calculate_scope": "RSS sheet Calculate, up to 3 attempts, 400ms apart; failure skips the rest of the loop",
        "com_write_retry": "Set-CellValue 20x300ms; startup board formulas use Invoke-ComRetry 8x500ms",
    }


def future_watcher_edit_plan() -> dict:
    """The live edit required before any real sidecar exists. Not applied."""
    return {
        "applied": False,
        "approval": "separate OWNER go-ahead required before any watcher edit",
        "future_source_id": "ms2-watcher-sidecar-writer-0.1",
        "default_enabled": False,
        "touch_points": [
            "Do not change Read-BoardDepth, Write-TickLogDiff, the 2-second sleep, RSS formulas, or dashboard writes in the same change as turning a writer on.",
            "A later approved patch would add one opt-in function after the existing Read-BoardDepth call, guarded by an explicit local flag that defaults off.",
            "That function would stamp read_started_at before the first board cell and read_finished_at after the last cell, and would persist null with qty_known false when Get-SafeNumber returns null.",
            "It would append only under data/private/ms2_sidecar, by temp file plus replace, and a disk or lock failure would be caught so the price, audio, and sign path continues.",
            "poll_seq would be copied from the loop counter already incremented in Write-TickLogDiff. It would not be written into exchange_sequence.",
            "event_time, received_at, and available_at would be null until a distinct measurement exists. The loop Get-Date would be watcher_observed_at only, with clock_quality UNSYNCHRONIZED_LOCAL.",
        ],
        "risks": [
            "Any extra COM read or timestamp inside the 2-second loop can extend the poll and increase RPC_E_CALL_REJECTED against Heartbeat and the 100-name collector.",
            "Appending a sidecar from the same try block as the dashboard write can skip the sign update when the disk is full.",
            "A bulk read would change the current 40-cell timing; this plan does not switch Read-BoardDepth to a bulk read.",
            "Writing the sidecar into ms2_live would mix it with the tick CSV. The private root is separate so the existing CSV bytes stay as they are.",
        ],
        "rollback": [
            "This contract PR has no watcher delta. Rollback is: do not deploy a watcher patch.",
            "If a later patch is live and COM errors, poll gaps, or dashboard freezes appear: Ctrl+C the watcher console only. The existing finally block sets RSS接続!B16 to 停止 and saves the workbook. Excel stays open.",
            "Do not Stop-Process Excel. Forced Excel termination is the known path to COM 0x80004002.",
            "Restore Kioxia_RSS_Live_Watcher.ps1 from audited main 7d796f1d4f60fb81027f756401d8dbf1c065c915 and delete only untracked data/private/ms2_sidecar jsonl. Leave kioxia_ticks, kioxia_tick_diag, and 気配値ログ.csv in place.",
        ],
    }


def windows_acceptance_checklist() -> list[dict]:
    """OWNER Windows checks. None of these ran in this offline change."""
    return [
        {
            "id": "W1",
            "when": "market closed, disposable workbook, or the live book only while the watcher is already stopped by OWNER",
            "check": "Start the current watcher with no sidecar flag. Confirm data/private/ms2_sidecar is absent or unchanged, tick and board CSV headers are unchanged, and the dashboard price still updates.",
            "status": "NOT_VERIFIED",
        },
        {
            "id": "W2",
            "when": "after a separate approval, off session, sidecar flag explicitly on",
            "check": "Record poll spacing, com_error_diag.csv growth, CPU, and whether the 40 cell reads made the loop exceed 2 seconds. Capture one private sidecar file and run this validator locally. Do not upload that file.",
            "status": "NOT_VERIFIED",
        },
        {
            "id": "W3",
            "when": "stop and restore",
            "check": "Ctrl+C the watcher window. Confirm B16 becomes 停止, Excel and MS2 remain running, and no Excel process is left behind by the watcher itself. Force-killing Excel is a failed stop.",
            "status": "NOT_VERIFIED",
        },
        {
            "id": "W4",
            "when": "fault",
            "check": "If COM errors, a frozen sign, a poll gap, or a sidecar exception appears, turn the future flag off, Ctrl+C, and restore the audited watcher script. Do not keep trading from a stale dashboard.",
            "status": "NOT_VERIFIED",
        },
    ]


def source_field_catalog() -> list[dict]:
    """Clock and book fields the current CSV files do not establish."""
    audit = producer_audit()
    return [
        {"field": "event_time", "meaning": "exchange timestamp only when the feed supplied one", "current": audit["tick_time_meaning"], "missing_treatment": "null with basis ABSENT; do not copy the loop clock"},
        {"field": "watcher_observed_at", "meaning": "local watcher clock with source and quality", "current": audit["loop_clock"], "missing_treatment": "do not assign an offset or call it NTP"},
        {"field": "received_at", "meaning": "a separate receive measurement", "current": "not stored", "missing_treatment": "null; do not rename recorded_at"},
        {"field": "available_at", "meaning": "when a consumer could read a durable sidecar line", "current": "not stored", "missing_treatment": "null; never set equal to the observation clock"},
        {"field": "poll_seq", "meaning": audit["poll_seq_meaning"], "current": "tick CSV column 5", "missing_treatment": "do not copy it into exchange_sequence"},
        {"field": "bid_qty", "meaning": "best bid size from the level-1 RSS cell", "current": "read in memory, not in the board CSV", "missing_treatment": "null and qty_known false; OVER/UNDER are not bid_qty"},
    ]


def _safety() -> dict:
    return {
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "rss_order_enabled": False,
        "watcher_modified": False,
        "legacy_history_modified": False,
        "sidecar_writer_default_enabled": SIDECAR_WRITER_DEFAULT_ENABLED,
        "writes_performed": False,
        "eligible_observed_n": 0,
        "recorded_forward_allowed": False,
        "closed_eligible": False,
        "expectancy_yen": None,
        "profit_factor": None,
        "max_drawdown_yen": None,
        "verified_net_pnl_yen": None,
        "remaining_to_10b_yen": None,
    }


def assess_cost(cost) -> dict:
    """Verified cost requires a status and an evidence reference. Amount is not echoed."""
    if cost is None:
        return {"verified": False, "status": "ABSENT", "reasons": ["COST_ABSENT"]}
    if not isinstance(cost, dict):
        return {"verified": False, "status": "UNVERIFIED", "reasons": ["COST_UNVERIFIED"]}
    status = cost.get("status")
    amount = cost.get("amount_yen")
    ref = cost.get("evidence_ref")
    if status == "MODEL":
        return {"verified": False, "status": "MODEL", "reasons": ["COST_MODELED_NOT_VERIFIED"]}
    if status != "VERIFIED":
        return {"verified": False, "status": "UNVERIFIED", "reasons": ["COST_UNVERIFIED"]}
    ref_ok = isinstance(ref, str) and bool(ref.strip()) and ref.strip().lower() not in {"0", "none", "zero"}
    amount_ok = _number(amount) and amount >= 0
    if not ref_ok or not amount_ok:
        return {"verified": False, "status": "UNVERIFIED", "reasons": ["COST_UNVERIFIED"]}
    return {"verified": True, "status": "VERIFIED", "reasons": ["COST_VERIFIED_NOT_A_FILL"]}


def _report(*, contract_status: str, decision_state: str, reasons: list[str], producer_id: str,
            cost: dict | None = None, bytes_read: int = 0, input_sha256: str | None = None,
            row_count: int = 0, admitted_count: int = 0, pit_records: list | None = None,
            synthetic_n: int = 0) -> dict:
    cost_info = cost or assess_cost(None)
    merged = set(reasons)
    merged.update(cost_info["reasons"])
    if contract_status != "NOT_READ":
        merged.update({"CAPTURE_NOT_AUTHENTICATED", "FILL_EVALUATOR_NOT_COUPLED", "ECONOMICS_UNKNOWN", "ELIGIBLE_OBSERVED_N_ZERO"})
    else:
        merged.update({"ELIGIBLE_OBSERVED_N_ZERO", "ECONOMICS_UNKNOWN"})
    close_state = "DISABLED" if contract_status == "NOT_READ" else "NOT_CLOSED"
    return {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "pit_schema_version": PIT_SCHEMA_VERSION,
        "contract_status": contract_status,
        "decision_state": decision_state,
        "close_state": close_state,
        "reasons": sorted(merged),
        "producer_id": producer_id,
        "bytes_read": bytes_read,
        "input_sha256": input_sha256,
        "row_count": row_count,
        "admitted_count": admitted_count,
        "pit_evidence_origin": "SYNTHETIC" if synthetic_n else None,
        "pit_records": pit_records or [],
        "synthetic_n": synthetic_n,
        "cost_status": cost_info["status"],
        **_safety(),
    }


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _int_nonneg(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


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


def _delta_ms(later: datetime, earlier: datetime) -> int | None:
    delta = later - earlier
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    if micros % 1000 != 0:
        return None
    return micros // 1000


def _parse_clock(raw, *, allow_null: bool, reject: list[str], label: str) -> datetime | None:
    if raw is None:
        if not allow_null:
            reject.append(label)
        return None
    if not isinstance(raw, str) or not raw.strip():
        reject.append("TIMESTAMP_INVALID")
        return None
    text = raw.strip()
    if text.endswith("Z") or "JST" in text or "Tokyo" in text or "Japan" in text:
        reject.append("TIMEZONE_UNKNOWN")
        return None
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        reject.append("TIMESTAMP_INVALID")
        return None
    if value.tzinfo is None or value.utcoffset() is None or _offset_text(value) is None:
        reject.append("TIMEZONE_UNKNOWN")
        return None
    return value


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("DUPLICATE_KEY")
        out[key] = value
    return out


def _legacy_code(raw: bytes) -> str | None:
    if raw.startswith(b"\xef\xbb\xbf"):
        text_bytes = raw[3:]
    else:
        text_bytes = raw
    stripped = text_bytes.lstrip()
    if not stripped or stripped[:1] in (b"{", b"["):
        return None
    try:
        first = text_bytes.decode("utf-8").splitlines()[0].strip()
    except UnicodeDecodeError:
        return None
    return {
        TICK_HEADER: "LEGACY_TICK_CSV",
        DIAG_HEADER: "LEGACY_DIAG_CSV",
        BAR_HEADER: "LEGACY_15S_CSV",
        BOARD_HEADER: "LEGACY_BOARD_CSV",
    }.get(first)


def _parse_jsonl(raw: bytes) -> list[dict]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("DATA_CORRUPT") from exc
    if "\x00" in text:
        raise ValueError("DATA_CORRUPT")
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
    return records


def _key_errors(record: dict, allowed: frozenset[str]) -> list[str]:
    reasons = []
    if not set(record).issubset(allowed):
        reasons.append("UNKNOWN_FIELD")
    if not allowed.issubset(record):
        reasons.append("MISSING_FIELD")
    leaked = SAFETY_KEYS.intersection(record)
    if leaked and any(record.get(key) is True for key in leaked):
        reasons.append("SAFETY_FLAG_REFUSED")
    return reasons


def _clock_bundle(record: dict, reject: list[str]) -> dict[str, datetime | None]:
    event = _parse_clock(record.get("event_time"), allow_null=True, reject=reject, label="EVENT_TIME_ABSENT")
    watcher = _parse_clock(record.get("watcher_observed_at"), allow_null=True, reject=reject, label="WATCHER_OBSERVED_AT_ABSENT")
    received = _parse_clock(record.get("received_at"), allow_null=True, reject=reject, label="TIMESTAMP_INVALID")
    available = _parse_clock(record.get("available_at"), allow_null=True, reject=reject, label="AVAILABLE_AT_ABSENT")
    present = [item for item in (event, watcher, received, available) if item is not None]
    timezone = record.get("timezone")
    if present:
        if not isinstance(timezone, str) or not _OFFSET_RE.fullmatch(timezone):
            reject.append("TIMEZONE_UNKNOWN")
        else:
            for item in present:
                if _offset_text(item) != timezone:
                    reject.append("TIMEZONE_MISMATCH")
                    break
    elif timezone not in (None,):
        reject.append("TIMEZONE_WITHOUT_TIMESTAMP")
    named = [item for item in present]
    for index, left in enumerate(named):
        for right in named[index + 1:]:
            if left == right:
                reject.append("CLOCKS_NOT_DISTINGUISHED")
                break
    return {"event": event, "watcher": watcher, "received": received, "available": available}


def _basis_clocks(record, clocks, reject, incomplete) -> None:
    event_basis = record.get("event_time_basis")
    if clocks["event"] is None:
        if event_basis != "ABSENT":
            reject.append("EVENT_TIME_BASIS_CONTRADICTION")
        else:
            incomplete.append("EVENT_TIME_ABSENT")
    elif event_basis != "EXCHANGE_SUPPLIED":
        reject.append("EVENT_TIME_BASIS_CONTRADICTION")
    watcher_basis = record.get("watcher_observed_at_basis")
    if clocks["watcher"] is None:
        if watcher_basis != "ABSENT" or record.get("clock_source") != "UNKNOWN" or record.get("clock_quality") != "UNKNOWN":
            reject.append("CLOCK_BASIS_CONTRADICTION")
        else:
            incomplete.append("WATCHER_OBSERVED_AT_ABSENT")
    else:
        if watcher_basis != "GET_DATE_LOCAL" or record.get("clock_source") not in {"WINDOWS_LOCAL", "OTHER_LOCAL"}:
            reject.append("CLOCK_BASIS_CONTRADICTION")
        quality = record.get("clock_quality")
        if quality == "NTP_ASSERTED":
            reject.append("CLOCK_QUALITY_UNPROVEN")
        elif quality == "UNKNOWN":
            incomplete.append("CLOCK_QUALITY_UNKNOWN")
        elif quality != "UNSYNCHRONIZED_LOCAL":
            reject.append("CLOCK_BASIS_CONTRADICTION")
    received_basis = record.get("received_at_basis")
    if clocks["received"] is None:
        if received_basis != "NOT_SEPARATELY_EVIDENCED":
            reject.append("RECEIVED_AT_NOT_SEPARATE")
    else:
        if received_basis != "SEPARATE_EVIDENCE":
            reject.append("RECEIVED_AT_NOT_SEPARATE")
    available_basis = record.get("available_at_basis")
    if available_basis not in {"DURABLE_CONSUMER_READ", "NOT_DEMONSTRATED"}:
        reject.append("AVAILABLE_AT_BASIS_INVALID")
    elif clocks["available"] is None:
        if available_basis != "NOT_DEMONSTRATED":
            reject.append("AVAILABLE_AT_BASIS_CONTRADICTION")
        else:
            incomplete.append("AVAILABLE_AT_ABSENT")
    elif available_basis != "DURABLE_CONSUMER_READ":
        reject.append("INVENTED_AVAILABLE_AT")
    if clocks["event"] is not None and clocks["watcher"] is not None:
        age = _delta_ms(clocks["watcher"], clocks["event"])
        if age is None:
            reject.append("SUBMILLISECOND_UNRECORDED")
        elif age <= 0:
            reject.append("TIME_ORDER_CONTRADICTION")
    if clocks["available"] is not None and clocks["watcher"] is not None:
        gap = _delta_ms(clocks["available"], clocks["watcher"])
        if gap is None:
            reject.append("SUBMILLISECOND_UNRECORDED")
        elif gap <= 0:
            reject.append("AVAILABLE_AT_ASSERTED_EQUAL")
    if clocks["available"] is not None and clocks["event"] is not None:
        ahead = _delta_ms(clocks["available"], clocks["event"])
        if ahead is None:
            reject.append("SUBMILLISECOND_UNRECORDED")
        elif ahead <= 0:
            reject.append("TIME_ORDER_CONTRADICTION")
    if clocks["received"] is not None and clocks["available"] is not None:
        order = _delta_ms(clocks["available"], clocks["received"])
        if order is None:
            reject.append("SUBMILLISECOND_UNRECORDED")
        elif order <= 0:
            reject.append("TIME_ORDER_CONTRADICTION")


def _sequence(record, reject, incomplete) -> int | None:
    poll = record.get("poll_seq")
    if not isinstance(poll, int) or isinstance(poll, bool) or not 1 <= poll <= 10**12:
        reject.append("POLL_SEQ_INVALID")
    if record.get("poll_seq_basis") != "WATCHER_LOOP":
        reject.append("POLL_SEQ_BASIS_INVALID")
    basis = record.get("sequence_basis")
    proven = record.get("order_proven")
    sequence = record.get("exchange_sequence")
    if not isinstance(proven, bool):
        reject.append("ORDER_PROVEN_INVALID")
        proven = False
    if basis not in {"POLL", "EXCHANGE", "UNKNOWN"}:
        reject.append("SEQUENCE_BASIS_INVALID")
    if basis == "POLL" and proven is True:
        reject.append("POLL_ORDER_NOT_EXCHANGE_ORDER")
    elif basis == "EXCHANGE" and proven is not True:
        reject.append("SEQUENCE_BASIS_CONTRADICTION")
    elif basis == "UNKNOWN" and proven is True:
        reject.append("SEQUENCE_BASIS_CONTRADICTION")
    elif basis == "POLL" and proven is False:
        incomplete.append("POLL_ORDER_NOT_EXCHANGE_ORDER")
    elif basis == "UNKNOWN" and proven is False:
        incomplete.append("SEQUENCE_BASIS_UNKNOWN")
    if sequence is None:
        if basis == "EXCHANGE":
            reject.append("EXCHANGE_SEQUENCE_ABSENT")
        else:
            incomplete.append("EXCHANGE_SEQUENCE_ABSENT")
        return None
    if not _int_nonneg(sequence) or sequence > 10**12:
        reject.append("EXCHANGE_SEQUENCE_INVALID")
        return None
    if basis != "EXCHANGE":
        reject.append("EXCHANGE_SEQUENCE_PRESENT_ON_POLL")
    if sequence == poll:
        reject.append("POLL_SEQ_REUSED_AS_EXCHANGE_SEQUENCE")
    return sequence if basis == "EXCHANGE" else None


def _freshness(record, clocks, reject, incomplete) -> str | None:
    freshness = record.get("data_freshness")
    basis = record.get("freshness_basis")
    age = record.get("quote_age_ms")
    bound = record.get("freshness_bound_ms")
    if freshness not in {"OK", "STALE", "MISSING", "FUTURE", "UNKNOWN"}:
        reject.append("FRESHNESS_INVALID")
        return None
    if freshness != "OK":
        if age is not None or bound is not None or basis not in {"NOT_EVIDENCED", "STALE_DECLARED", "MISSING_DECLARED", "FUTURE_DECLARED"}:
            reject.append("FRESHNESS_CONTRADICTION")
        else:
            incomplete.append({
                "STALE": "FRESHNESS_STALE",
                "MISSING": "FRESHNESS_MISSING",
                "FUTURE": "FRESHNESS_FUTURE",
                "UNKNOWN": "FRESHNESS_UNKNOWN",
            }[freshness])
        return None
    if basis != "EXCHANGE_AGE_WITHIN_BOUND":
        reject.append("FRESHNESS_CONTRADICTION")
        return None
    if not _int_nonneg(age) or not isinstance(bound, int) or isinstance(bound, bool) or bound <= 0:
        reject.append("FRESHNESS_CONTRADICTION")
        return None
    if clocks["event"] is None or clocks["watcher"] is None:
        reject.append("FRESHNESS_CONTRADICTION")
        return None
    measured = _delta_ms(clocks["watcher"], clocks["event"])
    if measured is None:
        reject.append("SUBMILLISECOND_UNRECORDED")
        return None
    if measured != age:
        reject.append("FRESHNESS_AGE_MISMATCH")
        return None
    if age > bound:
        reject.append("FRESHNESS_BOUND_EXCEEDED")
        return None
    return "OK"


def _gap_components(payload: dict, reject: list[str]) -> bool | None:
    window = payload.get("window_size")
    overlap = payload.get("overlap_with_prev")
    prev = payload.get("prev_poll_nonempty")
    new = payload.get("new_appended")
    if not _int_nonneg(window) or not _int_nonneg(overlap) or not isinstance(prev, bool) or not _int_nonneg(new):
        reject.append("GAP_DIAG_INVALID")
        return None
    if overlap > window or new > window:
        reject.append("GAP_DIAG_INVALID")
        return None
    return bool(prev is True and overlap == 0 and window > 0)


def _gap(record, reject, incomplete, *, nested: bool) -> bool | None:
    evidence = record.get("gap_evidence")
    flag = record.get("suspected_gap")
    if evidence not in {"ATTACHED", "NOT_ATTACHED"}:
        reject.append("GAP_EVIDENCE_INVALID")
        return None
    if not nested:
        if evidence != "ATTACHED":
            reject.append("GAP_ABSENCE_ASSUMED")
            return None
        expected = _gap_components(record, reject)
        if expected is None:
            return None
        if flag is not expected:
            reject.append("GAP_FLAG_CONTRADICTION")
            return None
        if flag is True:
            incomplete.append("GAP_SUSPECTED")
        elif record.get("prev_poll_nonempty") is not True:
            incomplete.append("GAP_UNPROVEN")
        return flag
    if evidence == "NOT_ATTACHED":
        if flag is not None or record.get("gap_diag") is not None:
            reject.append("GAP_ABSENCE_ASSUMED")
            return None
        incomplete.append("SUSPECTED_GAP_UNKNOWN")
        return None
    diag = record.get("gap_diag")
    if not isinstance(diag, dict) or set(diag) != GAP_DIAG_FIELDS:
        reject.append("GAP_DIAG_INVALID")
        return None
    if diag.get("poll_seq") != record.get("poll_seq"):
        reject.append("GAP_DIAG_INVALID")
        return None
    expected = _gap_components(diag, reject)
    if expected is None:
        return None
    if flag is not expected:
        reject.append("GAP_FLAG_CONTRADICTION")
        return None
    if flag is True:
        incomplete.append("GAP_SUSPECTED")
        return flag
    if diag.get("prev_poll_nonempty") is not True:
        incomplete.append("GAP_UNPROVEN")
    return flag


def _book_side(value, known, *, qty: bool, reject: list[str], incomplete: list[str], code: str):
    if not isinstance(known, bool):
        reject.append("BOOK_SHAPE_INVALID")
        return None
    if known is False:
        if value is not None:
            reject.append("BOOK_QTY_KNOWN_FLAG_CONTRADICTION" if qty else "BOOK_SHAPE_INVALID")
        incomplete.append(code)
        return None
    if qty:
        if not _number(value) or value < 0:
            reject.append("BOOK_QTY_KNOWN_WITHOUT_VALUE")
            return None
    elif not _number(value) or value <= 0:
        reject.append("BOOK_SHAPE_INVALID")
        return None
    return value


def _authoritative_book(record, read_clocks, reject, incomplete) -> dict | None:
    """Validate top-of-book and optional levels without treating unknown size as zero."""
    source = record.get("book_qty_source")
    if source == "OVER_UNDER":
        reject.append("BOOK_QTY_NOT_TOP_OF_BOOK")
    elif source not in {"RSS_LEVEL_QTY", "UNKNOWN"}:
        reject.append("BOOK_SHAPE_INVALID")
    top = record.get("top")
    levels = record.get("levels")
    depth = record.get("depth_claimed")
    if not isinstance(top, dict) or set(top) != TOP_FIELDS or not isinstance(levels, list):
        reject.append("BOOK_SHAPE_INVALID")
        return None
    if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 10 or len(levels) != depth:
        reject.append("DEPTH_CONTRADICTION")
        return None
    bid = _book_side(top.get("bid"), _price_known(top, "bid"), qty=False, reject=reject, incomplete=incomplete, code="BOOK_INCOMPLETE")
    ask = _book_side(top.get("ask"), _price_known(top, "ask"), qty=False, reject=reject, incomplete=incomplete, code="BOOK_INCOMPLETE")
    bid_qty = _book_side(top.get("bid_qty"), top.get("bid_qty_known"), qty=True, reject=reject, incomplete=incomplete, code="BOOK_QTY_UNKNOWN")
    ask_qty = _book_side(top.get("ask_qty"), top.get("ask_qty_known"), qty=True, reject=reject, incomplete=incomplete, code="BOOK_QTY_UNKNOWN")
    if source == "UNKNOWN" and (top.get("bid_qty_known") is True or top.get("ask_qty_known") is True):
        reject.append("BOOK_QTY_NOT_TOP_OF_BOOK")
    if source == "RSS_LEVEL_QTY" and (top.get("bid_qty_known") is not True or top.get("ask_qty_known") is not True):
        incomplete.append("BOOK_QTY_UNKNOWN")
    for name in ("over_qty", "under_qty"):
        value = record.get(name)
        if value is not None and (not _number(value) or value < 0):
            reject.append("BOOK_SHAPE_INVALID")
    if bid is not None and ask is not None:
        if bid > ask:
            incomplete.append("BOOK_CROSSED")
        elif bid == ask:
            incomplete.append("BOOK_LOCKED")
    trade_known = record.get("last_trade_known")
    tick_known = record.get("tick_size_known")
    if not isinstance(trade_known, bool) or not isinstance(tick_known, bool):
        reject.append("BOOK_SHAPE_INVALID")
    else:
        if trade_known:
            if not _number(record.get("last_trade_price")) or record.get("last_trade_price") <= 0 or not _number(record.get("last_trade_qty")) or record.get("last_trade_qty") < 0:
                reject.append("BOOK_SHAPE_INVALID")
        elif record.get("last_trade_price") is not None or record.get("last_trade_qty") is not None:
            reject.append("BOOK_SHAPE_INVALID")
        else:
            incomplete.append("TRADE_PRINT_ABSENT")
        if tick_known:
            if not _number(record.get("tick_size")) or record.get("tick_size") <= 0:
                reject.append("BOOK_SHAPE_INVALID")
        elif record.get("tick_size") is not None:
            reject.append("BOOK_SHAPE_INVALID")
        else:
            incomplete.append("TICK_SIZE_UNKNOWN")
    parsed = []
    for index, level in enumerate(levels):
        if not isinstance(level, dict) or set(level) != LEVEL_FIELDS or level.get("level") != index + 1:
            reject.append("LEVEL_INVALID")
            return None
        _book_side(level.get("bid"), _price_known(level, "bid"), qty=False, reject=reject, incomplete=incomplete, code="BOOK_INCOMPLETE")
        _book_side(level.get("ask"), _price_known(level, "ask"), qty=False, reject=reject, incomplete=incomplete, code="BOOK_INCOMPLETE")
        _book_side(level.get("bid_qty"), level.get("bid_qty_known"), qty=True, reject=reject, incomplete=incomplete, code="BOOK_QTY_UNKNOWN")
        _book_side(level.get("ask_qty"), level.get("ask_qty_known"), qty=True, reject=reject, incomplete=incomplete, code="BOOK_QTY_UNKNOWN")
        read_at = _parse_clock(level.get("read_at"), allow_null=True, reject=reject, label="TIMESTAMP_INVALID")
        if level.get("read_at") is not None and record.get("timezone") and read_at is not None and _offset_text(read_at) != record.get("timezone"):
            reject.append("TIMEZONE_MISMATCH")
        parsed.append((level, read_at))
    if depth >= 1:
        first, _ = parsed[0]
        for key in ("bid", "ask", "bid_qty", "ask_qty", "bid_qty_known", "ask_qty_known"):
            if first.get(key) != top.get(key):
                reject.append("BOOK_TOP_MISMATCH")
                break
    _read_span(record, read_clocks, parsed, reject, incomplete)
    if any(code in reject for code in ("BOOK_SHAPE_INVALID", "LEVEL_INVALID", "BOOK_QTY_NOT_TOP_OF_BOOK", "BOOK_TOP_MISMATCH", "DEPTH_CONTRADICTION")):
        return None
    return {"bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty}


def _price_known(payload: dict, field: str) -> bool:
    """Return whether a price cell is present.

    Null means the cell was not a usable number. A present number is checked
    separately and is not treated as known when it is zero, non-finite, or
    non-numeric. Quantities use their own flags, so a price can be present
    while its size stays unknown.
    """
    return payload.get(field) is not None


def _read_span(record, clocks, parsed, reject, incomplete) -> None:
    method = record.get("read_method")
    atomic = record.get("snapshot_atomic")
    started = _parse_clock(record.get("read_started_at"), allow_null=True, reject=reject, label="TIMESTAMP_INVALID")
    finished = _parse_clock(record.get("read_finished_at"), allow_null=True, reject=reject, label="TIMESTAMP_INVALID")
    skew = record.get("read_skew_ms")
    clocks["read_started"] = started
    clocks["read_finished"] = finished
    if method == "SEQUENTIAL_CELL":
        if atomic is not False:
            reject.append("SNAPSHOT_ATOMIC_CONTRADICTION")
        else:
            incomplete.append("SNAPSHOT_NOT_ATOMIC")
    elif method == "BULK_RANGE":
        if atomic is not True:
            reject.append("SNAPSHOT_ATOMIC_CONTRADICTION")
    else:
        reject.append("SNAPSHOT_ATOMIC_CONTRADICTION")
        return
    if started is None or finished is None:
        incomplete.append("SKEW_NOT_RECORDED")
        if skew is not None:
            reject.append("SKEW_CONTRADICTION")
        return
    if record.get("timezone") and (_offset_text(started) != record.get("timezone") or _offset_text(finished) != record.get("timezone")):
        reject.append("TIMEZONE_MISMATCH")
    measured = _delta_ms(finished, started)
    if measured is None:
        reject.append("SUBMILLISECOND_UNRECORDED")
        return
    if measured < 0:
        reject.append("TIME_ORDER_CONTRADICTION")
        return
    if skew is None:
        incomplete.append("SKEW_NOT_RECORDED")
    elif not _int_nonneg(skew) or skew != measured:
        reject.append("SKEW_MISMATCH")
    if method == "BULK_RANGE" and (skew != 0 or started != finished):
        reject.append("SNAPSHOT_ATOMIC_CONTRADICTION")
    level_times = [item[1] for item in parsed if item[1] is not None]
    if method == "BULK_RANGE":
        for item in level_times:
            if item != started:
                reject.append("SNAPSHOT_ATOMIC_CONTRADICTION")
                break
    elif level_times:
        if min(level_times) != started or max(level_times) != finished:
            reject.append("SKEW_CONTRADICTION")
    if clocks.get("available") is not None and finished is not None:
        after = _delta_ms(clocks["available"], finished)
        if after is None:
            reject.append("SUBMILLISECOND_UNRECORDED")
        elif after <= 0:
            reject.append("AVAILABLE_AT_ASSERTED_EQUAL")
    if clocks.get("watcher") is not None and started is not None and finished is not None:
        if started < clocks["watcher"] and record.get("kind") == "BOARD_SNAPSHOT":
            # The loop clock may be taken before the cell reads. That is allowed.
            pass
        if finished < clocks["watcher"]:
            reject.append("TIME_ORDER_CONTRADICTION")


def _identity(record, reject) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        reject.append("SCHEMA_VERSION_UNKNOWN")
    if not isinstance(record.get("observation_id"), str) or not _NAME_RE.fullmatch(record.get("observation_id", "")):
        reject.append("OBSERVATION_ID_ABSENT")
    source = record.get("source")
    if not _text(source) or len(source) > 120:
        reject.append("SOURCE_ABSENT")
    elif source == CURRENT_WATCHER_SOURCE:
        reject.append("WATCHER_SOURCE_HAS_NO_SIDECAR")
    symbol = record.get("symbol")
    if not isinstance(symbol, str) or not _NAME_RE.fullmatch(symbol):
        reject.append("SYMBOL_ABSENT")
    if record.get("market") not in {"TSE", "JNX"}:
        reject.append("MARKET_INVALID")
    if record.get("capture_authenticated") is not False:
        reject.append("CAPTURE_AUTHENTICATION_REFUSED")
    window = record.get("poll_window_ms")
    if window is not None and (not isinstance(window, int) or isinstance(window, bool) or window <= 0 or window > 60_000):
        reject.append("POLL_WINDOW_INVALID")


def _pit_quote(record, clocks, book) -> dict | None:
    if book is None or any(book.get(key) is None for key in ("bid", "ask", "bid_qty", "ask_qty")):
        return None
    if book["bid"] >= book["ask"]:
        return None
    if record.get("last_trade_known") is not True or record.get("tick_size_known") is not True:
        return None
    return {
        "schema_version": PIT_SCHEMA_VERSION,
        "event_id": record["observation_id"],
        "kind": "QUOTE",
        "source": record["source"],
        "symbol": record["symbol"],
        "market": record["market"],
        "event_time": record["event_time"],
        "available_at": record["available_at"],
        "timezone": record["timezone"],
        "sequence_basis": "EXCHANGE",
        "order_proven": True,
        "sequence": record["exchange_sequence"],
        "poll_seq": record["poll_seq"],
        "suspected_gap": False,
        "data_freshness": "OK",
        "bid": book["bid"],
        "ask": book["ask"],
        "bid_qty": book["bid_qty"],
        "ask_qty": book["ask_qty"],
        "last_trade_price": record["last_trade_price"],
        "last_trade_qty": record["last_trade_qty"],
        "tick_size": record["tick_size"],
    }


def _pit_print(record) -> dict:
    return {
        "schema_version": PIT_SCHEMA_VERSION,
        "event_id": record["observation_id"],
        "kind": "ORDERED_PRINT",
        "source": record["source"],
        "symbol": record["symbol"],
        "market": record["market"],
        "event_time": record["event_time"],
        "available_at": record["available_at"],
        "timezone": record["timezone"],
        "sequence_basis": "EXCHANGE",
        "order_proven": True,
        "sequence": record["exchange_sequence"],
        "poll_seq": record["poll_seq"],
        "suspected_gap": False,
        "data_freshness": "OK",
        "price": record["price"],
        "volume": record["volume"],
    }


def validate_record(record: dict) -> dict:
    """Validate one sidecar object. Reject codes block the whole file."""
    reject: list[str] = []
    incomplete: list[str] = []
    if not isinstance(record, dict):
        return {"reject": ["DATA_CORRUPT"], "incomplete": [], "pit": None, "clocks": {}, "kind": None}
    kind = record.get("kind")
    allowed = {"BOARD_SNAPSHOT": BOARD_FIELDS, "TICK_PRINT": TICK_FIELDS, "GAP_DIAG": GAP_FIELDS}.get(kind)
    if allowed is None:
        reject.append("KIND_INVALID")
        allowed = SHARED_FIELDS
    reject.extend(_key_errors(record, allowed))
    _identity(record, reject)
    clocks = _clock_bundle(record, reject)
    if "MISSING_FIELD" not in reject and "UNKNOWN_FIELD" not in reject:
        _basis_clocks(record, clocks, reject, incomplete)
        _sequence(record, reject, incomplete)
        freshness = _freshness(record, clocks, reject, incomplete)
        if kind == "GAP_DIAG":
            _gap(record, reject, incomplete, nested=False)
            if record.get("read_method") != "NOT_APPLICABLE":
                reject.append("SNAPSHOT_ATOMIC_CONTRADICTION")
            incomplete.append("GAP_DIAG_NOT_A_QUOTE")
            pit = None
        elif kind == "TICK_PRINT":
            _gap(record, reject, incomplete, nested=True)
            _print_fields(record, reject, incomplete)
            pit = _pit_print(record) if freshness == "OK" else None
        elif kind == "BOARD_SNAPSHOT":
            _gap(record, reject, incomplete, nested=True)
            book = _authoritative_book(record, clocks, reject, incomplete)
            pit = _pit_quote(record, clocks, book) if freshness == "OK" else None
        else:
            pit = None
    else:
        pit = None
    if pit is not None and incomplete:
        pit = None
    if reject:
        pit = None
    return {
        "reject": sorted(set(reject)),
        "incomplete": sorted(set(incomplete)),
        "pit": pit,
        "clocks": clocks,
        "kind": kind,
        "observation_id": record.get("observation_id"),
        "symbol": record.get("symbol"),
        "market": record.get("market"),
        "poll_seq": record.get("poll_seq"),
        "sequence": record.get("exchange_sequence"),
        "event_time": clocks.get("event"),
        "poll_window_ms": record.get("poll_window_ms"),
        "gap_diag": record.get("gap_diag") if kind != "GAP_DIAG" else {
            "poll_seq": record.get("poll_seq"),
            "window_size": record.get("window_size"),
            "overlap_with_prev": record.get("overlap_with_prev"),
            "prev_poll_nonempty": record.get("prev_poll_nonempty"),
            "new_appended": record.get("new_appended"),
        },
        "suspected_gap": record.get("suspected_gap"),
    }


def _print_fields(record, reject, incomplete) -> None:
    if record.get("read_method") != "NOT_APPLICABLE" or record.get("snapshot_atomic") is not None:
        reject.append("PRINT_IS_NOT_A_QUOTE")
    if record.get("read_started_at") is not None or record.get("read_finished_at") is not None or record.get("read_skew_ms") is not None:
        reject.append("PRINT_IS_NOT_A_QUOTE")
    price = record.get("price")
    volume = record.get("volume")
    if price is None:
        incomplete.append("PRICE_ABSENT")
    elif not _number(price) or price <= 0:
        reject.append("PRICE_INVALID")
    if volume is None:
        incomplete.append("VOLUME_ABSENT")
    elif not _number(volume) or volume <= 0:
        reject.append("VOLUME_INVALID")
    if record.get("gap_diag") is not None and record.get("gap_evidence") == "NOT_ATTACHED":
        reject.append("GAP_ABSENCE_ASSUMED")


def _canonical(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def audit_sidecar_bytes(raw: bytes, *, cost=None) -> dict:
    """Validate sidecar bytes. The same bytes always yield the same report."""
    cost_info = assess_cost(cost)
    if not isinstance(raw, (bytes, bytearray)):
        return _report(contract_status="BLOCKED", decision_state="BLOCKED", reasons=["DATA_CORRUPT"], producer_id="none", cost=cost_info)
    raw = bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_BYTES:
        return _report(
            contract_status="BLOCKED", decision_state="BLOCKED", reasons=["PRIVATE_FILE_TOO_LARGE"],
            producer_id="none", cost=cost_info, bytes_read=len(raw), input_sha256=digest,
        )
    legacy = _legacy_code(raw)
    if legacy:
        return _report(
            contract_status="BLOCKED", decision_state="BLOCKED", reasons=[legacy, "LEGACY_CSV_NOT_MIGRATED"],
            producer_id="ms2_live.legacy_csv", cost=cost_info, bytes_read=len(raw), input_sha256=digest,
        )
    try:
        records = _parse_jsonl(raw)
    except ValueError as exc:
        code = str(exc) if str(exc) in {"DATA_CORRUPT", "EMPTY_INPUT"} else "DATA_CORRUPT"
        return _report(
            contract_status="BLOCKED", decision_state="BLOCKED", reasons=[code],
            producer_id="ms2_sidecar.unreadable", cost=cost_info, bytes_read=len(raw), input_sha256=digest,
        )
    reasons: list[str] = []
    seen: dict[str, str] = {}
    unique = []
    for record in records:
        token = _canonical(record)
        observation_id = record.get("observation_id")
        if isinstance(observation_id, str) and observation_id in seen:
            if seen[observation_id] != token:
                reasons.append("DUPLICATE_CONFLICT")
            continue
        if isinstance(observation_id, str):
            seen[observation_id] = token
        unique.append(record)
    validated = [validate_record(record) for record in unique]
    for item in validated:
        reasons.extend(item["reject"])
        reasons.extend(item["incomplete"])
    identities = [(item["symbol"], item["market"], item["kind"], item["poll_seq"]) for item in validated]
    if len(identities) != len(set(identities)):
        reasons.append("DUPLICATE_POLL")
    symbols = {item["symbol"] for item in validated}
    markets = {item["market"] for item in validated}
    kinds = {item["kind"] for item in validated}
    if len(symbols) > 1:
        reasons.append("MIXED_SYMBOL")
    if len(markets) > 1:
        reasons.append("MIXED_MARKET")
    if len(kinds) > 1:
        reasons.append("MIXED_KIND")
    ordered = sorted(
        (item for item in validated if item["event_time"] is not None and _int_nonneg(item["sequence"])),
        key=lambda item: (item["event_time"], item["sequence"], str(item["observation_id"])),
    )
    sequences = [item["sequence"] for item in ordered]
    if len(sequences) != len(set(sequences)):
        reasons.append("EXCHANGE_SEQUENCE_INVALID")
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
    # File-level duplicates are rejects. A poll-order or missing exchange sequence is incomplete
    # when validate_record recorded it that way, and a reject when the record claimed otherwise.
    reject_only = set()
    for item in validated:
        reject_only.update(item["reject"])
    reject_only.update({"DUPLICATE_CONFLICT", "DUPLICATE_POLL", "MIXED_MARKET", "MIXED_SYMBOL", "MIXED_KIND", "SEQUENCE_TIME_CONFLICT", "EXCHANGE_SEQUENCE_INVALID"})
    blocked = bool(reject_only.intersection(reasons) or (set(reasons) & {
        "DUPLICATE_CONFLICT", "DUPLICATE_POLL", "MIXED_MARKET", "MIXED_SYMBOL", "MIXED_KIND",
        "SEQUENCE_TIME_CONFLICT",
    }))
    incomplete_codes = [code for item in validated for code in item["incomplete"]]
    if blocked:
        return _report(
            contract_status="BLOCKED", decision_state="BLOCKED", reasons=reasons,
            producer_id="ms2_watcher_sidecar", cost=cost_info, bytes_read=len(raw),
            input_sha256=digest, row_count=len(records), admitted_count=0,
        )
    pit = [item["pit"] for item in validated if item["pit"] is not None]
    if incomplete_codes or len(pit) != len(validated):
        return _report(
            contract_status="ADMITTED_INCOMPLETE", decision_state="BLOCKED", reasons=reasons,
            producer_id="ms2_watcher_sidecar", cost=cost_info, bytes_read=len(raw),
            input_sha256=digest, row_count=len(records), admitted_count=len(unique),
        )
    pit_sorted = sorted(pit, key=lambda item: (item["event_time"], item["sequence"], item["event_id"]))
    return _report(
        contract_status="PROJECTABLE_SYNTHETIC", decision_state="BLOCKED", reasons=reasons,
        producer_id="ms2_watcher_sidecar", cost=cost_info, bytes_read=len(raw),
        input_sha256=digest, row_count=len(records), admitted_count=len(unique),
        pit_records=pit_sorted, synthetic_n=len(pit_sorted),
    )


def resolve_sidecar_path(repo_root, relative: str) -> Path:
    """Resolve one jsonl file under data/private/ms2_sidecar. Refuse links and parent segments."""
    if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")):
        raise ValueError("PRIVATE_PATH_INVALID")
    parts = Path(relative).parts
    if ".." in parts or parts[:3] != PRIVATE_PARTS or len(parts) != 4 or not _FILE_RE.fullmatch(parts[3]):
        raise ValueError("PRIVATE_PATH_INVALID")
    root = Path(repo_root).resolve()
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("PRIVATE_PATH_LINK")
    allowed_parent = root / "data" / "private" / "ms2_sidecar"
    if current.parent != allowed_parent:
        raise ValueError("PRIVATE_PATH_INVALID")
    if not current.is_file():
        raise ValueError("PRIVATE_PATH_NOT_FOUND")
    if current.stat().st_size > MAX_BYTES:
        raise ValueError("PRIVATE_FILE_TOO_LARGE")
    return current


def audit_private_sidecar(repo_root, relative: str | None, *, cost=None) -> dict:
    """Read one explicit private file. An empty path reads nothing and writes nothing."""
    if relative is None or relative == "":
        return _report(
            contract_status="NOT_READ", decision_state="DISABLED", reasons=["SIDECAR_DISABLED"],
            producer_id="none", cost=assess_cost(cost),
        )
    try:
        path = resolve_sidecar_path(repo_root, relative)
    except ValueError as exc:
        code = str(exc) if str(exc) in {"PRIVATE_PATH_INVALID", "PRIVATE_PATH_LINK", "PRIVATE_PATH_NOT_FOUND", "PRIVATE_FILE_TOO_LARGE"} else "PRIVATE_PATH_INVALID"
        return _report(contract_status="BLOCKED", decision_state="BLOCKED", reasons=[code], producer_id="none", cost=assess_cost(cost))
    except OSError:
        return _report(contract_status="BLOCKED", decision_state="BLOCKED", reasons=["PRIVATE_PATH_INVALID"], producer_id="none", cost=assess_cost(cost))
    return audit_sidecar_bytes(path.read_bytes(), cost=cost)


def join_poll_references(board: dict | None, tick: dict | None, diag: dict | None) -> dict:
    """Join a board, a tick, and a gap row only when poll id and clocks prove the same poll.

    A match is a poll reference. It does not create an exchange order or a quote.
    """
    base = {
        "exchange_order_proven": False,
        "pit_projectable": False,
        "real_submit_allowed": False,
        "eligible_observed_n": 0,
    }
    if not all(isinstance(item, dict) for item in (board, tick, diag)):
        return {**base, "status": "NOT_JOINED", "reasons": ["JOIN_INPUT_ABSENT"], "poll_seq": None}
    checked = [validate_record(board), validate_record(tick), validate_record(diag)]
    reasons = [code for item in checked for code in item["reject"]]
    if reasons:
        return {**base, "status": "BLOCKED", "reasons": sorted(set(reasons)), "poll_seq": None}
    if [item["kind"] for item in checked] != ["BOARD_SNAPSHOT", "TICK_PRINT", "GAP_DIAG"]:
        return {**base, "status": "BLOCKED", "reasons": ["JOIN_KIND_MISMATCH"], "poll_seq": None}
    poll_ids = {item["poll_seq"] for item in checked}
    symbols = {item["symbol"] for item in checked}
    markets = {item["market"] for item in checked}
    if len(poll_ids) != 1 or len(symbols) != 1 or len(markets) != 1:
        return {**base, "status": "NOT_JOINED", "reasons": ["POLL_REFERENCE_MISMATCH"], "poll_seq": None}
    if board.get("suspected_gap") is True or diag.get("suspected_gap") is True:
        return {**base, "status": "BLOCKED", "reasons": ["GAP_SUSPECTED"], "poll_seq": board.get("poll_seq")}
    board_diag = board.get("gap_diag")
    if not isinstance(board_diag, dict) or any(board_diag.get(key) != diag.get(key) for key in ("window_size", "overlap_with_prev", "prev_poll_nonempty", "new_appended")):
        return {**base, "status": "BLOCKED", "reasons": ["GAP_REFERENCE_CONTRADICTION"], "poll_seq": board.get("poll_seq")}
    if board.get("suspected_gap") != diag.get("suspected_gap"):
        return {**base, "status": "BLOCKED", "reasons": ["GAP_REFERENCE_CONTRADICTION"], "poll_seq": board.get("poll_seq")}
    window = board.get("poll_window_ms")
    if window is None or tick.get("poll_window_ms") != window or diag.get("poll_window_ms") != window:
        return {**base, "status": "NOT_JOINED", "reasons": ["TIME_REFERENCE_UNPROVEN"], "poll_seq": board.get("poll_seq")}
    tick_at = checked[1]["clocks"].get("watcher")
    diag_at = checked[2]["clocks"].get("watcher")
    started = checked[0]["clocks"].get("read_started")
    finished = checked[0]["clocks"].get("read_finished")
    if tick_at is None or diag_at is None or started is None or finished is None:
        return {**base, "status": "NOT_JOINED", "reasons": ["TIME_REFERENCE_UNPROVEN"], "poll_seq": board.get("poll_seq")}
    if diag_at != tick_at:
        return {**base, "status": "BLOCKED", "reasons": ["TIME_REFERENCE_CONTRADICTION"], "poll_seq": board.get("poll_seq")}
    span = _delta_ms(max(finished, tick_at), min(started, tick_at))
    if span is None or span > window:
        return {**base, "status": "BLOCKED", "reasons": ["TIME_REFERENCE_CONTRADICTION"], "poll_seq": board.get("poll_seq")}
    return {
        **base,
        "status": "POLL_REFERENCE_MATCHED",
        "reasons": ["POLL_MATCH_IS_NOT_EXCHANGE_ORDER"],
        "poll_seq": board.get("poll_seq"),
    }


def redact_report(report: dict) -> dict:
    """Drop projected prices and quantities before a text export."""
    hidden = {"pit_records"}
    exported = {key: value for key, value in report.items() if key not in hidden}
    exported["pit_event_ids"] = sorted(
        item.get("event_id") for item in report.get("pit_records") or [] if isinstance(item, dict)
    )
    exported["pit_count"] = len(report.get("pit_records") or [])
    return exported


def main(argv=None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Validate a private MS2 watcher sidecar without reading it unless --input is set")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--input", default="", help="data/private/ms2_sidecar/<file>.jsonl or empty to read nothing")
    args = parser.parse_args(argv)
    report = audit_private_sidecar(args.repo_root, args.input or None)
    json.dump(redact_report(report), sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
