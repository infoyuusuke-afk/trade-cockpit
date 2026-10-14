"""Issue #362: synthetic ownership boundary and hard owner death, no live I/O."""
import os
import struct
import tempfile
import time
import unittest
import uuid
from multiprocessing import get_context, shared_memory
from pathlib import Path
from scripts import ms2_ipc_integrity as ipc
from scripts import ms2_nonblocking_handoff as h
from scripts.ms2_ps_python_bridge import start_bridge
from tests.test_ms2_ps_python_bridge import _board, RELATIVE


def owner(root, pipe):
    session = start_bridge(root, RELATIVE, enabled=True, fault=h.FAULT_HOLD)
    if session.status != 'STARTED':
        pipe.send({'status': session.status, 'reason': session.reason})
        return
    session.submit_capture(_board())
    pipe.send({'status': 'STARTED', 'name': session.map_name, 'generation': session._generation})
    pipe.recv()  # Parent kills this exact owned Process object.


def racing_create(name, ready, release, pipe):
    ready.wait(5)
    mapping = None
    try:
        mapping = ipc.create_mapping(name, h.SHM_SIZE)
        pipe.send('CREATED')
        release.wait(5)
    except FileExistsError:
        pipe.send('COLLISION')
    finally:
        if mapping:
            mapping.close()
            if os.name != 'nt': mapping.unlink()
        pipe.close()


