"""Bounded non-blocking handoff for an already-copied MS2 board.

Issue #352. Draft PR #351 can notice that a synchronous writer exceeded 50ms
only after that writer returns. A stalled disk write still holds the caller
for the whole stall. This module does not edit the watcher and does not open
Excel. It copies a fixed-size record into a preallocated shared-memory slot
and returns. A separate process performs the private JSONL write.

The producer path does not take a lock, does not call ``json.dumps``, and
does not call a blocking write. Queue capacity is fixed. When it is full the
incoming record is dropped and counted. The worker never reads Excel.

This is not a hard real-time guarantee. CPython on a general-purpose OS can
still be delayed by the scheduler. Live watcher connection stays blocked.
"""
from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import struct
import sys
import time
import uuid
from datetime import datetime
from multiprocessing import Process, get_context
from multiprocessing import shared_memory
from pathlib import Path

from scripts.ms2_offline_observation_writer import record_captured_observation
from scripts.ms2_watcher_sidecar_contract import CURRENT_WATCHER_SOURCE, SAFETY_KEYS

HANDOFF_VERSION = "ms2-nonblocking-handoff-0.1"
AUDITED_MAIN_SHA = "b235fde33a47975ca771e3d6c2b4d0e4b613d600"
STACK_HEAD = "b7ed5ae7f2a1eaca7aa13290730b7058958f2ac5"
WATCHER_RELATIVE = "ms2_live/Kioxia_RSS_Live_Watcher.ps1"
QUEUE_CAPACITY = 8
RECORD_SIZE = 2048
SLOT_BASE = 4096
SHM_SIZE = SLOT_BASE + QUEUE_CAPACITY * RECORD_SIZE
DROP_POLICY = "DROP_NEWEST"
RESTART_POLICY = "DISCARD_UNPUBLISHED"
RETRY_POLICY = "NO_RETRY"
SUBMIT_DEADLINE_NS = 5_000_000
STOP_TIMEOUT_S = 0.25
STALL_AFTER_NS = 150_000_000
HEARTBEAT_GRACE_NS = 1_000_000_000
EXISTING_BOARD_COM_READS = 40
EXTRA_COM_READS = 0
HARD_REALTIME_GUARANTEED = False
LIVE_WATCHER_CONNECTION = "P0_BLOCKED"
MAGIC = b"NBH1"

_OFF_WRITE = 0
_OFF_READ = 8
_OFF_DROPPED = 16
_OFF_HEARTBEAT = 24
_OFF_FLAGS = 32
_OFF_WORKER_PID = 40
_OFF_QUEUED = 48
_OFF_DURABLE = 56
_OFF_FAILURES = 64
_OFF_FAIL_CLOSED = 72
_OFF_DUPLICATES = 80
_OFF_STALL_SEEN = 88
_OFF_STALE_DISCARDED = 96
_OFF_FAULT = 104
_OFF_GENERATION = 112
_OFF_COM_READS = 120
_OFF_LOCK_TIMEOUTS = 128
_OFF_DEAD_DROPS = 136
_OFF_KILL_DROPS = 144
_OFF_MAX_ELAPSED_NS = 152
_OFF_SUBMIT_COUNT = 160
_OFF_LAST_ELAPSED_NS = 168
_OFF_REASON = 256
_REASON_SIZE = 32

_FLAG_KILL = 1
_FLAG_STOP = 2

FAULT_NONE = 0
FAULT_HOLD = 1
FAULT_BLOCK_IO = 2
FAULT_DISK_FULL = 3
FAULT_PERMISSION = 4
FAULT_FILE_LOCK = 5
FAULT_CRASH = 6
FAULT_STALL = 7
FAULT_BLOCK_UNCHECKED = 8

_FRESHNESS = ("UNKNOWN", "OK", "STALE", "MISSING", "FUTURE")
_CLOCK_LIMIT = 40
_SOURCE_LIMIT = 120
_ID_LIMIT = 80
_SYMBOL_LIMIT = 32


def _atom(buf, offset: int) -> ctypes.c_uint64:
    return ctypes.c_uint64.from_buffer(buf, offset)


def _load(buf, offset: int) -> int:
    return int(_atom(buf, offset).value)


def _store(buf, offset: int, value: int) -> None:
    _atom(buf, offset).value = int(value)


def _add(buf, offset: int, count: int = 1) -> None:
    item = _atom(buf, offset)
    item.value = int(item.value) + count


def _reason(buf, text: str) -> None:
    raw = text.encode("ascii", "replace")[:_REASON_SIZE]
    buf[_OFF_REASON:_OFF_REASON + _REASON_SIZE] = raw.ljust(_REASON_SIZE, b"\0")


