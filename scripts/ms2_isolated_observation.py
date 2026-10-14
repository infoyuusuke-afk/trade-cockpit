"""Issue 366 OFFLINE ONLY: fixed-copy ingress; all bridge work is on lane B.

Input is an immutable canonical 2048-byte fixture prepared OUTSIDE lane A.
This is not a Watcher adapter, authentication, or a WCET guarantee.
"""
from __future__ import annotations

import ctypes
import os
import time
import threading
import zlib
from multiprocessing import get_context, parent_process

CAPACITY = 8
SIZE = 2048
READY, STOP, KILL, DEAD = 1, 2, 3, 4
REASONS = ('QUEUE_FULL', 'GATE_BUSY', 'NOT_READY', 'STOP_PENDING', 'KILL_SWITCH',
           'CONSUMER_STALE', 'INPUT_INVALID', 'STALE_INPUT', 'WRONG_PRODUCER',
           'OLD_GENERATION')


def contract():
    return dict(offline_only=True, watcher_applied=False, extra_com_reads=0,
                real_submit_allowed=False, promotion_eligible=False,
                statistical_edge_confirmed=False, eligible_observed_n=0,
                same_user_authentication='SAME_USER_AUTH_UNRESOLVED',
                production='P0_BLOCKED', snapshot_atomic=False,
                close_state='NOT_CLOSED', hard_realtime_guaranteed=False,
                input_preparation='OUTSIDE_CRITICAL_PATH',
                native_ps_producer='NOT_VERIFIED')


class Ingress:
    """Single PID/thread producer. Handles allocated by offline launcher only.

    No process launch/attach, disk, JSON, canonical pack, SHA, pipe, sleep,
    join, liveness syscall or blocking lock acquisition in offer(). CRC32 is
    a fixed 2048-byte corruption check, NOT identity authentication.
    Counters are producer-local; exact totals plus first/last drop clocks.
    """
    def __init__(self, ctx, generation):
        self.data = ctx.RawArray(ctypes.c_ubyte, CAPACITY * SIZE)
        self.tags = ctx.RawArray(ctypes.c_uint64, CAPACITY * 5)
        self.meta = ctx.RawArray(ctypes.c_uint64, 6)
        self.gate = ctx.Lock()
        self.generation = generation
        self.meta[4] = generation
        self.owner_pid = os.getpid()
        self.owner_thread = threading.get_ident()
        self.counts = {reason: [0, 0, 0, 0, 0] for reason in REASONS}
        self.accepted = 0
        self.last_poll = 0
        self.view = memoryview(self.data).cast('B')

    def _drop(self, reason, poll, at):
        item = self.counts[reason]
        if not item[0]: item[1], item[3] = at, poll
        item[0] += 1
        item[2], item[4] = at, poll
        return 'DROP', reason

    def offer(self, record, poll, observed_ns, generation=None):
        now = time.monotonic_ns()
        # Types are checked before any coercion or user-defined callback.
        if type(poll) is not int or not 0 < poll < 2**63:
            return self._drop('INPUT_INVALID', 0, now)
        if os.getpid() != self.owner_pid or threading.get_ident() != self.owner_thread:
            return self._drop('WRONG_PRODUCER', poll, now)
        if type(record) is not bytes or len(record) != SIZE or type(observed_ns) is not int:
            return self._drop('INPUT_INVALID', poll, now)
        if observed_ns <= 0 or observed_ns > now or now - observed_ns > 1_000_000_000 or poll <= self.last_poll:
            return self._drop('STALE_INPUT', poll, now)
        self.last_poll = poll  # Even a DROP cannot be retried with the same poll.
        if generation is not None and (type(generation) is not int or generation != self.generation):
            return self._drop('OLD_GENERATION', poll, now)
        if not self.gate.acquire(False):
            return self._drop('GATE_BUSY', poll, now)
        try:
            state = self.meta[2]
            if state != READY:
                reason = 'KILL_SWITCH' if state == KILL else 'STOP_PENDING' if state == STOP else 'NOT_READY'
                return self._drop(reason, poll, now)
            if self.meta[4] != self.generation:
                return self._drop('OLD_GENERATION', poll, now)
            if now - self.meta[3] > 500_000_000:
                return self._drop('CONSUMER_STALE', poll, now)
            write, read = self.meta[0], self.meta[1]
            if write < read or write - read >= CAPACITY:
                return self._drop('QUEUE_FULL', poll, now)
            slot = write % CAPACITY
            self.tags[slot*5] = 0  # Uncommitted until full copy and tag.
            self.view[slot*SIZE:(slot+1)*SIZE] = record
            self.tags[slot*5+1] = self.generation
            self.tags[slot*5+2] = observed_ns
            self.tags[slot*5+3] = zlib.crc32(record)
            self.tags[slot*5+4] = poll
            self.tags[slot*5] = write + 1
            self.meta[0] = write + 1
            self.accepted += 1
            return 'ACCEPTED', 'INGRESS_ONLY'
        finally:
            self.gate.release()

    def audit(self):
        # Read only from the producer thread after measurement/quiescence.
        return dict(accepted=self.accepted, drops={k: dict(count=v[0], first_at_ns=v[1],
                    last_at_ns=v[2], first_poll=v[3], last_poll=v[4])
                    for k, v in self.counts.items() if v[0]},
                    timestamp_domain='MONOTONIC_SESSION', durable=False,
                    close_state='NOT_CLOSED', eligible_observed_n=0)


