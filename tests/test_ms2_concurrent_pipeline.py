import os
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import ms2_nonblocking_handoff as h
from scripts import ms2_ipc_integrity as ipc
import tempfile
from tests.ms2_concurrent_pipeline import run, normal_failure_evidence, synthetic
from scripts.ms2_ps_python_bridge import stamp_header
from scripts.ms2_bridge_record import pack_capture


class _GateScript:
    """Virtual clock for the unchanged worker loop; no real sleep or disk.

    ``events`` maps a worker sleep count to an action run inside that sleep.
    An action may advance the clock to model the worker being descheduled.
    The gate is changed only through the real ``ipc.acquire``/``ipc.release``.
    """
    def __init__(self, buf, events, stop_after):
        self.buf, self.events, self.stop_after = buf, events, stop_after
        self.now = 1_000_000_000
        self.sleeps = 0
        self.holds = []
        self._held_at = None
    def monotonic_ns(self):
        return self.now
    def monotonic(self):
        return self.now / 1e9
    def take(self):
        self.assert_true(ipc.acquire(self.buf))
        self._held_at = self.now
    def commit(self):
        """Producer ACCEPTED path inside the hold: seal, publish, count."""
        write = h._load(self.buf, h._OFF_WRITE)
        generation = h._load(self.buf, h._OFF_GENERATION)
        record = pack_capture(synthetic(write + 1, generation))['record']
        ipc.seal(self.buf, record, generation, write)
        h._store(self.buf, h._OFF_WRITE, write + 1)
        h._add(self.buf, h._OFF_QUEUED)
        h._add(self.buf, h._OFF_SUBMIT_COUNT)
    def give(self, commit=True):
        # A real producer hold never ends without moving a progress counter.
        if commit:
            self.commit()
        ipc.release(self.buf)
        self.holds.append(self.now - self._held_at)
        self._held_at = None
    def assert_true(self, ok):
        if not ok:
            raise AssertionError('SCRIPT_GATE_NOT_ACQUIRED')
    def sleep(self, seconds):
        self.sleeps += 1
        self.now += int(seconds * 1e9)
        action = self.events.get(self.sleeps)
        if action:
            action(self)
        if self.sleeps >= self.stop_after:
            if self._held_at is not None:
                self.give(commit=False)
            h._store(self.buf, h._OFF_FLAGS, h._load(self.buf, h._OFF_FLAGS) | h._FLAG_STOP)


def _drive_worker(events, *, stop_after=200, queued=False, held=False):
    """Run the real ``_worker_loop`` on a private buffer with a scripted gate."""
    generation = 7_000_000 + os.getpid() % 100_000
    buf = bytearray(h.SHM_SIZE)
    stamp_header(buf, generation)
    script = _GateScript(buf, events, stop_after)
    if queued:  # One committed slot already waiting.
        script.commit()
    if held:  # Producer already inside the gate when the worker starts.
        script.take()
    try:
        with tempfile.TemporaryDirectory() as root, patch.object(h, 'time', script):
            h._worker_loop(buf, root, 'data/private/ms2_sidecar/gate382.jsonl', generation)
    finally:
        ipc.close_generation(generation)
    return buf, script