def _read_reason(buf) -> str:
    raw = bytes(buf[_OFF_REASON:_OFF_REASON + _REASON_SIZE]).split(b"\0", 1)[0]
    return raw.decode("ascii", "replace")


def handoff_contract() -> dict:
    """Fixed bounds. These are not a license to edit or start the watcher."""
    return {
        "handoff_version": HANDOFF_VERSION,
        "audited_main_sha": AUDITED_MAIN_SHA,
        "stack_head": STACK_HEAD,
        "queue_capacity": QUEUE_CAPACITY,
        "record_bytes": RECORD_SIZE,
        "drop_policy": DROP_POLICY,
        "restart_policy": RESTART_POLICY,
        "retry_policy": RETRY_POLICY,
        "submit_deadline_ns": SUBMIT_DEADLINE_NS,
        "stop_timeout_s": STOP_TIMEOUT_S,
        "producer_locks": 0,
        "producer_json_dumps": False,
        "producer_blocking_write": False,
        "extra_com_reads": EXTRA_COM_READS,
        "worker_excel_access": False,
        "snapshot_atomic": False,
        "sequence_basis": "POLL",
        "hard_realtime_guaranteed": HARD_REALTIME_GUARANTEED,
        "hard_realtime_reason": "CPYTHON_USERSPACE_ON_GENERAL_PURPOSE_OS",
        "live_watcher_connection": LIVE_WATCHER_CONNECTION,
        "watcher_modified": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "windows_acceptance": "NOT_VERIFIED",
    }


def windows_acceptance_checklist() -> list[dict]:
    """Market-closed Windows steps. Not executed in this environment."""
    return [
        {
            "id": "W1",
            "status": "NOT_VERIFIED",
            "title": "起動と現行経路",
            "checks": [
                "市場外。Watcherの自動起動は使わない。sidecarフラグはオフのまま現行Watcherを起動する。",
                "現在値、音声、売買サイン、Excelが通常どおり動くこと。private jsonlが増えないこと。",
                "追加のValue2が無いこと。Read-BoardDepthは従来の40回のままであること。",
            ],
        },
        {
            "id": "W2",
            "status": "NOT_VERIFIED",
            "title": "COM競合とポーリング遅れ",
            "checks": [
                "別承認のあと、市場外だけでフラグをオンにする。先にフラグなしで60秒の基準を取る。",
                "数えるのはポーリング遅れ、COMエラー件数、CPU、破棄件数だけとする。価格と板の生値は控えない。",
                "フラグオンのCOMエラーが基準より増えないこと。サインが凍結しないこと。",
            ],
        },
        {
            "id": "W3",
            "status": "NOT_VERIFIED",
            "title": "Writer障害",
            "checks": [
                "書込先を書けない場所、満杯、ロック、ワーカー強制終了にそれぞれ一度だけ切り替える。",
                "Watcherの現在値、音声、サインが続くこと。破棄件数とfail-closed件数が数として残ること。",
                "再試行ループで2秒待機を止めていないこと。privateファイルをGitHubへ出さないこと。",
            ],
        },
        {
            "id": "W4",
            "status": "NOT_VERIFIED",
            "title": "停止とExcel残留",
            "checks": [
                "WatcherコンソールだけをCtrl+Cする。終了待機の上限を超えたらWriterプロセスを切る。",
                "Excelは開いたままにする。ExcelをStop-Processまたはtaskkillしない。",
                "RSS接続!B16が停止になること。kioxia_ticksと気配値ログは削除しないこと。フラグをオフに戻すこと。",
            ],
        },
    ]


def _put_text(buf: bytearray, offset: int, size: int, text: str) -> bool:
    raw = text.encode("utf-8")
    if len(raw) > size:
        return False
    buf[offset:offset + size] = raw.ljust(size, b"\0")
    return True


def _get_text(blob: bytes, offset: int, size: int) -> str:
    raw = blob[offset:offset + size].split(b"\0", 1)[0]
    return raw.decode("utf-8")


def _clock_problem(value) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        return "TIMESTAMP_INVALID"
    if len(value) > _CLOCK_LIMIT or sys.getsizeof(value) > 1024:
        return "TIMESTAMP_INVALID"
    text = value.strip()
    if text.endswith("Z") or "JST" in text or "Tokyo" in text or "Japan" in text:
        return "TIMEZONE_NOT_GUESSED"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return "TIMESTAMP_INVALID"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "TIMEZONE_NOT_GUESSED"
    if parsed.microsecond % 1000 != 0:
        return "SUBMILLISECOND_UNRECORDED"
    return None


