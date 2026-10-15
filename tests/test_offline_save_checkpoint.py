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


if __name__ == '__main__':
    unittest.main()