def lower_priority():
    # Executed in B only. Failure cannot be relabelled as priority success.
    try:
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
                return 'NOT_VERIFIED'
        else:
            os.nice(10)
        return 'LOWERED'
    except OSError:
        return 'NOT_VERIFIED'


def _consumer(data, tags, meta, gate, generation, root, relative, conn, fault):
    from scripts.ms2_ps_python_bridge import start_bridge
    from scripts.ms2_bridge_record import unpack_capture
    from scripts.ms2_nonblocking_handoff import _load, _OFF_FLAGS, _OFF_HEARTBEAT, _OFF_DUPLICATES, STALL_AFTER_NS
    priority = lower_priority()
    session = start_bridge(root, relative, enabled=True, fault=fault)
    report = dict(priority=priority, forwarded=0, refused={},
                  generation=generation, contract=contract(), refusal_times={})
    view = memoryview(data).cast('B')
    parent = parent_process()
    held = False
    def refuse(reason):
        report['refused'][reason] = report['refused'].get(reason, 0) + 1
        now = time.monotonic_ns()
        span = report['refusal_times'].setdefault(reason, {'first_at_ns': now, 'last_at_ns': now})
        span['last_at_ns'] = now
    try:
        if session.status != 'STARTED':
            conn.send(dict(status=session.status, reason=session.reason)); return
        # Writer gets its own below-normal/nice priority, outside lane A.
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x200, False, session._process.pid)
            if handle:
                kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                report['writer_priority'] = 'LOWERED' if kernel.SetPriorityClass(handle, 0x4000) else 'NOT_VERIFIED'
                kernel.CloseHandle(handle)
            else: report['writer_priority'] = 'NOT_VERIFIED'
        else:
            os.setpriority(os.PRIO_PROCESS, session._process.pid, 10)
            report['writer_priority'] = 'LOWERED'
        with gate:
            meta[3] = time.monotonic_ns(); meta[2] = READY
        conn.send(dict(status='READY', priority=priority, writer_priority=report['writer_priority'],
                       map_name=session.map_name, writer_pid=session._process.pid))
        while parent is None or parent.is_alive():
            if conn.poll():
                command = conn.recv()
                if command == 'metrics':
                    metrics = session.metrics()
                    metrics['duplicates'] = _load(session._shm.buf, _OFF_DUPLICATES) if session._shm else 0
                    conn.send(dict(report, writer=metrics)); continue
                if command == 'hold': held = True; continue
                if command == 'resume': held = False; continue
                if command == 'kill_writer':
                    session._process.kill(); session._process.join(2)
                    with gate: meta[2] = DEAD
                    continue
                if command == 'stop': break
            with gate:
                if meta[2] in (STOP, KILL): break
                meta[3] = time.monotonic_ns()
                write, read = meta[0], meta[1]
                if held or write == read: record = None
                elif write < read or write - read > CAPACITY:
                    meta[2] = DEAD; refuse('HEADER_CORRUPT'); break
                else:
                    slot = read % CAPACITY
                    tag = tuple(tags[slot*5:slot*5+5])
                    record = bytes(view[slot*SIZE:(slot+1)*SIZE])
                    meta[1] = read + 1  # Never replay refused/old records.
            if record is None:
                time.sleep(.001); continue
            if tag[0] != read + 1 or tag[1] != generation:
                refuse('TORN_OR_OLD_GENERATION'); continue
            if zlib.crc32(record) != tag[3]: refuse('PAYLOAD_CORRUPT'); continue
            if time.monotonic_ns() - tag[2] > 500_000_000:
                refuse('STALE_ACQUISITION'); continue
            capture = unpack_capture(record)
            if capture is None:
                refuse('RECORD_INVALID'); continue
            if capture['poll_seq'] != tag[4]:
                refuse('POLL_MISMATCH'); continue
            if not session._process.is_alive():
                with gate: meta[2] = DEAD
                refuse('WRITER_DEAD'); continue
            buf = session._shm.buf
            if _load(buf, _OFF_FLAGS) or time.monotonic_ns()-_load(buf, _OFF_HEARTBEAT) > STALL_AFTER_NS:
                refuse('WRITER_UNHEALTHY'); continue
            with gate:
                if meta[2] != READY:
                    refuse('STOP_OR_KILL_BEFORE_FORWARD'); continue
            result = session.publish_bytes(record)  # SHA/ACL/IPC is B only.
            if result['status'] == 'ACCEPTED': report['forwarded'] += 1
            else: refuse(result.get('reason', 'BRIDGE_REFUSED'))
    except (EOFError, BrokenPipeError):
        refuse('OWNER_CHANNEL_CLOSED')
    finally:
        with gate:
            pending = max(0, meta[0] - meta[1])
            meta[1] = meta[0]; meta[2] = DEAD
        report['discarded_pending'] = pending
        report['stop'] = session.stop(.05)
        try: conn.send(report)
        except (BrokenPipeError, EOFError, OSError): pass
        view.release(); conn.close()