def _number(value, *, positive: bool):
    if type(value) is bool or sys.getsizeof(value) > 40:
        return "HOSTILE_VALUE", None
    if type(value) is int or type(value) is float:
        number = float(value)
        if number != number or number in {float("inf"), float("-inf")}:
            return "QTY_INVALID", None
        if positive and number <= 0:
            return "QTY_INVALID", None
        if not positive and number < 0:
            return "QTY_INVALID", None
        return None, number
    return "HOSTILE_VALUE", None


def _refuse(reason: str) -> dict:
    return {"ok": False, "reason": reason, "record": None}


def pack_capture(capture) -> dict:
    """Copy one board into a fixed record. Missing clocks and sizes stay absent.

    A naive clock is refused. It is not given a ``+09:00`` offset. ``poll_seq``
    is stored as the loop counter only. ``available_at`` is not copied.
    """
    if type(capture) is not dict:
        return _refuse("BOARD_INPUT_INVALID")
    if SAFETY_KEYS.intersection(capture) and any(capture.get(key) is True for key in SAFETY_KEYS):
        return _refuse("SAFETY_FLAG_REFUSED")
    if capture.get("capture_authenticated") not in (None, False):
        return _refuse("CAPTURE_AUTHENTICATION_REFUSED")
    if capture.get("fill_missing_with_zero") not in (None, False):
        return _refuse("QTY_ZERO_FILL_REFUSED")
    symbol = capture.get("symbol")
    market = capture.get("market")
    if type(symbol) is not str or not symbol or len(symbol) > _SYMBOL_LIMIT:
        return _refuse("SYMBOL_ABSENT")
    if market not in {"TSE", "JNX"}:
        return _refuse("MARKET_INVALID")
    poll = capture.get("poll_seq")
    if type(poll) is bool or type(poll) is not int or sys.getsizeof(poll) > 40 or not 1 <= poll <= 10**12:
        return _refuse("POLL_SEQ_INVALID")
    source = capture.get("source", "ms2-nonblocking-handoff-0.1")
    if type(source) is not str or not source.strip() or len(source) > _SOURCE_LIMIT:
        return _refuse("SOURCE_ABSENT")
    if source == CURRENT_WATCHER_SOURCE:
        return _refuse("WATCHER_SOURCE_HAS_NO_SIDECAR")
    observation_id = capture.get("observation_id")
    if observation_id is not None:
        if type(observation_id) is not str or not observation_id or len(observation_id) > _ID_LIMIT:
            return _refuse("OBSERVATION_ID_ABSENT")
    timezone = capture.get("timezone")
    if timezone is not None:
        if type(timezone) is not str or timezone in {"JST", "Asia/Tokyo"} or "Tokyo" in timezone or "Japan" in timezone:
            return _refuse("TIMEZONE_NOT_GUESSED")
    for name in ("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at"):
        problem = _clock_problem(capture.get(name)) if name in capture else None
        if problem:
            return _refuse(problem)
    if "available_at" in capture and capture.get("available_at") is not None:
        problem = _clock_problem(capture.get("available_at"))
        if problem and problem != "TIMEZONE_NOT_GUESSED":
            return _refuse(problem)
    levels = capture.get("levels")
    if type(levels) is not list:
        return _refuse("BOARD_INPUT_INVALID")
    if len(levels) > 10:
        return _refuse("DEPTH_LIMIT")
    numbers = []
    parsed_levels = []
    for item in levels:
        if type(item) is not dict:
            return _refuse("LEVEL_INVALID")
        number = item.get("Level", item.get("level"))
        if type(number) is not int or not 1 <= number <= 10:
            return _refuse("LEVEL_NUMBER_ABSENT")
        numbers.append(number)
        row = {"level": number}
        for price_key, out_key in (("AskPrice", "ask"), ("BidPrice", "bid"), ("ask", "ask"), ("bid", "bid")):
            if price_key in item and out_key not in row:
                raw = item.get(price_key)
                if raw is None:
                    row[out_key] = None
                else:
                    reason, number_value = _number(raw, positive=True)
                    if reason:
                        return _refuse(reason if reason != "HOSTILE_VALUE" else "BOOK_VALUE_TYPE_INVALID")
                    row[out_key] = number_value
        for qty_key, out_key in (("AskQty", "ask_qty"), ("BidQty", "bid_qty"), ("ask_qty", "ask_qty"), ("bid_qty", "bid_qty")):
            if qty_key in item and out_key not in row:
                raw = item.get(qty_key)
                if raw is None:
                    row[out_key] = None
                    row[out_key + "_known"] = False
                else:
                    reason, number_value = _number(raw, positive=False)
                    if reason:
                        return _refuse("QTY_INVALID" if reason != "HOSTILE_VALUE" else "BOOK_VALUE_TYPE_INVALID")
                    row[out_key] = number_value
                    row[out_key + "_known"] = True
        read_at = item.get("read_at", item.get("ReadAt"))
        if read_at is not None:
            problem = _clock_problem(read_at)
            if problem:
                return _refuse(problem)
            row["read_at"] = read_at.strip()
        parsed_levels.append(row)
    if numbers and numbers != list(range(1, len(numbers) + 1)):
        return _refuse("LEVEL_SEQUENCE_GAP")
    freshness = capture.get("data_freshness", "UNKNOWN")
    if freshness not in _FRESHNESS:
        return _refuse("FRESHNESS_INVALID")
    gap = capture.get("gap")
    gap_flag = None
    if gap is not None:
        if type(gap) is not dict:
            return _refuse("GAP_DIAG_INVALID")
        for key in ("window_size", "overlap_with_prev", "new_appended"):
            raw = gap.get(key)
            if type(raw) is not int or raw < 0 or sys.getsizeof(raw) > 40:
                return _refuse("GAP_DIAG_INVALID")
        if type(gap.get("prev_poll_nonempty")) is not bool:
            return _refuse("GAP_DIAG_INVALID")
        if "suspected_gap" in gap and type(gap.get("suspected_gap")) is not bool:
            return _refuse("GAP_DIAG_INVALID")
        gap_flag = gap.get("suspected_gap")
    buf = bytearray(RECORD_SIZE)
    buf[0:4] = MAGIC
    buf[4] = 1
    buf[5] = len(parsed_levels)
    buf[6] = _FRESHNESS.index(freshness)
    flags = 0
    if "available_at" in capture and capture.get("available_at") is not None:
        flags |= 1
    if capture.get("snapshot_atomic") is True:
        flags |= 2
    if capture.get("exchange_sequence") is not None or capture.get("sequence_basis") == "EXCHANGE":
        flags |= 4
    if "synthetic" in source:
        flags |= 8
    buf[7] = flags
    struct_poll = int(poll).to_bytes(8, "little")
    buf[8:16] = struct_poll
    if not _put_text(buf, 16, _SYMBOL_LIMIT, symbol):
        return _refuse("SYMBOL_ABSENT")
    if not _put_text(buf, 48, 8, market):
        return _refuse("MARKET_INVALID")
    if observation_id is not None and not _put_text(buf, 56, _ID_LIMIT, observation_id):
        return _refuse("OBSERVATION_ID_ABSENT")
    if not _put_text(buf, 136, _SOURCE_LIMIT, source):
        return _refuse("SOURCE_ABSENT")
    clock_at = 256
    for name in ("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at"):
        raw = capture.get(name)
        if type(raw) is str and raw:
            if not _put_text(buf, clock_at, _CLOCK_LIMIT, raw.strip()):
                return _refuse("TIMESTAMP_INVALID")
        clock_at += _CLOCK_LIMIT
    level_at = clock_at
    for row in parsed_levels:
        ask_known = 1 if "ask" in row and row["ask"] is not None else 0
        bid_known = 1 if "bid" in row and row["bid"] is not None else 0
        ask_qty_known = 1 if row.get("ask_qty_known") else 0
        bid_qty_known = 1 if row.get("bid_qty_known") else 0
        buf[level_at] = row["level"]
        buf[level_at + 1] = ask_known | (bid_known << 1) | (ask_qty_known << 2) | (bid_qty_known << 3)
        struct.pack_into(
            "<dddd",
            buf,
            level_at + 8,
            float(row["ask"]) if ask_known else 0.0,
            float(row["bid"]) if bid_known else 0.0,
            float(row["ask_qty"]) if ask_qty_known else 0.0,
            float(row["bid_qty"]) if bid_qty_known else 0.0,
        )
        read_at = row.get("read_at") or ""
        if read_at and not _put_text(buf, level_at + 40, _CLOCK_LIMIT, read_at):
            return _refuse("TIMESTAMP_INVALID")
        level_at += 80
    if gap is not None:
        buf[1800] = 1
        buf[1801] = 0 if gap_flag is None else (1 if gap_flag else 2)
        buf[1802] = 1 if gap.get("prev_poll_nonempty") else 0
        buf[1808:1812] = int(gap["window_size"]).to_bytes(4, "little")
        buf[1812:1816] = int(gap["overlap_with_prev"]).to_bytes(4, "little")
        buf[1816:1820] = int(gap["new_appended"]).to_bytes(4, "little")
    if level_at > 1800:
        return _refuse("RECORD_LAYOUT")
    return {"ok": True, "reason": "PACKED", "record": bytes(buf), "flags": flags}


