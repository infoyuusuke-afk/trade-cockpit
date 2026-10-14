"""#364 synthetic commit boundary. No brokerage data, no PID-based cleanup."""
import os
import tempfile
import time
import unittest
from multiprocessing import get_context, shared_memory
from pathlib import Path
from scripts import ms2_nonblocking_handoff as h
from scripts.ms2_ps_python_bridge import start_bridge, attach_publish
from scripts.ms2_bridge_record import pack_capture
from scripts.ms2_offline_observation_writer import record_captured_observation
from tests.test_ms2_ps_python_bridge import _board, RELATIVE


def inflight_owner(root, fault, pipe):
    session = start_bridge(root, RELATIVE, enabled=True, fault=fault)
    try:
        pipe.send(dict(status=session.status, name=session.map_name, generation=session._generation))
        if session.status != 'STARTED': return
        capture = _board(); capture['poll_seq'] = 4
        session.submit_capture(capture)
        command = pipe.recv()
        if command == 'kill_worker':
            session._process.kill(); session._process.join(5)
            pipe.send(session.stop())
        else:
            pipe.send(session.stop())
    finally:
        session.stop()
        pipe.close()


def untrusted_same_user(name, record, pipe):
    # No inherited producer session or credential. Public name + canonical bytes.
    pipe.send(attach_publish(name, record)); pipe.close()


