"""Bounded non-blocking handoff for an already-copied MS2 board.

Issue #352. Draft PR #351 can notice that a synchronous writer exceeded 50ms
only after that writer returns. A stalled disk write still holds the caller
for the whole stall. This module does not edit the watcher and does not open
Excel. It copies a fixed-size record into a preallocated shared-memory slot
and returns. A separate process performs the private JSONL write.

The producer path does not take a lock, does not call ``json.dumps``, and
does not call a blocking write. Queue capacity is fixed. When it is full the
incoming record is dropped and counted. The worker never reads Excel.
The 2048-byte slot layout lives in ``scripts/ms2_bridge_record.py`` so a
PowerShell producer shares the same slot with the spawned durable worker.

This is not a hard real-time guarantee. CPython on a general-purpose OS can
still be delayed by the scheduler. Live watcher connection stays blocked.
"""
from __future__ import annotations

import ctypes
import errno
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

from scripts import ms2_ipc_integrity as ipc
from scripts.ms2_bridge_record import RECORD_SIZE, pack_capture, unpack_capture
from scripts.ms2_offline_observation_writer import (
    record_captured_observation, _lock_native, _unlock_native,
    resolve_write_path, _is_reparse, exclusive_writer_lock,
)

HANDOFF_VERSION = "ms2-nonblocking-handoff-0.1"
AUDITED_MAIN_SHA = "b235fde33a47975ca771e3d6c2b4d0e4b613d600"
STACK_HEAD = "b7ed5ae7f2a1eaca7aa13290730b7058958f2ac5"
WATCHER_RELATIVE = "ms2_live/Kioxia_RSS_Live_Watcher.ps1"
QUEUE_CAPACITY = 8
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
FAULT_WRITE_INFLIGHT = 10  # Pause inside temp write until harness releases.
FAULT_BEFORE_REPLACE = 11
FAULT_AFTER_REPLACE = 12

FAULT_CONSUMER_GATE = 9  # synthetic crash-during-read injection


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
        "same_user_authentication": "SAME_USER_AUTH_UNRESOLVED",
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