def unpack_capture(blob: bytes) -> dict | None:
    """Rebuild the writer capture. Exchange order and available_at stay absent."""
    if len(blob) != RECORD_SIZE or blob[0:4] != MAGIC or blob[4] != 1:
        return None
    import struct
    count = blob[5]
    freshness = _FRESHNESS[blob[6]] if blob[6] < len(_FRESHNESS) else "UNKNOWN"
    poll = int.from_bytes(blob[8:16], "little")
    symbol = _get_text(blob, 16, _SYMBOL_LIMIT)
    market = _get_text(blob, 48, 8)
    observation_id = _get_text(blob, 56, _ID_LIMIT)
    source = _get_text(blob, 136, _SOURCE_LIMIT)
    clocks = {}
    clock_at = 256
    for name in ("event_time", "watcher_observed_at", "received_at", "read_started_at", "read_finished_at"):
        text = _get_text(blob, clock_at, _CLOCK_LIMIT)
        if text:
            clocks[name] = text
        clock_at += _CLOCK_LIMIT
    levels = []
    level_at = clock_at
    for _ in range(count):
        number = blob[level_at]
        mask = blob[level_at + 1]
        ask, bid, ask_qty, bid_qty = struct.unpack_from("<dddd", blob, level_at + 8)
        row = {"Level": number}
        if mask & 1:
            row["AskPrice"] = ask
        if mask & 2:
            row["BidPrice"] = bid
        if mask & 4:
            row["AskQty"] = ask_qty
        else:
            row["AskQty"] = None
        if mask & 8:
            row["BidQty"] = bid_qty
        else:
            row["BidQty"] = None
        read_at = _get_text(blob, level_at + 40, _CLOCK_LIMIT)
        if read_at:
            row["read_at"] = read_at
        levels.append(row)
        level_at += 80
    capture = {
        "symbol": symbol,
        "market": market,
        "poll_seq": poll,
        "kind": "BOARD_SNAPSHOT",
        "source": source,
        "sequence_basis": "POLL",
        "order_proven": False,
        "read_method": "SEQUENTIAL_CELL",
        "snapshot_atomic": False,
        "levels": levels,
        "data_freshness": freshness,
    }
    if observation_id:
        capture["observation_id"] = observation_id
    capture.update(clocks)
    if clocks.get("event_time"):
        capture["event_time_basis"] = "EXCHANGE_SUPPLIED"
    if blob[1800] == 1:
        gap = {
            "window_size": int.from_bytes(blob[1808:1812], "little"),
            "overlap_with_prev": int.from_bytes(blob[1812:1816], "little"),
            "prev_poll_nonempty": bool(blob[1802]),
            "new_appended": int.from_bytes(blob[1816:1820], "little"),
        }
        if blob[1801] == 1:
            gap["suspected_gap"] = True
        elif blob[1801] == 2:
            gap["suspected_gap"] = False
        capture["gap"] = gap
    return capture


