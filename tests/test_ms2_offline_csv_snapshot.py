"""Synthetic fixtures only. No MS2, Excel, network or real market values."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import ms2_offline_csv_snapshot as m

TICK = b'recorded_at,tick_time,price,volume,poll_seq\r\n2026-01-02 09:00:00,09:00:00,1,1,1\r\n'
DIAG = b'poll_time,window_size,overlap_with_prev,new_appended,suspected_gap\n2026-01-02 09:00:00,1,0,1,False\n'


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.tick = self.source / 'kioxia_ticks_20260102.csv'
        self.diag = self.source / 'kioxia_tick_diag_20260102.csv'
        self.tick.write_bytes(TICK)
        self.diag.write_bytes(DIAG)

    def run_snapshot(self, **kw):
        return m.preserve_csv(self.root, self.source, self.tick.name, **kw)

    def output(self):
        return self.root / 'data/private/ms2_csv_snapshots'

    def assertBlocked(self, result):
        self.assertEqual(result['state'], 'BLOCKED')
        self.assertFalse(result['source_authenticated'])
        self.assertFalse(result['promotion_eligible'])
        self.assertFalse(result['real_submit_allowed'])

    def test_no_opt_in_no_filesystem_access(self):
        with patch.object(Path, 'lstat', side_effect=AssertionError('access')), patch.object(Path, 'open', side_effect=AssertionError('access')):
            self.assertEqual(m.preserve_csv('/missing', '/missing')['state'], 'NOT_REQUESTED')

    def test_raw_bytes_hash_size_and_readonly_source(self):
        before = self.tick.stat()
        self.tick.chmod(0o444)
        try:
            result = self.run_snapshot()
        finally:
            self.tick.chmod(0o600)
        self.assertEqual(result['state'], 'PRESERVED_UNAUTHENTICATED')
        saved = self.output() / result['snapshot_id']
        self.assertEqual((saved / self.tick.name).read_bytes(), TICK)
        entry = json.loads((saved / 'manifest.json').read_text())['files'][0]
        self.assertEqual(entry['size'], len(TICK))
        self.assertEqual(entry['sha256'], hashlib.sha256(TICK).hexdigest())
        self.assertEqual(self.tick.read_bytes(), TICK)
        self.assertEqual(self.tick.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.tick.stat().st_ino, before.st_ino)

    def test_actual_watcher_utf8_bom_and_crlf_preserved_as_bytes(self):
        # PowerShell 5.1 Out-File -Encoding utf8 commonly writes a BOM.
        tick = b'\xef\xbb\xbf' + TICK
        diag = b'\xef\xbb\xbf' + DIAG.replace(b'\n', b'\r\n')
        self.tick.write_bytes(tick)
        self.diag.write_bytes(diag)
        result = self.run_snapshot(diag_name=self.diag.name)
        self.assertEqual(result['state'], 'PRESERVED_UNAUTHENTICATED')
        location = self.output() / result['snapshot_id']
        self.assertEqual((location / self.tick.name).read_bytes(), tick)
        self.assertEqual((location / self.diag.name).read_bytes(), diag)

    def test_duplicate_and_existing_data_protected(self):
        first = self.run_snapshot()
        saved = self.output() / first['snapshot_id']
        before = {p.name: p.read_bytes() for p in saved.iterdir()}
        self.assertBlocked(self.run_snapshot())
        self.assertEqual(before, {p.name: p.read_bytes() for p in saved.iterdir()})

    def test_diag_separate_hash_and_nonatomic_safety(self):
        result = self.run_snapshot(diag_name=self.diag.name)
        manifest = json.loads((self.output() / result['snapshot_id'] / 'manifest.json').read_text())
        self.assertFalse(manifest['pair_atomic'])
        self.assertEqual(manifest['pair_evidence'], 'INDEPENDENT_FILE_READS_NOT_SIMULTANEOUS')
        self.assertEqual(manifest['files'][1]['sha256'], hashlib.sha256(DIAG).hexdigest())
        self.assertEqual(manifest['files'][1]['size'], len(DIAG))
        for key in ('source_authenticated', 'promotion_eligible', 'real_submit_allowed'):
            self.assertIs(manifest[key], False)
        self.assertNotIn('available_at', manifest)
        self.assertNotIn('event_time', manifest)

    def test_mismatched_missing_and_corrupt_diag(self):
        for name in ('kioxia_tick_diag_20260103.csv', '../outside.csv'):
            self.assertBlocked(self.run_snapshot(diag_name=name))
        for raw in (b'bad\n', DIAG.replace(b'False', b'unknown'), DIAG.replace(b'2026-01-02', b'2026-01-03'), DIAG.replace(b',1,0,1,', b',1,2,1,')):
            self.diag.write_bytes(raw)
            self.assertBlocked(self.run_snapshot(diag_name=self.diag.name))
        self.diag.unlink()
        self.assertBlocked(self.run_snapshot(diag_name=self.diag.name))
        self.assertFalse(self.output().exists())

    def test_invalid_header_corrupt_partial_and_values(self):
        for raw in (b'', b'bad\n', TICK.replace(b'price', b'other'), TICK[:-2], TICK + b'broken\n', TICK.replace(b',1,1,1', b',NaN,1,1'), TICK.replace(b'09:00:00,1', b'99:00:00,1'), TICK.replace(b'2026-01-02', b'2026-01-03'), TICK + b'\x00\n', b'\xff\n'):
            with self.subTest(raw=raw):
                self.tick.write_bytes(raw)
                self.assertBlocked(self.run_snapshot())
        self.assertFalse(self.output().exists())

    def test_invalid_paths_and_size(self):
        for name in ('../' + self.tick.name, str(self.tick), 'nested/' + self.tick.name, 'kioxia_ticks_20261399.csv', 'kioxia_ticks_20260102.csv:stream'):
            self.assertBlocked(m.preserve_csv(self.root, self.source, name))
        with patch.object(m, 'MAX_BYTES', len(TICK) - 1):
            self.assertBlocked(self.run_snapshot())
        self.assertFalse(self.output().exists())

    def test_source_symlink_and_destination_link(self):
        # Native links are tested when allowed. Otherwise model their lstat
        # attributes to exercise refusal without requiring Windows privilege.
        from types import SimpleNamespace
        import stat
        original_lstat = Path.lstat

        def refuse_as_link(linked_path, run, *, mode=stat.S_IFLNK, attributes=0):
            def fake_lstat(path, *args, **kwargs):
                if path == linked_path:
                    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                return original_lstat(path, *args, **kwargs)
            with patch.object(Path, 'lstat', fake_lstat):
                self.assertBlocked(run())

        target = self.source / 'original.csv'
        # The fixture file MUST be moved before attempting a native link.
        # Otherwise symlink_to always raises FileExistsError and silently
        # reduces this test to the mocked fallback even on Linux.
        self.tick.rename(target)
        try:
            self.assertFalse(self.tick.exists())
            try:
                self.tick.symlink_to(target)
            except (OSError, NotImplementedError):
                refuse_as_link(self.tick, self.run_snapshot)
                # Windows directory reparse points can be non-symlink modes.
                refuse_as_link(self.tick, self.run_snapshot,
                               mode=stat.S_IFREG, attributes=0x400)
            else:
                self.assertTrue(self.tick.is_symlink())
                self.assertBlocked(self.run_snapshot())
        finally:
            if self.tick.is_symlink():
                self.tick.unlink()
            target.rename(self.tick)

        outside = self.root / 'outside'
        outside.mkdir()
        link = self.root / 'data'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            # These are synthetic refusal checks, not proof of native
            # Windows junction / reparse-point or ACL behavior.
            refuse_as_link(link, self.run_snapshot)
            refuse_as_link(link, self.run_snapshot,
                           mode=stat.S_IFDIR, attributes=0x400)
        else:
            self.assertTrue(link.is_symlink())
            self.assertBlocked(self.run_snapshot())
            self.assertEqual(list(outside.iterdir()), [])
            link.unlink()
        self.assertFalse(self.output().exists())

    def test_stat_api_timestamp_representation_difference(self):
        original = m.os.fstat
        def handle_stat(fd):
            info = original(fd)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_size=info.st_size, st_mode=info.st_mode,
                                   st_mtime_ns=info.st_mtime_ns + 1,
                                   st_ctime_ns=info.st_ctime_ns + 1)
        with patch.object(m.os, 'fstat', handle_stat):
            self.assertEqual(self.run_snapshot()['state'], 'PRESERVED_UNAUTHENTICATED')

    def test_handle_timestamp_mutation_refused(self):
        original = m.os.fstat
        calls = 0
        def handle_stat(fd):
            nonlocal calls
            calls += 1
            info = original(fd)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino,
                                   st_size=info.st_size, st_mode=info.st_mode,
                                   st_mtime_ns=info.st_mtime_ns + calls,
                                   st_ctime_ns=info.st_ctime_ns)
        with patch.object(m.os, 'fstat', handle_stat):
            self.assertBlocked(self.run_snapshot())
        self.assertFalse(self.output().exists())

    def test_change_between_reads_rejected(self):
        original = Path.open
        calls = 0
        def opening(path, *args, **kwargs):
            nonlocal calls
            if path == self.tick and args == ('rb',):
                calls += 1
                if calls == 2:
                    self.tick.write_bytes(TICK.replace(b',1,1,1', b',2,1,1'))
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', opening):
            self.assertBlocked(self.run_snapshot())
        self.assertFalse(self.output().exists())

    def test_tick_change_during_diag_rejected(self):
        original = m._read
        def reading(path):
            raw = original(path)
            if path == self.diag:
                self.tick.write_bytes(TICK.replace(b',1,1,1', b',2,1,1'))
            return raw
        with patch.object(m, '_read', reading):
            self.assertBlocked(self.run_snapshot(diag_name=self.diag.name))
        self.assertFalse(self.output().exists())

    def test_failed_publication_protects_previous_snapshot(self):
        first = self.run_snapshot()
        saved = self.output() / first['snapshot_id']
        before = {p.name: p.read_bytes() for p in saved.iterdir()}
        self.tick.write_bytes(TICK.replace(b',1,1,1', b',2,1,1'))
        with patch.object(m.os, 'fsync', side_effect=OSError('private path MUST NOT LEAK')):
            result = self.run_snapshot()
        self.assertBlocked(result)
        self.assertNotIn('private path', json.dumps(result))
        self.assertEqual(list(self.output().iterdir()), [saved])
        self.assertEqual(before, {p.name: p.read_bytes() for p in saved.iterdir()})

    def test_readback_corruption_refused(self):
        original = m._read
        def reading(path):
            raw = original(path)
            return raw + b'x' if 'ms2_csv_snapshots' in path.parts else raw
        with patch.object(m, '_read', reading):
            self.assertBlocked(self.run_snapshot())
        self.assertEqual(list(self.output().iterdir()), [])


if __name__ == '__main__':
    unittest.main()