def _owner_io_hooks(buf, fault, owner_dead):
    """Fence *before* replace; cannot cancel an already-entered OS syscall.

    Fault pauses model a syscall which cannot observe parent death until it
    returns. Only the harness can release it. Lease remains held throughout.
    """
    hooks = dict(_hooks_for(fault) or {})
    def pause(code, reason):
        if fault == code:
            _reason(buf, reason)
            while _load(buf, _OFF_FAULT) == code:
                time.sleep(.005)
    original_write = hooks.get("write", os.write)
    def write(fd, payload):
        if fault == FAULT_WRITE_INFLIGHT:
            # A partial temp is real; published JSONL is untouched.
            amount = os.write(fd, payload[:max(1, len(payload)//2)])
            pause(FAULT_WRITE_INFLIGHT, "IO_INFLIGHT")
            return amount
        return original_write(fd, payload)
    def replace(src, dst):
        pause(FAULT_BEFORE_REPLACE, "BEFORE_REPLACE")
        if owner_dead() or _load(buf, _OFF_FLAGS) & (_FLAG_STOP | _FLAG_KILL):
            raise OSError(errno.ECANCELED, "OWNER_COMMIT_REFUSED")
        os.replace(src, dst)
        pause(FAULT_AFTER_REPLACE, "AFTER_REPLACE")
        # Never undo an already-published valid record on owner death.
    hooks.update(write=write, replace=replace)
    return hooks


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


def _worker_loop(buf, repo_root: str, relative: str, generation: int | None = None) -> None:
    generation = _load(buf, _OFF_GENERATION) if generation is None else generation
    ipc.prepare(generation)
    _store(buf, _OFF_WORKER_PID, os.getpid())
    _store(buf, _OFF_HEARTBEAT, time.monotonic_ns())
    gate_busy_since = None
    next_read = 0
    write_highwater = 0
    from multiprocessing import parent_process
    parent = parent_process()
    def owner_dead():
        if parent is None:  # Direct/unit invocation has no spawned owner.
            return False
        if parent.is_alive():
            return False
        _store(buf, _OFF_FLAGS, _load(buf, _OFF_FLAGS) | _FLAG_STOP | _FLAG_KILL)
        _reason(buf, "OWNER_DEAD_QUARANTINED")
        return True
    while True:
        fault = _load(buf, _OFF_FAULT)
        if fault == FAULT_BLOCK_UNCHECKED:
            time.sleep(30)  # Deliberately uninterruptible synthetic I/O.
            continue
        if owner_dead(): return
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
        if (_load(buf, _OFF_WRITE) == _load(buf, _OFF_READ) or fault == FAULT_HOLD):
            try:
                write_index, read_index = ipc.validate_header(buf, generation)
                if read_index != next_read or write_index < write_highwater:
                    raise ValueError("IPC_INDEX_ROLLBACK")
            except ValueError as exc:
                _add(buf, _OFF_FAIL_CLOSED)
                _store(buf, _OFF_FLAGS, flags | _FLAG_KILL)
                _reason(buf, str(exc))
                return
            # Idle/HOLD never acquires a free gate or steals a just-released
            # publisher gate. Seeing it free breaks the busy-duration interval.
            now = time.monotonic_ns()
            if struct.unpack_from("<I", buf, ipc.GATE)[0] == 0:
                gate_busy_since = None
            elif gate_busy_since is None:
                gate_busy_since = now
            elif now - gate_busy_since > STALL_AFTER_NS:
                _add(buf, _OFF_FAIL_CLOSED)
                _store(buf, _OFF_FLAGS, flags | _FLAG_KILL)
                _reason(buf, "IPC_GATE_ABANDONED")
                return
            time.sleep(0.002)
            continue
        if not ipc.acquire(buf):
            now = time.monotonic_ns()
            if gate_busy_since is None:
                gate_busy_since = now
            if now - gate_busy_since > STALL_AFTER_NS:
                _add(buf, _OFF_FAIL_CLOSED)
                _store(buf, _OFF_FLAGS, flags | _FLAG_KILL)
                _reason(buf, "IPC_GATE_ABANDONED")
                return
            time.sleep(0.002)
            continue
        gate_busy_since = None
        try:
            fault = _load(buf, _OFF_FAULT)
            write_index, read_index = ipc.validate_header(buf, generation)
            if read_index != next_read or write_index < write_highwater:
                raise ValueError("IPC_INDEX_ROLLBACK")
            write_highwater = write_index
            if fault == FAULT_CONSUMER_GATE:
                time.sleep(30)
            if write_index == read_index or fault == FAULT_HOLD:
                blob = None
            else:
                blob = ipc.read_slot(buf, generation, read_index)
                # Claim the immutable local copy while holding the common gate.
                _store(buf, _OFF_READ, read_index + 1)
                next_read = read_index + 1
        except ValueError as exc:
            _add(buf, _OFF_FAIL_CLOSED)
            _store(buf, _OFF_FLAGS, flags | _FLAG_KILL)
            _reason(buf, str(exc))
            return
        finally:
            ipc.release(buf)
        if blob is None:
            time.sleep(0.002)
            continue
        if owner_dead(): return
        if _load(buf, _OFF_FLAGS) & (_FLAG_STOP | _FLAG_KILL):
            _reason(buf, "STOPPED")
            return
        if fault == FAULT_BLOCK_IO:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if owner_dead(): return
                if _load(buf, _OFF_FLAGS) & (_FLAG_STOP | _FLAG_KILL):
                    _reason(buf, "ABANDONED")
                    return
                _store(buf, _OFF_HEARTBEAT, time.monotonic_ns())
                time.sleep(0.02)
        if owner_dead(): return
        capture = unpack_capture(blob)
        if capture is None:
            _add(buf, _OFF_FAIL_CLOSED)
            _reason(buf, "RECORD_CORRUPT")
        else:
            report = record_captured_observation(
                repo_root, relative, capture, enabled=True, hooks=_owner_io_hooks(buf, fault, owner_dead),
            )
            if owner_dead(): return
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


def _worker_entry(shm_name: str, repo_root: str, relative: str, generation: int | None = None) -> None:
    # The child holds a separate lease. If its owner crashes, a new owner
    # cannot start until this worker exits, even while disk IO is stalled.
    runtime = Path(repo_root) / "data/private/ms2_sidecar/runtime"
    fd = _take_lifecycle_lock(runtime / "worker.lock")
    shm = None
    try:
        shm = shared_memory.SharedMemory(name=shm_name)
        _worker_loop(shm.buf, repo_root, relative, generation)
    finally:
        if shm is not None:
            shm.close()  # Attached worker never unlinks someone else's mapping.
        ipc.close_generation(generation)
        _drop_lifecycle_lock(fd)


def _take_lifecycle_lock(path: Path) -> int:
    if _is_reparse(path):
        raise ValueError("PRIVATE_PATH_LINK")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_native(fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _drop_lifecycle_lock(fd: int) -> None:
    try:
        _unlock_native(fd)
    finally:
        os.close(fd)


def _quarantine_unpublished(root: Path, generation: int) -> int:
    private = root / "data/private/ms2_sidecar"
    with exclusive_writer_lock(private):
        return _quarantine_unpublished_locked(root, generation)


def _quarantine_unpublished_locked(root: Path, generation: int) -> int:
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
        self._owns_mapping = False
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
        from scripts.ms2_ps_python_bridge import publish_into
        return publish_into(buf, packed["record"], self._generation)

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
        exit_verified = self._process is None or not self._process.is_alive()
        self._stopped = True
        self.status = "STOPPED" if exit_verified else "STOP_PENDING"
        if exit_verified:
            self._close_handles()
        return {
            "status": self.status,
            "worker_exit_verified": exit_verified,
            "abandoned": abandoned,
            "killed": killed,
            "elapsed_s": time.monotonic() - started,
            "timeout_s": timeout_s,
            "restart_policy": RESTART_POLICY,
        }

    def _close_handles(self) -> None:
        ipc.close_generation(getattr(self, "_generation", 0))
        if self._shm is not None:
            shm = self._shm
            self._shm = None
            shm.close()
            if self._owns_mapping and os.name != "nt":
                try:
                    shm.unlink()
                except FileNotFoundError:
                    pass
            self._owns_mapping = False
        if self._lock_fd is not None:
            fd = self._lock_fd
            self._lock_fd = None
            _drop_lifecycle_lock(fd)


def start_handoff(repo_root, relative: str | None = None, *, enabled: bool = False,
                  fault: int = FAULT_NONE, map_name: str | None = None,
                  require_process_authentication: bool = False) -> HandoffSession:
    """Offline startup only. No lock wait, no retry, one spawn, bounded readiness."""
    if enabled is not True or not relative:
        return HandoffSession("DISABLED", "SIDECAR_DISABLED")
    if require_process_authentication:
        return HandoffSession("P0_BLOCKED", "SAME_USER_AUTH_UNRESOLVED")
    session = HandoffSession("STARTING", "STARTING")
    try:
        path = resolve_write_path(repo_root, relative)
        root = Path(repo_root).resolve()
        runtime = path.parent / "runtime"
        if _is_reparse(runtime) or _is_reparse(runtime / "unpublished"):
            raise ValueError("PRIVATE_PATH_LINK")
        runtime.mkdir(parents=True, exist_ok=True)
        os.chmod(runtime, 0o700)
        (runtime / "unpublished").mkdir(exist_ok=True)
        # Shared by both entry points: no parallel bridge/handoff owners.
        session._lock_fd = _take_lifecycle_lock(runtime / "handoff.lock")
        probe_fd = _take_lifecycle_lock(runtime / "worker.lock")
        _drop_lifecycle_lock(probe_fd)
        generation = (time.monotonic_ns() & ((1 << 63) - 1)) or 1
        discarded = _quarantine_unpublished(root, generation)
        name = map_name or ("b" + uuid.uuid4().hex[:11])
        # create=True refuses collisions. We never attach/unlink a colliding map.
        shm = ipc.create_mapping(name, SHM_SIZE)
        session._shm = shm
        session._owns_mapping = True
        ipc.windows_acl_audit(shm.name)
        session._generation = generation
        session.map_name = shm.name
        session._repo = str(root)
        buf = shm.buf
        buf[:] = b"\0" * SHM_SIZE
        from scripts.ms2_ps_python_bridge import stamp_header
        stamp_header(buf, generation)
        _store(buf, _OFF_STALE_DISCARDED, discarded)
        _store(buf, _OFF_FAULT, int(fault))
        from scripts.ms2_ps_python_bridge import publish_into
        context = get_context("spawn")
        process = context.Process(target=_worker_entry, args=(name, str(root), relative, generation), daemon=False)
        try:
            process.start()
        except Exception:
            session.reason = "WORKER_START_FAILED"
            session._close_handles()
            session.status = "START_FAILED"
            return session
        session._process = process
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if _load(buf, _OFF_HEARTBEAT) and process.is_alive():
                session.status = "STARTED"
                session.reason = "STARTED"
                return session
            if not process.is_alive():
                break
            time.sleep(0.01)
        session.stop(0.05)
        session.status = "START_FAILED"
        session.reason = "WORKER_START_FAILED"
        return session
    except BlockingIOError:
        session._close_handles()
        session.status, session.reason = "ALREADY_RUNNING", "DUPLICATE_START"
    except FileExistsError:
        session._close_handles()
        session.status, session.reason = "START_FAILED", "MAPPING_CREATE_FAILED"
    except (OSError, ValueError) as exc:
        session._close_handles()
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).replace("_", "").isalnum() else "STARTUP_REFUSED"
        session.status, session.reason = "START_FAILED", reason
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