def _hooks_for(fault: int) -> dict | None:
    if fault == FAULT_DISK_FULL:
        def _write(fd, payload):
            raise OSError(errno.ENOSPC, "No space left on device")
        return {"write": _write}
    if fault == FAULT_PERMISSION:
        def _open(*args, **kwargs):
            raise PermissionError(errno.EACCES, "Permission denied")
        return {"open": _open}
    if fault == FAULT_FILE_LOCK:
        def _flock(fd, op):
            raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")
        return {"flock": _flock}
    return None


def _classify(report: dict) -> str:
    reasons = set(report.get("reasons") or [])
    if report.get("writes_performed"):
        return "APPENDED"
    if "DISK_FULL" in reasons:
        return "DISK_FULL"
    if "WRITE_LOCKED" in reasons:
        return "WRITE_LOCKED"
    if "WRITE_FAILED" in reasons:
        return "WRITE_FAILED"
    if "DATA_CORRUPT" in reasons:
        return "DATA_CORRUPT"
    if "IDEMPOTENT_REPLAY" in reasons or "DUPLICATE_POLL" in reasons or "DUPLICATE_CONFLICT" in reasons:
        return "DUPLICATE"
    return "FAIL_CLOSED"


def _worker_loop(buf, repo_root: str, relative: str) -> None:
    _store(buf, _OFF_WORKER_PID, os.getpid())
    _store(buf, _OFF_HEARTBEAT, time.monotonic_ns())
    while True:
        fault = _load(buf, _OFF_FAULT)
        if fault == FAULT_CRASH:
            os._exit(97)
        if fault == FAULT_STALL:
            if _load(buf, _OFF_FLAGS) & (_FLAG_STOP | _FLAG_KILL):
                _reason(buf, "STOPPED")
                return
            time.sleep(0.05)
            continue
        _store(buf, _OFF_HEARTBEAT, time.monotonic_ns())
        flags = _load(buf, _OFF_FLAGS)
        if flags & (_FLAG_STOP | _FLAG_KILL):
            _reason(buf, "STOPPED")
            return
        if fault == FAULT_BLOCK_UNCHECKED:
            time.sleep(30)
            continue
        write_index = _load(buf, _OFF_WRITE)
        read_index = _load(buf, _OFF_READ)
        if write_index == read_index or fault == FAULT_HOLD:
            time.sleep(0.002)
            continue
        slot = SLOT_BASE + (read_index % QUEUE_CAPACITY) * RECORD_SIZE
        blob = bytes(buf[slot:slot + RECORD_SIZE])
        if fault == FAULT_BLOCK_IO:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if _load(buf, _OFF_FLAGS) & (_FLAG_STOP | _FLAG_KILL):
                    _store(buf, _OFF_READ, read_index + 1)
                    _reason(buf, "ABANDONED")
                    return
                _store(buf, _OFF_HEARTBEAT, time.monotonic_ns())
                time.sleep(0.02)
        capture = unpack_capture(blob)
        if capture is None:
            _add(buf, _OFF_FAIL_CLOSED)
            _reason(buf, "RECORD_CORRUPT")
        else:
            report = record_captured_observation(
                repo_root, relative, capture, enabled=True, hooks=_hooks_for(fault),
            )
            kind = _classify(report)
            _reason(buf, kind)
            if kind == "APPENDED":
                _add(buf, _OFF_DURABLE)
            elif kind == "DUPLICATE":
                _add(buf, _OFF_DUPLICATES)
            elif kind in {"DISK_FULL", "WRITE_FAILED", "WRITE_LOCKED"}:
                _add(buf, _OFF_FAILURES)
            else:
                _add(buf, _OFF_FAIL_CLOSED)
            if report.get("com_reads_added"):
                _add(buf, _OFF_COM_READS, int(report["com_reads_added"]))
        _store(buf, _OFF_READ, read_index + 1)