class ConcurrentTests(unittest.TestCase):

    # Issue #382: IPC_GATE_ABANDONED must mean one gate hold was observed
    # continuously for STALL_AFTER_NS, not that two unrelated short holds were
    # sampled on either side of a pause in the worker's own scheduling.
    def _assert_not_abandoned(self, buf, script):
        self.assertEqual(h._read_reason(buf), 'STOPPED')
        self.assertEqual(h._load(buf, h._OFF_FAIL_CLOSED), 0)
        self.assertFalse(h._load(buf, h._OFF_FLAGS) & h._FLAG_KILL)
        self.assertTrue(script.holds)
        self.assertLess(max(script.holds), h.STALL_AFTER_NS)

    def test_short_holds_across_idle_worker_pause_are_not_abandonment(self):
        def first_hold(s): s.take()  # worker samples it busy after this sleep
        def descheduled(s):          # 2ms hold ends, worker is off-CPU 200ms,
            s.now += 2_000_000; s.give()
            s.now += 198_000_000; s.take()  # a new, unrelated 2ms hold begins
        def second_release(s): s.now += 2_000_000; s.give()
        buf, script = _drive_worker({3: first_hold, 4: descheduled, 5: second_release}, stop_after=12)
        self._assert_not_abandoned(buf, script)

    def test_short_holds_across_queued_worker_pause_are_not_abandonment(self):
        def descheduled(s):
            s.now += 2_000_000; s.give()
            s.now += 198_000_000; s.take()
        def second_release(s): s.now += 2_000_000; s.give()
        # Stop before the worker reaches the slot so no Writer/disk is involved.
        buf, script = _drive_worker({1: descheduled, 2: second_release}, stop_after=2, queued=True, held=True)
        self._assert_not_abandoned(buf, script)

    def test_one_continuous_hold_still_fails_closed_as_abandoned(self):
        def hold_forever(s): s.take()
        buf, script = _drive_worker({2: hold_forever}, stop_after=10_000)
        self.assertEqual(h._read_reason(buf), 'IPC_GATE_ABANDONED')
        self.assertEqual(h._load(buf, h._OFF_FAIL_CLOSED), 1)
        self.assertTrue(h._load(buf, h._OFF_FLAGS) & h._FLAG_KILL)
        # Detected after the threshold with normal sampling, never before it.
        self.assertGreater(script.now - script._held_at, h.STALL_AFTER_NS)
        self.assertLess(script.now - script._held_at, h.STALL_AFTER_NS + 20_000_000)

    def test_one_continuous_hold_while_queued_still_fails_closed(self):
        buf, script = _drive_worker({}, stop_after=10_000, queued=True, held=True)
        self.assertEqual(h._read_reason(buf), 'IPC_GATE_ABANDONED')
        self.assertTrue(h._load(buf, h._OFF_FLAGS) & h._FLAG_KILL)
        self.assertEqual(h._load(buf, h._OFF_READ), 0)  # nothing claimed

    def test_stuck_hold_with_30_to_40ms_worker_sampling_still_fails_closed(self):
        # Counterexample to a gap-reset watchdog: one hold, never released,
        # while the live worker (heartbeat advancing) samples every 30-40ms.
        def stutter(s):
            s.now += 28_000_000 + (s.sleeps % 2) * 10_000_000  # +2ms sleep = 30/40ms
        events = {k: stutter for k in range(3, 10_000)}
        events[2] = lambda s: s.take()
        heartbeats = []
        original = _GateScript.sleep
        def sleep(s, seconds):
            heartbeats.append(h._load(s.buf, h._OFF_HEARTBEAT))
            original(s, seconds)
        with patch.object(_GateScript, 'sleep', sleep):
            buf, script = _drive_worker(events, stop_after=200)  # ~7s virtual
        self.assertGreaterEqual(len(set(heartbeats)), 4)  # worker kept running in the hold
        self.assertEqual(h._read_reason(buf), 'IPC_GATE_ABANDONED')
        self.assertTrue(h._load(buf, h._OFF_FLAGS) & h._FLAG_KILL)
        # Inside the hold, bounded by threshold plus one 40ms sampling gap.
        self.assertLess(script.now - script._held_at, h.STALL_AFTER_NS + 45_000_000)

    def test_ambiguous_tail_sample_fails_closed_known_limit(self):
        # Proven limit of the existing IPC: the worker samples hold A after its
        # last counter write but before release, is off-CPU 200ms, and resumes
        # inside hold B before B commits. Gate word and every counter are
        # identical to one 200ms hold, so no observer of this IPC can tell the
        # two apart. The watchdog must take the safe side: fail closed.
        def a_committed(s): s.take(); s.commit()     # A's counters already moved
        def descheduled(s):
            s.now += 1_000_000; s.give(commit=False)  # A releases (tail only)
            s.now += 199_000_000; s.take()           # B in progress, uncommitted
        buf, script = _drive_worker({2: a_committed, 3: descheduled}, stop_after=40)
        self.assertEqual(h._read_reason(buf), 'IPC_GATE_ABANDONED')
        self.assertTrue(h._load(buf, h._OFF_FLAGS) & h._FLAG_KILL)

    def _out_of_gate_submitter(self, buf, generation):
        """Real HandoffSession.submit on the same mapping: it refuses on a
        busy gate (or a full queue) but still bumps counters outside the gate."""
        session = h.HandoffSession('STARTED', '')
        session._shm = SimpleNamespace(buf=buf)
        session._generation = generation
        attempts = []
        def submit(s):
            before = {name: h._load(buf, off) for name, off in
                      (('submit', h._OFF_SUBMIT_COUNT), ('dropped', h._OFF_DROPPED), ('write', h._OFF_WRITE))}
            r = session.submit(synthetic(1000 + len(attempts), generation))
            after = {name: h._load(buf, off) for name, off in
                     (('submit', h._OFF_SUBMIT_COUNT), ('dropped', h._OFF_DROPPED), ('write', h._OFF_WRITE))}
            attempts.append((r['status'], r['reason'], before, after))
        return submit, attempts

    def _stuck_with_out_of_gate_updates(self, queued):
        # Issue #382 (ChatGPT audit): a stuck gate held >=600ms while another
        # submitter retries every 20-30ms. Each retry fails on the gate (or a
        # full queue) yet moves SUBMIT_COUNT/DROPPED outside the gate.
        generation = 7_000_000 + os.getpid() % 100_000
        holder = {}
        def setup(s):
            for _ in range(queued):
                s.commit()
            s.take(); holder['at'] = s.now
            holder['submit'], holder['attempts'] = self._out_of_gate_submitter(s.buf, h._load(s.buf, h._OFF_GENERATION))
        def tick(s):
            if 'submit' in holder and (s.now - holder.get('last', 0)) >= 20_000_000 + (len(holder['attempts']) % 2) * 10_000_000:
                holder['last'] = s.now; holder['submit'](s)
        events = {1: setup}
        events.update({k: tick for k in range(2, 400)})  # 2ms worker samples, ~0.8s
        buf, script = _drive_worker(events, stop_after=400)
        attempts = holder['attempts']
        refused = [a for a in attempts if a[0] in {'REFUSED', 'DROPPED'}]
        self.assertGreater(len(refused), 3)
        self.assertTrue(all(a[3]['write'] == a[2]['write'] for a in refused))  # nothing entered the gate
        self.assertTrue(any(a[3]['submit'] > a[2]['submit'] for a in refused))  # out-of-gate update happened
        self.assertEqual(h._read_reason(buf), 'IPC_GATE_ABANDONED')
        self.assertTrue(h._load(buf, h._OFF_FLAGS) & h._FLAG_KILL)
        self.assertLess(script.now - holder['at'], h.STALL_AFTER_NS + 10_000_000)
        return attempts

    def test_stuck_gate_with_out_of_gate_submit_count_still_fails_closed(self):
        attempts = self._stuck_with_out_of_gate_updates(queued=0)
        self.assertTrue(all(a[1] == 'PRODUCER_BUSY' for a in attempts if a[0] == 'REFUSED'))

    def test_stuck_gate_with_out_of_gate_dropped_still_fails_closed(self):
        attempts = self._stuck_with_out_of_gate_updates(queued=h.QUEUE_CAPACITY)
        self.assertTrue(any(a[0] == 'DROPPED' and a[3]['dropped'] > a[2]['dropped'] for a in attempts))

    def test_released_gate_between_normal_samples_is_not_abandonment(self):
        events = {}
        for k in range(2, 200, 4):  # 2ms holds every 8ms for ~0.8s
            events[k] = lambda s: s.take()
            events[k + 1] = lambda s: s.give()
        buf, script = _drive_worker(events, stop_after=210)
        self._assert_not_abandoned(buf, script)

    def test_gate_failure_snapshot_preserves_unknown_and_no_death_claim(self):
        buf = bytearray(h.SHM_SIZE)
        h._store(buf, h._OFF_HEARTBEAT, 800_000_000)
        h._store(buf, h._OFF_WRITE, 32)
        h._store(buf, h._OFF_READ, 31)
        h._store(buf, h._OFF_FAIL_CLOSED, 1)
        h._reason(buf, 'IPC_GATE_ABANDONED')
        struct.pack_into('<I', buf, ipc.GATE, 1)
        worker = SimpleNamespace(is_alive=lambda: False, exitcode=0)
        session = SimpleNamespace(_shm=SimpleNamespace(buf=buf), _process=worker)
        producer = SimpleNamespace(poll=lambda: 0)
        with patch('tests.ms2_concurrent_pipeline.time.monotonic_ns', return_value=1_000_000_000):
            evidence = normal_failure_evidence(
                {'PERSISTED_VERIFIED': 31, 'UNKNOWN_TERMINAL': 1, 'DROPPED_PRE_QUEUE': 68},
                [{'state': 'ACCEPTED'}] * 32, [{'transition': 'APPENDED'}] * 31,
                session, producer, True)
        self.assertEqual(evidence['accepted'], 32)
        self.assertEqual(evidence['heartbeat_age_ms'], 200.0)
        self.assertEqual(evidence['gate_word'], 1)
        self.assertEqual(evidence['fail_closed_count'], 1)
        self.assertEqual(evidence['write_index']-evidence['read_index'], 1)
        self.assertFalse(evidence['mutex_abandonment_proven'])
        self.assertEqual(evidence['production'], 'P0_BLOCKED')
        self.assertNotIn('symbol', str(evidence))
        self.assertNotIn('record', str(evidence))

    def test_uninitialized_heartbeat_is_unknown(self):
        buf = bytearray(h.SHM_SIZE)
        session = SimpleNamespace(_shm=SimpleNamespace(buf=buf),
                                  _process=SimpleNamespace(is_alive=lambda: True, exitcode=None))
        evidence = normal_failure_evidence({}, [], [], session, None, False)
        self.assertIsNone(evidence['heartbeat_age_ms'])
        self.assertIsNone(evidence['producer_exitcode'])
        self.assertEqual(evidence['worker_transitions'], {})
        self.assertFalse(evidence['mutex_abandonment_proven'])

    def test_real_bridge_writer_concurrent_faults(self):
        for mode in ('normal','delay','queue_full','gate_busy','permission','partial','before_replace','after_replace','worker_kill','kill','stop','duplicate','receipt_loss'):
            with self.subTest(mode=mode):
                r=run(mode,n=16)
                self.assertEqual(r['attempts'],16)
                self.assertEqual(r['queued']+r['drops'],16)
                self.assertEqual(r['close_state'],'NOT_CLOSED')
                self.assertEqual(r['production'],'P0_BLOCKED')
                self.assertEqual(r['five_ms'],'NOT_MET')
                self.assertEqual(sum(r['states'].values()),1 if mode=='duplicate' else 16)
                if mode=='gate_busy':self.assertGreater(r['cohorts']['GATE_BUSY']['full_ms']['N'],0)
    @unittest.skipUnless(os.name=='nt','Native Windows PS5.1 required')
    def test_native_real_bridge_concurrent(self):
        r=run('normal',n=16,native=True)
        self.assertEqual(r['ps'].split('.')[:2],['5','1'])
        self.assertTrue(r['concurrent_completion_observed'])
        self.assertEqual(r['states'].get('PERSISTED_VERIFIED'),r['queued'])

if __name__=='__main__':unittest.main()