class SecurityTests(unittest.TestCase):
    def test_concurrent_creators_have_exactly_one_owner(self):
        ctx = get_context('spawn'); ready = ctx.Event(); release = ctx.Event()
        name = 'b' + uuid.uuid4().hex[:11]
        children = []; pipes = []
        try:
            for _ in range(3):
                parent, child = ctx.Pipe()
                process = ctx.Process(target=racing_create, args=(name, ready, release, child))
                process.start(); children.append(process); pipes.append(parent); child.close()
            ready.set()
            outcomes = []
            for pipe in pipes:
                self.assertTrue(pipe.poll(8)); outcomes.append(pipe.recv())
            self.assertEqual(sorted(outcomes), ['COLLISION', 'COLLISION', 'CREATED'])
        finally:
            release.set()
            for process in children:
                process.join(6)
                if process.is_alive(): process.kill(); process.join(5)
                self.assertEqual(process.exitcode, 0)
            for pipe in pipes: pipe.close()

    def test_exclusive_map_collision_never_changes_foreign_bytes(self):
        name = 'b' + uuid.uuid4().hex[:11]
        foreign = ipc.create_mapping(name, h.SHM_SIZE)
        try:
            foreign.buf[:8] = b'FOREIGN!'
            with self.assertRaises(FileExistsError):
                ipc.create_mapping(name, h.SHM_SIZE)
            self.assertEqual(bytes(foreign.buf[:8]), b'FOREIGN!')
        finally:
            foreign.close()
            if os.name != 'nt': foreign.unlink()

    def test_owner_hard_kill_quarantines_pending_data_and_fresh_restart(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = get_context('spawn'); parent, child = ctx.Pipe()
            process = ctx.Process(target=owner, args=(root, child))
            process.start(); old = None; fresh = None
            try:
                self.assertTrue(parent.poll(8)); info = parent.recv()
                self.assertEqual(info['status'], 'STARTED', info)
                old = shared_memory.SharedMemory(name=info['name'])
                process.kill(); process.join(5)
                self.assertFalse(process.is_alive())
                deadline = time.monotonic() + 6
                while time.monotonic() < deadline and not (h._load(old.buf, h._OFF_FLAGS) & 3):
                    time.sleep(.01)
                self.assertEqual(h._load(old.buf, h._OFF_FLAGS) & 3, 3)
                self.assertEqual(h._read_reason(old.buf), 'OWNER_DEAD_QUARANTINED')
                self.assertFalse((Path(root) / RELATIVE).exists())
                # Worker lease, not an arbitrary PID, establishes exit/restart permission.
                while time.monotonic() < deadline:
                    fresh = start_bridge(root, RELATIVE, enabled=True)
                    if fresh.status == 'STARTED': break
                    self.assertEqual(fresh.status, 'ALREADY_RUNNING')
                    time.sleep(.01)
                self.assertEqual(fresh.status, 'STARTED')
                self.assertNotEqual(fresh.map_name, info['name'])
                self.assertNotEqual(fresh._generation, info['generation'])
                self.assertEqual(fresh.metrics()['queued'], 0)
                self.assertEqual(fresh.metrics()['durable'], 0)
            finally:
                if process.is_alive(): process.kill(); process.join(5)
                if fresh: fresh.stop()
                if old:
                    old.close()
                    if os.name != 'nt':
                        try: old.unlink()
                        except FileNotFoundError: pass
                parent.close(); child.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows native creation boundary')
    def test_mutex_precreation_refused_and_real_acl_audited(self):
        generation = int(uuid.uuid4().hex[:14], 16)
        ipc.prepare(generation, create=True)
        # Remove only local cache, keep original handle alive to simulate collision.
        original = ipc._mutexes.pop(generation)
        try:
            with self.assertRaisesRegex(ValueError, 'IPC_MUTEX_COLLISION'):
                ipc.prepare(generation, create=True)
            ipc.prepare(generation)
            self.assertEqual(ipc.windows_acl_audit('', object_handle=ipc._mutexes[generation])['status'], 'PASS')
        finally:
            ipc._native.CloseHandle(original)

    @unittest.skipUnless(os.name == 'nt', 'Windows PS5.1 phase measurements')
    def test_repeated_windows_phases_with_background_contention(self):
        import subprocess, sys, json
        from tests.test_ms2_ps_python_bridge import ROOT
        for run in range(3):
            with tempfile.TemporaryDirectory() as root:
                session = start_bridge(root, RELATIVE, enabled=True, fault=h.FAULT_HOLD)
                self.assertEqual(session.status, 'STARTED', session.reason)
                load = None
                try:
                    if run == 1:
                        load = subprocess.Popen([sys.executable, '-c', 'while True: sum(range(10000))'])
                    started = time.perf_counter()
                    result = subprocess.run(['powershell.exe', '-NoProfile', '-File',
                        str(ROOT/'tests/ms2_ipc_fault_producer.ps1'), '-MapName', session.map_name,
                        '-Mode', 'timing'], capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads(result.stdout.strip())
                    report.update(run=run, background_contention=run == 1,
                                  harness_elapsed_ms=(time.perf_counter()-started)*1000)
                    print('WINDOWS_IPC_PHASES=' + json.dumps(report, sort_keys=True))
                    self.assertEqual(report['accepted'], 8)
                    self.assertEqual(report['dropped'], 192)
                    self.assertEqual(report['complete_steady']['samples'], 200)
                    self.assertIn('UNLOCK', report['stage_stats'])
                    self.assertIn('gc_delta', report['worst'])
                    for phase in ('packing', 'attach', 'mutex', 'publish'):
                        self.assertGreater(report['phases'][phase]['samples'], 0)
                finally:
                    if load: load.kill(); load.wait(5)
                    session.stop()

    @unittest.skipUnless(os.name == 'nt', 'actual unauthorized Windows token')
    def test_anonymous_token_cannot_open_created_objects(self):
        import ctypes
        from ctypes import wintypes as w
        name = 'b' + uuid.uuid4().hex[:11]
        generation = int(uuid.uuid4().hex[:14], 16)
        mapping = ipc.create_mapping(name, h.SHM_SIZE)
        ipc.prepare(generation, create=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        adv = ctypes.WinDLL('advapi32', use_last_error=True)
        kernel.GetCurrentThread.restype = w.HANDLE
        adv.ImpersonateAnonymousToken.argtypes = [w.HANDLE]
        kernel.OpenFileMappingW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        kernel.OpenFileMappingW.restype = w.HANDLE
        kernel.OpenMutexW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        kernel.OpenMutexW.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        impersonating = False
        try:
            self.assertTrue(adv.ImpersonateAnonymousToken(kernel.GetCurrentThread()))
            impersonating = True
            for fn, rights, target in ((kernel.OpenFileMappingW, 6, name),
                    (kernel.OpenMutexW, 0x100001, 'Local\\ms2ipc-v2-' + str(generation))):
                handle = fn(rights, False, target)
                error = ctypes.get_last_error()
                if handle: kernel.CloseHandle(handle)
                self.assertFalse(handle)
                self.assertEqual(error, 5)  # ERROR_ACCESS_DENIED, not merely missing.
        finally:
            if impersonating: self.assertTrue(adv.RevertToSelf())
            mapping.close(); ipc.close_generation(generation)
