import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import offline_save_checkpoint as cp


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'checkpoint.json'
        self.data = self.root / 'synthetic.bin'
        self.data.write_bytes(b'synthetic-one')

    def seed(self):
        return cp.initialize(self.state, self.data)

    def update(self, prior, generation=2):
        return cp.advance(self.state, self.data, generation=generation,
                          expected_record_sha256=prior['record_sha256'])

    def test_save_readback_chain_and_safety(self):
        first = self.seed()
        self.data.write_bytes(b'synthetic-two')
        second = self.update(first)
        self.assertEqual(cp.load(self.state), second)
        self.assertEqual(second['record']['previous_record_sha256'], first['record_sha256'])
        self.assertEqual(second['record']['byte_count'], 13)
        self.assertEqual(second['record']['sha256'], cp._digest(self.data.read_bytes()))
        self.assertEqual(second['record']['consistency'], 'PREVIOUS_MATCH')
        for key in ('source_authenticated', 'real_submit_allowed', 'promotion_eligible'):
            self.assertIs(second['record'][key], False)
        self.assertNotIn('available_at', second['record'])

    def test_duplicate_rejected_old_bytes_preserved(self):
        first = self.seed()
        old = self.state.read_bytes()
        with self.assertRaisesRegex(cp.CheckpointError, 'DUPLICATE'):
            self.update(first)
        self.assertEqual(self.state.read_bytes(), old)

    def test_generation_invalid_backwards_and_skips(self):
        first = self.seed()
        self.data.write_bytes(b'new')
        for generation in (0, -1, True, '2', 2.0, 1, 3, None, 2**63):
            with self.subTest(generation=generation), self.assertRaises(cp.CheckpointError):
                self.update(first, generation)
        self.assertEqual(cp.load(self.state), first)

    def test_missing_and_corruption_block_without_repair(self):
        with self.assertRaises(cp.CheckpointError):
            cp.load(self.state)
        with self.assertRaises(cp.CheckpointError):
            self.update({'record_sha256': '0' * 64})
        for raw in (b'broken', b'[]', b'null', b'{}'):
            self.state.write_bytes(raw)
            with self.assertRaises(cp.CheckpointError):
                cp.load(self.state)
            with self.assertRaises(cp.CheckpointError):
                self.seed()
            self.assertEqual(self.state.read_bytes(), raw)

    def test_semantically_invalid_record_even_with_recomputed_digest(self):
        first = self.seed()
        for key, value in (('generation', True), ('byte_count', -1), ('sha256', 'x'*64),
                           ('consumer_readback_at', '2026-01-01'), ('real_submit_allowed', True),
                           ('previous_generation', 0), ('consistency', 'MARKET_AUTHENTICATED')):
            bad = json.loads(json.dumps(first))
            bad['record'][key] = value
            bad['record_sha256'] = cp._digest(cp._encode(bad['record']))
            self.state.write_bytes(cp._encode(bad))
            with self.subTest(key=key), self.assertRaises(cp.CheckpointError):
                cp.load(self.state)

    def test_atomic_replace_failure_preserves_old(self):
        first = self.seed()
        old = self.state.read_bytes()
        self.data.write_bytes(b'new')
        with patch.object(cp.os, 'replace', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.update(first)
        self.assertEqual(self.state.read_bytes(), old)
        self.assertEqual(set(self.root.iterdir()), {self.state, self.data})

    def test_fsync_failure_preserves_old(self):
        first = self.seed()
        self.data.write_bytes(b'new')
        with patch.object(cp.os, 'fsync', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                self.update(first)
        self.assertEqual(cp.load(self.state), first)

    def test_staged_and_post_commit_readback_failure(self):
        first = self.seed()
        self.data.write_bytes(b'new')
        read = cp._read
        def staged(path):
            if path != self.state:
                raise cp.CheckpointError('staged failure')
            return read(path)
        with patch.object(cp, '_read', side_effect=staged):
            with self.assertRaises(cp.CheckpointError):
                self.update(first)
        self.assertEqual(cp.load(self.state), first)
        count = 0
        def post(path):
            nonlocal count
            if path == self.state:
                count += 1
                if count == 2:
                    raise cp.CheckpointError('committed verification unavailable')
            return read(path)
        with patch.object(cp, '_read', side_effect=post):
            with self.assertRaises(cp.CheckpointError):
                self.update(first)
        self.assertEqual(cp.load(self.state)['record']['generation'], 2)
        with self.assertRaises(cp.CheckpointError):
            self.update(first)

    def test_stale_lock_blocks_reads_and_writes(self):
        first = self.seed()
        lock = self.state.with_name(self.state.name + '.lock')
        lock.mkdir()
        with self.assertRaises(cp.CheckpointError):
            cp.load(self.state)
        with self.assertRaises(cp.CheckpointError):
            self.update(first)
        self.assertTrue(lock.exists())

    def test_concurrent_same_previous_exactly_one_commit(self):
        first = self.seed()
        self.data.write_bytes(b'new')
        barrier = threading.Barrier(2)
        outcomes = []
        def worker():
            barrier.wait()
            try:
                self.update(first)
                outcomes.append('saved')
            except cp.CheckpointError:
                outcomes.append('blocked')
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(outcomes, ['saved', 'blocked'])
        self.assertEqual(cp.load(self.state)['record']['generation'], 2)

    def test_empty_unstable_unreadable_data(self):
        first = self.seed()
        self.data.write_bytes(b'')
        with self.assertRaises(cp.CheckpointError):
            self.update(first)
        original = Path.read_bytes
        values = iter((b'one', b'two'))
        def unstable(path):
            return next(values) if path == self.data else original(path)
        with patch.object(Path, 'read_bytes', unstable):
            with self.assertRaises(cp.CheckpointError):
                self.update(first)
        self.data.unlink()
        with self.assertRaises(cp.CheckpointError):
            self.update(first)
        self.assertEqual(cp.load(self.state), first)

    def test_same_path_and_bootstrap_overwrite_refused(self):
        with self.assertRaises(cp.CheckpointError):
            cp.initialize(self.data, self.data)
        first = self.seed()
        with self.assertRaises(cp.CheckpointError):
            self.seed()
        self.assertEqual(cp.load(self.state), first)


class ReceiptCheckpointTests(unittest.TestCase):
    """Synthetic file/receipt integration, including deterministic race injection."""
    def setUp(self):
        CheckpointTests.setUp(self)
        self.prior = cp.initialize(self.state, self.data)
        private = self.root / 'data/private/ms2_observations'
        private.mkdir(parents=True)
        self.data = private / 'synthetic.jsonl'
        self.data.write_bytes(b'synthetic-next\n')
        from scripts.ms2_observation_ingress import independent_consumer_readback
        self.consumer = independent_consumer_readback(
            self.root, 'data/private/ms2_observations/synthetic.jsonl')
        self.writer = dict(transition='APPENDED', writes_performed=True,
            eligible_observed_n=0, real_submit_allowed=False,
            file_sha256=self.consumer['input_sha256'],
            bytes_written=self.consumer['bytes_read'],
            writer_readback_completed_at='2026-01-01T00:00:00+00:00',
            writer_readback_clock_basis='WRITER_LOCAL_UTC_AFTER_READBACK')

    def receipt_update(self, **changes):
        args = dict(writer_receipt=self.writer, consumer_receipt=self.consumer,
                    generation=2, expected_record_sha256=self.prior['record_sha256'])
        args.update(changes)
        return cp.advance_from_receipts(self.state, self.data, **args)

    def test_receipt_success_and_no_promotion(self):
        saved = self.receipt_update()
        self.assertEqual(cp.load(self.state), saved)
        self.assertEqual(saved['record']['sha256'], self.consumer['input_sha256'])
        self.assertEqual(saved['record']['byte_count'], self.consumer['bytes_read'])
        self.assertEqual(saved['record']['generation'], 2)
        for key in ('source_authenticated', 'promotion_eligible', 'real_submit_allowed'):
            self.assertIs(saved['record'][key], False)
        self.assertNotIn('available_at', saved['record'])
        with self.assertRaises(cp.CheckpointError):
            self.receipt_update(generation=3, expected_record_sha256=saved['record_sha256'])
        self.assertEqual(cp.load(self.state), saved)

    def test_receipt_mismatch_and_unconfirmed_preserve_state(self):
        before = self.state.read_bytes()
        for changes in ({'file_sha256': '0'*64}, {'bytes_written': 1},
                        {'transition': 'PENDING'}, {'writes_performed': False}):
            with self.subTest(changes=changes), self.assertRaises(cp.CheckpointError):
                self.receipt_update(writer_receipt=dict(self.writer, **changes))
            self.assertEqual(self.state.read_bytes(), before)
        # Two agreeing but stale/false receipts still cannot authorize different bytes.
        for w, c in (({'file_sha256': '0'*64}, {'input_sha256': '0'*64}),
                     ({'bytes_written': 1}, {'bytes_read': 1})):
            with self.assertRaises(cp.CheckpointError):
                self.receipt_update(writer_receipt=dict(self.writer, **w),
                                    consumer_receipt=dict(self.consumer, **c))
            self.assertEqual(self.state.read_bytes(), before)

    def test_receipt_generation_and_previous_state(self):
        before = self.state.read_bytes()
        for generation in (1, 3):
            with self.assertRaises(cp.CheckpointError):
                self.receipt_update(generation=generation)
        with self.assertRaises(cp.CheckpointError):
            self.receipt_update(expected_record_sha256='0'*64)
        self.assertEqual(self.state.read_bytes(), before)
        for raw in (None, b'broken'):
            if raw is None:
                self.state.unlink()
            else:
                self.state.write_bytes(raw)
            with self.assertRaises(cp.CheckpointError):
                self.receipt_update()
            self.assertEqual(self.state.read_bytes() if self.state.exists() else None, raw)

    def test_receipt_reconcile_to_file_race(self):
        from scripts import ms2_observation_ingress as ingress
        original = ingress.reconcile_writer_consumer_receipts
        before = self.state.read_bytes()
        def race(*args, **kwargs):
            matched = original(*args, **kwargs)
            self.data.write_bytes(b'changed-after-reconciliation')
            return matched
        with patch.object(ingress, 'reconcile_writer_consumer_receipts', side_effect=race):
            with self.assertRaises(cp.CheckpointError):
                self.receipt_update()
        self.assertEqual(self.state.read_bytes(), before)

    def test_receipt_staging_race_and_identity_replacement(self):
        before = self.state.read_bytes()
        read = cp._read
        original_data = self.data.read_bytes()
        for same_bytes in (False, True):
            def race(path):
                result = read(path)
                if path != self.state:
                    replacement = self.data.with_suffix('.tmp')
                    replacement.write_bytes(original_data if same_bytes else b'changed')
                    replacement.replace(self.data)
                return result
            with patch.object(cp, '_read', side_effect=race):
                with self.assertRaises(cp.CheckpointError):
                    self.receipt_update()
            self.assertEqual(self.state.read_bytes(), before)
            self.data.write_bytes(original_data)

    def test_receipt_post_commit_failures_never_success(self):
        replace = cp.os.replace
        def race(src, dst):
            replace(src, dst)
            self.data.write_bytes(b'changed-after-commit')
        with patch.object(cp.os, 'replace', side_effect=race):
            with self.assertRaises(cp.CheckpointError):
                self.receipt_update()
        self.assertEqual(cp.load(self.state)['record']['generation'], 2)

    def test_receipt_committed_readback_failure(self):
        read = cp._read
        count = 0
        def fail(path):
            nonlocal count
            if path == self.state:
                count += 1
                if count == 2:
                    raise cp.CheckpointError('COMMITTED_READBACK_FAILED')
            return read(path)
        with patch.object(cp, '_read', side_effect=fail):
            with self.assertRaises(cp.CheckpointError):
                self.receipt_update()

    def test_receipt_concurrent_updates(self):
        barrier = threading.Barrier(2)
        outcomes = []
        def worker():
            barrier.wait()
            try:
                self.receipt_update()
                outcomes.append('saved')
            except cp.CheckpointError:
                outcomes.append('blocked')
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
            self.assertFalse(t.is_alive())
        self.assertCountEqual(outcomes, ['saved', 'blocked'])
        self.assertEqual(cp.load(self.state)['record']['generation'], 2)


if __name__ == '__main__':
    unittest.main()
