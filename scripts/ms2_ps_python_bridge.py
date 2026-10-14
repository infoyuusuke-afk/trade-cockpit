"""Bounded PowerShell-to-Python slot for an already copied MS2 board.

Issue #354. The live watcher is Windows PowerShell and its 2 second loop is
unchanged. This module does not edit that script, does not launch it, and
does not open Excel.

What crosses the boundary is one 2048-byte record. The Python process that
created the named mapping owns it. PowerShell opens that existing mapping,
copies the record, and publishes the write index. That call does not start
Python, does not open a pipe, and does not take a file lock.

A synchronous ``python.exe`` or pipe on every poll is not this design.

The offline bridge uses the same lifecycle and spawned durable worker on
Windows and Linux. Windows mappings disappear only when the last handle
closes; no attached process may unlink a mapping. A GitHub runner is not the
owner PC. Power-loss durability and Issue #356 IPC integrity remain gates.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import uuid
from multiprocessing import shared_memory
from pathlib import Path

from scripts import ms2_ipc_integrity as ipc
from scripts.ms2_bridge_record import MAGIC, RECORD_SIZE, pack_capture, unpack_capture

BRIDGE_VERSION = "ms2-ps-python-bridge-0.1"
AUDITED_MAIN_SHA = "d72a479816660b41389d0f61c38e4556e88eeb4b"
ISSUE_BASELINE_MAIN_SHA = "16aca17d8fc9c7a3f8618ba8f9471cf814d4b2e5"
STACK_HEAD = "728b45367d0c925fa50d2b73331788eafb8a3e9e"
WATCHER_RELATIVE = "ms2_live/Kioxia_RSS_Live_Watcher.ps1"
WATCHER_SHA256 = "4babc10249c2ebd603b28dfc20542224ce4b7b646fe16111ff398f76d2f60c1b"
PRODUCER_RELATIVE = "scripts/ms2_ps_python_bridge_producer.ps1"
QUEUE_CAPACITY = 8
SLOT_BASE = 4096
SHM_SIZE = SLOT_BASE + QUEUE_CAPACITY * RECORD_SIZE
DROP_POLICY = "DROP_NEWEST"
RESTART_POLICY = "DISCARD_UNPUBLISHED"
RETRY_POLICY = "NO_RETRY"
SUBMIT_DEADLINE_NS = 5_000_000
STOP_TIMEOUT_S = 0.25
STALL_AFTER_NS = 150_000_000
START_METHOD = "spawn"
ATTACH_NAME_CANDIDATES = 3
PROTO_OFFSET = 176

OFF_WRITE = 0
OFF_READ = 8
OFF_DROPPED = 16
OFF_HEARTBEAT = 24
OFF_FLAGS = 32
OFF_QUEUED = 48
OFF_DURABLE = 56
OFF_FAILURES = 64
OFF_FAIL_CLOSED = 72
OFF_STALE_DISCARDED = 96
OFF_FAULT = 104
OFF_GENERATION = 112
OFF_COM_READS = 120
OFF_KILL_DROPS = 144
OFF_SUBMIT_COUNT = 160
OFF_LAST_ELAPSED_NS = 168
OFF_MAX_ELAPSED_NS = 152

FLAG_KILL = 1
FLAG_STOP = 2

FORBIDDEN_PRODUCER_TOKENS = (
    "Excel",
    "Value2",
    "RssOrder",
    "Start-Process",
    "ConvertTo-Json",
    "Get-Content",
    "Out-File",
    "Add-Content",
    "Set-Content",
    "Invoke-WebRequest",
    "Invoke-RestMethod",
    "Start-Sleep",
    "New-Object -ComObject",
    "python",
)


def _atom(buf, offset: int):
    import ctypes
    return ctypes.c_uint64.from_buffer(buf, offset)


def _load(buf, offset: int) -> int:
    return int(_atom(buf, offset).value)


def _store(buf, offset: int, value: int) -> None:
    _atom(buf, offset).value = int(value)


def _add(buf, offset: int, count: int = 1) -> None:
    item = _atom(buf, offset)
    item.value = int(item.value) + count


def bridge_contract() -> dict:
    """Fixed bounds. These do not authorize a watcher edit or a live start."""
    return {
        "bridge_version": BRIDGE_VERSION,
        "audited_main_sha": AUDITED_MAIN_SHA,
        "issue_baseline_main_sha": ISSUE_BASELINE_MAIN_SHA,
        "stack_head": STACK_HEAD,
        "message": "one 2048-byte record of an already copied board",
        "owner": "python process that created the named mapping",
        "producer": "Submit-Ms2PsBridgeRecord",
        "producer_wired_to_watcher": False,
        "poll_path_calls_python": False,
        "poll_path_uses_pipe": False,
        "poll_path_file_lock": False,
        "queue_capacity": QUEUE_CAPACITY,
        "record_bytes": RECORD_SIZE,
        "drop_policy": DROP_POLICY,
        "restart_policy": RESTART_POLICY,
        "retry_policy": RETRY_POLICY,
        "submit_deadline_ns": SUBMIT_DEADLINE_NS,
        "stop_timeout_s": STOP_TIMEOUT_S,
        "start_method": START_METHOD,
        "attach_name_candidates": ATTACH_NAME_CANDIDATES,
        "extra_com_reads": 0,
        "snapshot_atomic": False,
        "sequence_basis": "POLL",
        "hard_realtime_guaranteed": False,
        "hard_realtime_reason": "CPYTHON_USERSPACE_ON_GENERAL_PURPOSE_OS",
        "live_watcher_connection": "P0_BLOCKED",
        "durable_writer_on_windows": "OFFLINE_IMPLEMENTED",
        "durable_writer_via_handoff_worker": "OFFLINE_IMPLEMENTED",
        "durable_writer_blocker": None,
        "durable_writer_owner_pc": "NOT_VERIFIED",
        "power_loss_durability": "NOT_VERIFIED",
        "powershell_memory_mapped_file": "NOT_VERIFIED",
        "windows_owner_pc": "NOT_VERIFIED",
        "windows_sleep_resume": "NOT_VERIFIED",
        "price_voice_sign_runtime": "NOT_VERIFIED",
        "watcher_modified": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "autostart": False,
    }


def _result(status: str, reason: str, started: int, buf=None) -> dict:
    depth = 0
    if buf is not None:
        depth = _load(buf, OFF_WRITE) - _load(buf, OFF_READ)
    return {
        "status": status,
        "reason": reason,
        "queue_depth": depth,
        "queue_capacity": QUEUE_CAPACITY,
        "drop_policy": DROP_POLICY,
        "elapsed_ns": time.monotonic_ns() - started,
        "com_reads_added": 0,
        "blocking_syscall": False,
        "retry": False,
        "hard_realtime_guaranteed": False,
    }


def stamp_header(buf, generation: int) -> None:
    """Mark a mapping the PowerShell opener can recognize without reading a file."""
    buf[PROTO_OFFSET:PROTO_OFFSET + 4] = MAGIC
    buf[PROTO_OFFSET + 4] = 2
    buf[PROTO_OFFSET + 5] = QUEUE_CAPACITY
    struct.pack_into("<HI", buf, PROTO_OFFSET + 6, RECORD_SIZE, SHM_SIZE)
    _store(buf, OFF_GENERATION, int(generation))


def publish_into(buf, blob, generation: int | None = None) -> dict:
    """Copy one fixed record and publish the index. No lock, pipe, or disk write."""
    started = time.monotonic_ns()
    if type(blob) is not bytes or len(blob) != RECORD_SIZE:
        return _result("REFUSED", "RECORD_SIZE", started, buf)
    if not ipc.acquire(buf):
        return _result("REFUSED", "PRODUCER_BUSY", started, buf)
    try:
        if generation is None:
            generation = _load(buf, OFF_GENERATION)
        write_index, read_index = ipc.validate_header(buf, generation)
        if _load(buf, OFF_FLAGS) & (FLAG_KILL | FLAG_STOP):
            _add(buf, OFF_KILL_DROPS)
            return _result("KILL_SWITCH", "KILL_SWITCH", started, buf)
        if write_index - read_index >= QUEUE_CAPACITY:
            _add(buf, OFF_DROPPED)
            return _result("DROPPED", DROP_POLICY, started, buf)
        ipc.seal(buf, blob, generation, write_index)
        _store(buf, OFF_WRITE, write_index + 1)
    except ValueError as exc:
        _store(buf, OFF_FLAGS, _load(buf, OFF_FLAGS) | FLAG_KILL)
        return _result("DROPPED", str(exc), started, buf)
    finally:
        ipc.release(buf)
    _add(buf, OFF_QUEUED)
    _add(buf, OFF_SUBMIT_COUNT)
    elapsed = time.monotonic_ns() - started
    _store(buf, OFF_LAST_ELAPSED_NS, elapsed)
    if elapsed > _load(buf, OFF_MAX_ELAPSED_NS):
        _store(buf, OFF_MAX_ELAPSED_NS, elapsed)
    return _result("ACCEPTED", "QUEUED", started, buf)


def attach_publish(name: str, record: bytes) -> str:
    """Second process, same protocol the PowerShell producer uses."""
    shm = shared_memory.SharedMemory(name=name)
    try:
        generation = _load(shm.buf, OFF_GENERATION)
        return publish_into(shm.buf, record, generation)["status"]
    finally:
        shm.close()


def _attached_publish_main(name: str, record: bytes, conn) -> None:
    try:
        conn.send(attach_publish(name, record))
    except Exception as exc:
        conn.send("ERROR:" + type(exc).__name__)
    finally:
        conn.close()


def probe_interpreter(executable: str, *, timeout_s: float = 1.0, args: tuple[str, ...] | None = None) -> dict:
    """One bounded launch check. No retry and no watcher involvement."""
    import subprocess
    started = time.monotonic()
    command = [executable, "-c", "import sys; raise SystemExit(0 if sys.version_info[0] >= 3 else 1)"]
    if args is not None:
        command = [executable, *args]
    if not executable or "\x00" in executable:
        return _probe("PYTHON_ABSENT", started, timeout_s)
    try:
        completed = subprocess.run(
            command,
            timeout=timeout_s,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return _probe("PYTHON_ABSENT", started, timeout_s)
    except subprocess.TimeoutExpired:
        return _probe("PYTHON_UNRESPONSIVE", started, timeout_s)
    except OSError:
        return _probe("PYTHON_START_FAILED", started, timeout_s)
    if completed.returncode != 0:
        return _probe("PYTHON_START_FAILED", started, timeout_s)
    return _probe("PYTHON_PRESENT", started, timeout_s)


def _probe(status: str, started: float, timeout_s: float) -> dict:
    return {
        "status": status,
        "attempts": 1,
        "retry": False,
        "timeout_s": timeout_s,
        "elapsed_s": time.monotonic() - started,
        "autostart": False,
    }


def _map_name() -> str:
    return "b" + uuid.uuid4().hex[:11]


class BridgeSession:
    """Owns one mapping and, on POSIX, one spawned writer process."""

    def __init__(self, status: str, reason: str):
        self.status = status
        self.reason = reason
        self._shm = None
        self._process = None
        self._lock_fd = None
        self._owns_mapping = False
        self._stopped = False
        self._generation = 0
        self.map_name = ""

    def publish_bytes(self, blob: bytes) -> dict:
        started = time.monotonic_ns()
        if self.status == "DISABLED":
            return _result("DISABLED", "SIDECAR_DISABLED", started)
        if self.status == "P0_BLOCKED":
            return _result("P0_BLOCKED", self.reason, started)
        if self._stopped or self.status in {"STOPPED", "START_FAILED", "ALREADY_RUNNING"}:
            return _result("WORKER_STOPPED", self.reason or "WORKER_STOPPED", started)
        if self.status != "STARTED" or self._shm is None:
            return _result("REFUSED", self.reason or "NOT_STARTED", started)
        result = publish_into(self._shm.buf, blob, self._generation)
        result["elapsed_ns"] = time.monotonic_ns() - started
        return result

    def submit_capture(self, capture) -> dict:
        """Pack outside the index publish. Oversized text is refused before encode."""
        started = time.monotonic_ns()
        if self.status != "STARTED" or self._shm is None:
            refused = self.publish_bytes(b"")
            refused["elapsed_ns"] = time.monotonic_ns() - started
            return refused
        packed = pack_capture(capture)
        if not packed["ok"]:
            return _result("REFUSED", packed["reason"], started, self._shm.buf)
        result = self.publish_bytes(packed["record"])
        result["elapsed_ns"] = time.monotonic_ns() - started
        return result

    def set_fault(self, fault: int) -> None:
        if self._shm is not None:
            _store(self._shm.buf, OFF_FAULT, int(fault))

    def trip_kill_switch(self) -> None:
        if self._shm is not None:
            flags = _load(self._shm.buf, OFF_FLAGS)
            _store(self._shm.buf, OFF_FLAGS, flags | FLAG_KILL)

    def observe_owner(self) -> dict:
        """Non-blocking owner check. The 2 second loop does not call this."""
        if self._shm is None or self._process is None:
            return {"status": self.status, "alive": False, "retry": False}
        alive = bool(self._process.is_alive())
        heartbeat = _load(self._shm.buf, OFF_HEARTBEAT)
        stalled = bool(heartbeat) and time.monotonic_ns() - heartbeat > STALL_AFTER_NS
        if not alive:
            flags = _load(self._shm.buf, OFF_FLAGS)
            _store(self._shm.buf, OFF_FLAGS, flags | FLAG_KILL)
            return {"status": "WORKER_DEAD", "alive": False, "retry": False}
        if stalled:
            return {"status": "WORKER_STALLED", "alive": True, "retry": False}
        return {"status": "WORKER_ALIVE", "alive": True, "retry": False}

    def metrics(self) -> dict:
        buf = None if self._shm is None else self._shm.buf
        return {
            "status": self.status,
            "queued": 0 if buf is None else _load(buf, OFF_QUEUED),
            "durable": 0 if buf is None else _load(buf, OFF_DURABLE),
            "dropped_newest": 0 if buf is None else _load(buf, OFF_DROPPED),
            "failures": 0 if buf is None else _load(buf, OFF_FAILURES),
            "fail_closed": 0 if buf is None else _load(buf, OFF_FAIL_CLOSED),
            "kill_drops": 0 if buf is None else _load(buf, OFF_KILL_DROPS),
            "com_reads_added": 0 if buf is None else _load(buf, OFF_COM_READS),
            "stale_discarded": 0 if buf is None else _load(buf, OFF_STALE_DISCARDED),
            "last_elapsed_ns": 0 if buf is None else _load(buf, OFF_LAST_ELAPSED_NS),
            "max_elapsed_ns": 0 if buf is None else _load(buf, OFF_MAX_ELAPSED_NS),
            "worker_alive": bool(self._process.is_alive()) if self._process is not None else False,
            "restart_policy": RESTART_POLICY,
            "retry_policy": RETRY_POLICY,
            "hard_realtime_guaranteed": False,
            "live_watcher_connection": "P0_BLOCKED",
        }

    def stop(self, timeout_s: float = STOP_TIMEOUT_S) -> dict:
        started = time.monotonic()
        killed = False
        if self._shm is not None:
            flags = _load(self._shm.buf, OFF_FLAGS)
            _store(self._shm.buf, OFF_FLAGS, flags | FLAG_STOP | FLAG_KILL)
        if self._process is not None and self._process.is_alive():
            self._process.join(timeout_s)
            if self._process.is_alive():
                self._process.kill()
                killed = True
                self._process.join(0.05)
        exit_verified = self._process is None or not self._process.is_alive()
        self._stopped = True
        self.status = "STOPPED" if exit_verified else "STOP_PENDING"
        self._close_handles()
        return {
            "status": self.status,
            "worker_exit_verified": exit_verified,
            "killed": killed,
            "elapsed_s": time.monotonic() - started,
            "timeout_s": timeout_s,
            "retry": False,
            "restart_policy": RESTART_POLICY,
        }

    def _close_handles(self) -> None:
        from scripts.ms2_nonblocking_handoff import HandoffSession
        HandoffSession._close_handles(self)


def start_bridge(repo_root, relative: str | None = None, *, enabled: bool = False,
                 fault: int = 0) -> BridgeSession:
    """Reuse one cross-platform owner lifecycle; never start in the poll path."""
    from scripts.ms2_nonblocking_handoff import start_handoff
    owned = start_handoff(repo_root, relative, enabled=enabled, fault=fault, map_name=_map_name())
    session = BridgeSession(owned.status, owned.reason)
    session.__dict__.update(owned.__dict__)
    # Transfer only handles created by this owner, never another map's handles.
    owned._shm = owned._process = owned._lock_fd = None
    owned._owns_mapping = False
    return session


def producer_audit(repo_root=None) -> dict:
    """Read the producer script. This does not execute PowerShell."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    path = root / PRODUCER_RELATIVE
    text = path.read_text(encoding="ascii")
    hits = [token for token in FORBIDDEN_PRODUCER_TOKENS if token in text]
    return {
        "path": PRODUCER_RELATIVE,
        "ascii": True,
        "forbidden_hits": hits,
        "calls_python": "python" in text.lower(),
        "extra_com_reads": 0,
    }