def _worker_entry(shm_name: str, repo_root: str, relative: str) -> None:
    shm = shared_memory.SharedMemory(name=shm_name)
    try:
        _worker_loop(shm.buf, repo_root, relative)
    finally:
        shm.close()


def _quarantine_unpublished(root: Path, generation: int) -> int:
    private = root / "data" / "private" / "ms2_sidecar"
    if not private.exists():
        return 0
    found = []
    for path in private.glob(".*.tmp"):
        if path.is_file() and not path.is_symlink():
            found.append(path)
    unpublished = private / "runtime" / "unpublished"
    if unpublished.is_dir() and not unpublished.is_symlink():
        for path in unpublished.iterdir():
            if path.is_file() and not path.is_symlink():
                found.append(path)
    if not found:
        return 0
    dest = private / "quarantine" / str(generation)
    dest.mkdir(parents=True, exist_ok=True)
    os.chmod(dest, 0o700)
    moved = 0
    for path in found:
        target = dest / f"{moved}-{path.name}"
        os.replace(path, target)
        os.chmod(target, 0o600)
        moved += 1
    return moved


class HandoffSession:
    """One producer. The disk worker is another process. Default start writes nothing."""

    def __init__(self, status: str, reason: str):
        self.status = status
        self.reason = reason
        self._shm = None
        self._process = None
        self._lock_fd = None
        self._refused = 0
        self._invalid = 0
        self._timezone_refused = 0
        self._stopped = False
        self._repo = None

    def submit(self, capture) -> dict:
        """Enqueue a fixed copy or drop it. This call does not wait for disk."""
        started = time.monotonic_ns()
        result = self._submit(capture, started)
        elapsed = time.monotonic_ns() - started
        result["elapsed_ns"] = elapsed
        result["com_reads_added"] = 0
        result["blocking_syscall"] = False
        result["hard_realtime_guaranteed"] = False
        if self._shm is not None:
            buf = self._shm.buf
            _add(buf, _OFF_SUBMIT_COUNT)
            _store(buf, _OFF_LAST_ELAPSED_NS, elapsed)
            current = _load(buf, _OFF_MAX_ELAPSED_NS)
            if elapsed > current:
                _store(buf, _OFF_MAX_ELAPSED_NS, elapsed)
        return result

    def _submit(self, capture, started: int) -> dict:
        if self.status == "DISABLED":
            self._refused += 1
            return self._result("DISABLED", "SIDECAR_DISABLED", started)
        if self._stopped or self.status in {"STOPPED", "START_FAILED"}:
            return self._result("WORKER_STOPPED", "WORKER_STOPPED", started)
        if self.status != "STARTED" or self._shm is None:
            self._refused += 1
            return self._result("REFUSED", self.reason or "NOT_STARTED", started)
        buf = self._shm.buf
        if _load(buf, _OFF_FLAGS) & _FLAG_KILL:
            _add(buf, _OFF_KILL_DROPS)
            return self._result("KILL_SWITCH", "KILL_SWITCH", started)
        heartbeat = _load(buf, _OFF_HEARTBEAT)
        if heartbeat and time.monotonic_ns() - heartbeat > STALL_AFTER_NS:
            _add(buf, _OFF_STALL_SEEN)
            alive = self._process.is_alive() if self._process is not None else False
            if not alive:
                _add(buf, _OFF_DEAD_DROPS)
                return self._result("WORKER_DEAD", "WORKER_DEAD", started)
        write_index = _load(buf, _OFF_WRITE)
        read_index = _load(buf, _OFF_READ)
        if write_index - read_index >= QUEUE_CAPACITY:
            _add(buf, _OFF_DROPPED)
            return self._result("DROPPED", DROP_POLICY, started)
        packed = pack_capture(capture)
        if not packed["ok"]:
            self._refused += 1
            if packed["reason"] in {"QTY_INVALID", "BOOK_VALUE_TYPE_INVALID"}:
                self._invalid += 1
            if packed["reason"] == "TIMEZONE_NOT_GUESSED":
                self._timezone_refused += 1
            return self._result("REFUSED", packed["reason"], started)
        slot = SLOT_BASE + (write_index % QUEUE_CAPACITY) * RECORD_SIZE
        record = packed["record"]
        buf[slot:slot + RECORD_SIZE] = record
        _store(buf, _OFF_WRITE, write_index + 1)
        _add(buf, _OFF_QUEUED)
        return self._result("ACCEPTED", "QUEUED", started)

    def _result(self, status: str, reason: str, started: int) -> dict:
        depth = 0
        if self._shm is not None:
            buf = self._shm.buf
            depth = _load(buf, _OFF_WRITE) - _load(buf, _OFF_READ)
        return {
            "status": status,
            "reason": reason,
            "queue_depth": depth,
            "queue_capacity": QUEUE_CAPACITY,
            "drop_policy": DROP_POLICY,
            "elapsed_ns": time.monotonic_ns() - started,
        }

    def set_fault(self, fault: int) -> None:
        if self._shm is not None:
            _store(self._shm.buf, _OFF_FAULT, int(fault))

    def trip_kill_switch(self) -> None:
        if self._shm is not None:
            flags = _load(self._shm.buf, _OFF_FLAGS)
            _store(self._shm.buf, _OFF_FLAGS, flags | _FLAG_KILL)

    def metrics(self) -> dict:
        buf = None if self._shm is None else self._shm.buf
        body = {
            "status": self.status,
            "queued": 0 if buf is None else _load(buf, _OFF_QUEUED),
            "durable": 0 if buf is None else _load(buf, _OFF_DURABLE),
            "dropped_newest": 0 if buf is None else _load(buf, _OFF_DROPPED),
            "failures": 0 if buf is None else _load(buf, _OFF_FAILURES),
            "fail_closed": 0 if buf is None else _load(buf, _OFF_FAIL_CLOSED),
            "duplicates": 0 if buf is None else _load(buf, _OFF_DUPLICATES),
            "stall_seen": 0 if buf is None else _load(buf, _OFF_STALL_SEEN),
            "stale_discarded": 0 if buf is None else _load(buf, _OFF_STALE_DISCARDED),
            "dead_drops": 0 if buf is None else _load(buf, _OFF_DEAD_DROPS),
            "kill_drops": 0 if buf is None else _load(buf, _OFF_KILL_DROPS),
            "com_reads_added": 0 if buf is None else _load(buf, _OFF_COM_READS),
            "lock_timeouts": 0 if buf is None else _load(buf, _OFF_LOCK_TIMEOUTS),
            "submit_count": 0 if buf is None else _load(buf, _OFF_SUBMIT_COUNT),
            "max_elapsed_ns": 0 if buf is None else _load(buf, _OFF_MAX_ELAPSED_NS),
            "last_reason": "" if buf is None else _read_reason(buf),
            "worker_pid": 0 if buf is None else _load(buf, _OFF_WORKER_PID),
            "generation": 0 if buf is None else _load(buf, _OFF_GENERATION),
            "refused": self._refused,
            "invalid_quantity": self._invalid,
            "timezone_not_guessed": self._timezone_refused,
            "queue_capacity": QUEUE_CAPACITY,
            "drop_policy": DROP_POLICY,
            "restart_policy": RESTART_POLICY,
            "retry_policy": RETRY_POLICY,
            "worker_alive": bool(self._process.is_alive()) if self._process is not None else False,
            "hard_realtime_guaranteed": False,
            "live_watcher_connection": LIVE_WATCHER_CONNECTION,
        }
        return body

    def stop(self, timeout_s: float = STOP_TIMEOUT_S) -> dict:
        """Ask the worker to leave, then kill it if it is still alive."""
        started = time.monotonic()
        abandoned = 0
        killed = False
        if self._shm is not None:
            buf = self._shm.buf
            flags = _load(buf, _OFF_FLAGS)
            _store(buf, _OFF_FLAGS, flags | _FLAG_STOP | _FLAG_KILL)
            abandoned = _load(buf, _OFF_WRITE) - _load(buf, _OFF_READ)
        if self._process is not None and self._process.is_alive():
            self._process.join(timeout_s)
            if self._process.is_alive():
                self._process.kill()
                killed = True
                self._process.join(0.05)
        self._stopped = True
        self.status = "STOPPED"
        self._close_handles()
        return {
            "status": "STOPPED",
            "abandoned": abandoned,
            "killed": killed,
            "elapsed_s": time.monotonic() - started,
            "timeout_s": timeout_s,
            "restart_policy": RESTART_POLICY,
        }

    def _close_handles(self) -> None:
        if self._shm is not None:
            self._shm.close()
            try:
                self._shm.unlink()
            except FileNotFoundError:
                pass
            self._shm = None
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(self._lock_fd)
            self._lock_fd = None