class OfflineLane:
    """Launcher/control API. NEVER invoke start/control/stop on lane A."""
    def __init__(self, root, relative, *, enabled=False, require_authentication=True, fault=0):
        self.ingress = self.process = self.conn = None
        self.status = 'DISABLED'
        self.reason = 'OFFLINE_DISABLED'
        if not enabled: return
        if require_authentication:
            self.status, self.reason = 'P0_BLOCKED', 'SAME_USER_AUTH_UNRESOLVED'; return
        ctx = get_context('spawn')
        # Exact session generation; identity is not authenticated.
        generation = int.from_bytes(os.urandom(8), 'little') or 1
        self.ingress = Ingress(ctx, generation)
        self.conn, child = ctx.Pipe()
        i = self.ingress
        self.process = ctx.Process(target=_consumer,
            args=(i.data, i.tags, i.meta, i.gate, generation, str(root), relative, child, fault))
        self.process.start(); child.close()
        if self.conn.poll(8):
            self.start_report = self.conn.recv()
            self.status = self.start_report['status']
            self.reason = self.start_report.get('reason', '')
        else:
            self.status, self.reason = 'P0_BLOCKED', 'START_NOT_PROVEN'

    def control(self, command):
        self.conn.send(command)
        if command == 'metrics' and self.conn.poll(3): return self.conn.recv()
        return None

    def stop(self):
        if self.process is None: return dict(status=self.status, reason=self.reason)
        if getattr(self, '_closed_control', False): return self.stop_report
        i = self.ingress
        # If orphan held gate, do not wait to mark stop. Control is separate B.
        if i.gate.acquire(False):
            try: i.meta[2] = STOP
            finally: i.gate.release()
        if self.process.is_alive():
            self.conn.send('stop'); self.process.join(.5)
        if self.process.is_alive(): return dict(status='STOP_PENDING', reason='CONSUMER_NOT_EXITED')
        try:
            result = self.conn.recv() if self.conn.poll(.1) else dict(status='P0_BLOCKED', reason='STOP_NOT_PROVEN')
        except EOFError:
            result = dict(status='P0_BLOCKED', reason='CONSUMER_CRASH_ORPHAN_NOT_PROVEN')
        if 'stop' in result: result['status'] = result['stop']['status']
        self.stop_report = result
        self._closed_control = True
        self.status = result.get('status', 'P0_BLOCKED'); return result