def watcher_unchanged(repo_root=None) -> dict:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1]
    path = root / WATCHER_RELATIVE
    blob = path.read_bytes()
    import hashlib
    digest = hashlib.sha256(blob).hexdigest()
    return {
        "path": WATCHER_RELATIVE,
        "sha256": digest,
        "matches_pinned": digest == WATCHER_SHA256,
        "modified": digest != WATCHER_SHA256,
    }


def hold_mapping(name: str, preset: str = "empty", timeout_s: float = 20.0) -> int:
    """Test harness. Holds a mapping until the producer publishes or the timeout fires.

    This is not auto-start and it does not launch the watcher or the durable writer.
    """
    if preset not in {"empty", "full", "kill"}:
        return 2
    if len(name) < 8 or len(name) > 16 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789" for ch in name):
        return 2
    shm = shared_memory.SharedMemory(create=True, size=SHM_SIZE, name=name)
    try:
        buf = shm.buf
        buf[:] = b"\0" * SHM_SIZE
        stamp_header(buf, 1)
        if preset == "full":
            _store(buf, OFF_WRITE, QUEUE_CAPACITY)
        elif preset == "kill":
            _store(buf, OFF_FLAGS, FLAG_KILL)
        print(f"READY {shm.name} {SHM_SIZE}", flush=True)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            write_index = _load(buf, OFF_WRITE)
            dropped = _load(buf, OFF_DROPPED)
            kill_drops = _load(buf, OFF_KILL_DROPS)
            if preset == "empty" and write_index:
                record = bytes(buf[SLOT_BASE:SLOT_BASE + RECORD_SIZE])
                print("RESULT " + json.dumps(_summary(record, buf), sort_keys=True), flush=True)
                return 0
            if preset != "empty" and (dropped or kill_drops):
                print("RESULT " + json.dumps(_summary(None, buf), sort_keys=True), flush=True)
                return 0
            time.sleep(0.02)
        print("RESULT " + json.dumps({"timeout": True}, sort_keys=True), flush=True)
        return 3
    finally:
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass


def _summary(record: bytes | None, buf) -> dict:
    unpacked = None if record is None else unpack_capture(record)
    body = {
        "timeout": False,
        "write": _load(buf, OFF_WRITE),
        "dropped": _load(buf, OFF_DROPPED),
        "kill_drops": _load(buf, OFF_KILL_DROPS),
        "queued": _load(buf, OFF_QUEUED),
        "snapshot_atomic": None if unpacked is None else unpacked.get("snapshot_atomic"),
        "sequence_basis": None if unpacked is None else unpacked.get("sequence_basis"),
        "poll_seq": None if unpacked is None else unpacked.get("poll_seq"),
        "event_time": None if unpacked is None else unpacked.get("event_time"),
        "symbol": None if unpacked is None else unpacked.get("symbol"),
        "freshness": None if unpacked is None else unpacked.get("data_freshness"),
        "level_count": 0 if unpacked is None else len(unpacked.get("levels") or []),
    }
    if unpacked and unpacked.get("levels"):
        first = unpacked["levels"][0]
        body["ask_qty"] = first.get("AskQty")
        body["bid_qty"] = first.get("BidQty")
        body["suspected_gap"] = bool((unpacked.get("gap") or {}).get("suspected_gap"))
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline PowerShell bridge contract")
    parser.add_argument("command", nargs="?", default="contract", choices=("contract", "probe", "hold", "pack-fixture"))
    parser.add_argument("--exe", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--preset", default="empty")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--fixture", default="")
    args = parser.parse_args(argv)
    if args.command == "contract":
        json.dump(bridge_contract(), sys.stdout, ensure_ascii=False, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.command == "probe":
        json.dump(probe_interpreter(args.exe, timeout_s=min(args.timeout, 2.0)), sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.command == "pack-fixture":
        payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        packed = pack_capture(payload)
        if not packed["ok"]:
            print(packed["reason"])
            return 2
        print(packed["record"].hex())
        return 0
    return hold_mapping(args.name, args.preset, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