def start_handoff(repo_root, relative: str | None = None, *, enabled: bool = False, fault: int = FAULT_NONE) -> HandoffSession:
    """Start the worker only when ``enabled`` is exactly True. The default writes nothing."""
    if enabled is not True or not relative:
        return HandoffSession("DISABLED", "SIDECAR_DISABLED")
    root = Path(repo_root)
    runtime = root / "data" / "private" / "ms2_sidecar" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    unpublished = runtime / "unpublished"
    unpublished.mkdir(exist_ok=True)
    lock_path = runtime / "handoff.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        session = HandoffSession("ALREADY_RUNNING", "DUPLICATE_START")
        return session
    generation = time.monotonic_ns() & ((1 << 64) - 1)
    discarded = _quarantine_unpublished(root, generation)
    name = "n" + uuid.uuid4().hex[:16]
    shm = shared_memory.SharedMemory(create=True, size=SHM_SIZE, name=name)
    buf = shm.buf
    buf[:] = b"\0" * SHM_SIZE
    _store(buf, _OFF_GENERATION, generation)
    _store(buf, _OFF_STALE_DISCARDED, discarded)
    _store(buf, _OFF_FAULT, int(fault))
    session = HandoffSession("STARTING", "STARTING")
    session._shm = shm
    session._lock_fd = fd
    session._repo = str(root)
    context = get_context("spawn")
    process = context.Process(target=_worker_entry, args=(name, str(root), relative), daemon=False)
    try:
        process.start()
    except Exception:
        session.status = "START_FAILED"
        session.reason = "WORKER_START_FAILED"
        session.stop(0.05)
        return session
    session._process = process
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if _load(buf, _OFF_HEARTBEAT) and process.is_alive():
            session.status = "STARTED"
            session.reason = "STARTED"
            return session
        time.sleep(0.01)
    session.status = "START_FAILED"
    session.reason = "WORKER_START_FAILED"
    session.stop(0.05)
    return session