class BoundaryTests(unittest.TestCase):
    def test_required_authentication_refuses_before_private_resource_creation(self):
        with tempfile.TemporaryDirectory() as root:
            for start in (start_bridge, h.start_handoff):
                session = start(root, RELATIVE, enabled=True, require_process_authentication=True)
                self.assertEqual(session.status, 'P0_BLOCKED')
                self.assertEqual(session.reason, 'SAME_USER_AUTH_UNRESOLVED')
                self.assertFalse((Path(root)/'data').exists())
                self.assertFalse(session._process)

    def test_same_user_can_publish_without_process_credential_is_not_authentication(self):
        with tempfile.TemporaryDirectory() as root:
            session = start_bridge(root, RELATIVE, enabled=True, fault=h.FAULT_HOLD)
            ctx = get_context('spawn'); parent, child = ctx.Pipe()
            process = ctx.Process(target=untrusted_same_user,
                args=(session.map_name, pack_capture(_board())['record'], child))
            try:
                self.assertEqual(session.status, 'STARTED')
                process.start(); self.assertTrue(parent.poll(8))
                self.assertEqual(parent.recv(), 'ACCEPTED')
                process.join(5); self.assertEqual(process.exitcode, 0)
                self.assertEqual(session.metrics()['queued'], 1)
                self.assertEqual(h.handoff_contract()['same_user_authentication'], 'SAME_USER_AUTH_UNRESOLVED')
            finally:
                if process.is_alive(): process.kill(); process.join(5)
                session.stop(); parent.close(); child.close()

    def _boundary(self, fault, reason, kill_worker=False):
        with tempfile.TemporaryDirectory() as root:
            report = record_captured_observation(root, RELATIVE, _board(), enabled=True)
            self.assertTrue(report['writes_performed'])
            path = Path(root)/RELATIVE; original = path.read_bytes()
            ctx = get_context('spawn'); parent, child = ctx.Pipe()
            owner = ctx.Process(target=inflight_owner, args=(root, fault, child))
            old = fresh = None
            try:
                owner.start(); self.assertTrue(parent.poll(8)); info = parent.recv()
                self.assertEqual(info['status'], 'STARTED', info)
                old = shared_memory.SharedMemory(name=info['name'])
                deadline = time.monotonic()+8
                while h._read_reason(old.buf) != reason and time.monotonic()<deadline:
                    time.sleep(.005)
                self.assertEqual(h._read_reason(old.buf), reason)
                if fault != h.FAULT_AFTER_REPLACE:
                    self.assertEqual(path.read_bytes(), original)
                else:
                    self.assertTrue(path.read_bytes().startswith(original))
                    self.assertEqual(len(path.read_bytes().splitlines()), 2)
                if kill_worker:
                    # Exact owned Process handle, never a PID read from IPC.
                    parent.send('kill_worker'); self.assertTrue(parent.poll(8))
                    self.assertEqual(parent.recv()['status'], 'STOPPED')
                    owner.join(5)
                else:
                    owner.kill(); owner.join(5)
                    blocked = start_bridge(root, RELATIVE, enabled=True)
                    self.assertEqual(blocked.status, 'ALREADY_RUNNING')
                    self.assertEqual(blocked.reason, 'DUPLICATE_START')
                    self.assertEqual(h._read_reason(old.buf), reason)
                    # Release a synthetic unresponsive syscall; not real cancellation.
                    h._store(old.buf, h._OFF_FAULT, h.FAULT_NONE)
                deadline = time.monotonic()+8
                while time.monotonic()<deadline:
                    fresh = start_bridge(root, RELATIVE, enabled=True)
                    if fresh.status == 'STARTED': break
                    self.assertEqual(fresh.status, 'ALREADY_RUNNING'); time.sleep(.01)
                self.assertEqual(fresh.status, 'STARTED')
                self.assertNotEqual(fresh._generation, info['generation'])
                self.assertEqual(fresh.metrics()['queued'], 0)
                self.assertEqual(fresh.metrics()['durable'], 0)
                self.assertEqual(fresh.submit_capture(_board())['status'], 'ACCEPTED')
                time.sleep(.1)
                if fault != h.FAULT_AFTER_REPLACE:
                    self.assertEqual(path.read_bytes(), original)
                else:
                    self.assertEqual(len(path.read_bytes().splitlines()), 2)
                if kill_worker and fault != h.FAULT_AFTER_REPLACE:
                    self.assertGreater(fresh.metrics()['stale_discarded'], 0)
                    self.assertTrue(list((path.parent/'quarantine').rglob('*.tmp')))
                if not kill_worker:
                    self.assertEqual(h._read_reason(old.buf), 'OWNER_DEAD_QUARANTINED')
                    self.assertEqual(h._load(old.buf, h._OFF_FLAGS)&3, 3)
                print('IPC_BOUNDARY=' + str(dict(fault=fault, kill_worker=kill_worker,
                    states=['IN_FLIGHT','BLOCKED' if not kill_worker else 'STOPPED','QUARANTINED','NEW_GENERATION'],
                    power_loss='NOT_VERIFIED')))
            finally:
                if old: h._store(old.buf, h._OFF_FAULT, h.FAULT_NONE)
                if owner.is_alive():
                    parent.send('stop'); owner.join(5)
                    if owner.is_alive(): owner.kill(); owner.join(5)
                if fresh: fresh.stop()
                if old:
                    old.close()
                    if os.name != 'nt':
                        try: old.unlink()
                        except FileNotFoundError: pass
                parent.close(); child.close()

    def test_owner_death_in_partial_temp_write_blocks_restart_until_return(self):
        self._boundary(h.FAULT_WRITE_INFLIGHT, 'IO_INFLIGHT')

    def test_owner_death_before_replace_does_not_commit(self):
        self._boundary(h.FAULT_BEFORE_REPLACE, 'BEFORE_REPLACE')

    def test_owner_death_after_replace_keeps_committed_jsonl(self):
        self._boundary(h.FAULT_AFTER_REPLACE, 'AFTER_REPLACE')

    def test_worker_crash_in_partial_write_quarantines_temp(self):
        self._boundary(h.FAULT_WRITE_INFLIGHT, 'IO_INFLIGHT', True)

    def test_worker_crash_before_replace_quarantines_complete_unpublished_temp(self):
        self._boundary(h.FAULT_BEFORE_REPLACE, 'BEFORE_REPLACE', True)

    def test_worker_crash_after_replace_preserves_committed_file(self):
        self._boundary(h.FAULT_AFTER_REPLACE, 'AFTER_REPLACE', True)