def watcher_surface(repo_root=None) -> dict:
    """Read-only count of the existing board loop. This does not import or run the watcher."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    path = root / WATCHER_RELATIVE
    text = path.read_text(encoding="utf-8")
    calls = text.count("Read-BoardDepth")
    return {
        "path": WATCHER_RELATIVE,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "read_board_depth_mentions": calls,
        "existing_board_com_reads_per_poll": EXISTING_BOARD_COM_READS,
        "extra_com_reads": EXTRA_COM_READS,
        "modified": False,
    }


def acceptance_verdict(metrics: dict | None = None) -> dict:
    """Offline isolation can pass while a hard real-time claim stays blocked."""
    measured = None if metrics is None else metrics.get("max_elapsed_ns")
    within = None if measured is None else measured <= SUBMIT_DEADLINE_NS
    return {
        "offline_handoff": "PASS" if within is True else "NOT_MEASURED" if within is None else "FAIL",
        "measured_max_elapsed_ns": measured,
        "submit_deadline_ns": SUBMIT_DEADLINE_NS,
        "hard_realtime_guarantee": "P0_BLOCKED",
        "hard_realtime_reason": "CPYTHON_USERSPACE_ON_GENERAL_PURPOSE_OS",
        "live_watcher_connection": LIVE_WATCHER_CONNECTION,
        "windows_acceptance": "NOT_VERIFIED",
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
    }


def main(argv=None) -> int:
    payload = {
        "contract": handoff_contract(),
        "windows_acceptance": windows_acceptance_checklist(),
        "verdict": acceptance_verdict(),
        "watcher": watcher_surface(),
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
