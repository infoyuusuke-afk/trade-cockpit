"""Synthetic-only regression for explicit local capture. Never reads an actual market CSV."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import ms2_local_csv_capture as c
from tests.test_ms2_offline_csv_snapshot import TICK


class LocalCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.source = self.repo / 'source'
        self.source.mkdir()
        self.tick = self.source / 'kioxia_ticks_20260102.csv'
        self.tick.write_bytes(TICK)
        self.ok = {'state': 'PASS', 'scope': 'SYNTHETIC_ONLY'}

    def test_no_selection_no_read(self):
        with patch.object(c, 'run_acceptance') as before, patch.object(c, 'preserve_csv') as save:
            self.assertEqual(c.capture_selection(None, self.repo), 'CANCELLED')
            before.assert_not_called()
            save.assert_not_called()

    def test_bad_names_refuse_before_read(self):
        invalid = ('relative.csv', str(self.source / 'wrong.csv'),
                   str(self.source / 'kioxia_ticks_20260102.csv:stream'),
                   str(self.source / 'kioxia_tick_diag_20260102.csv'))
        with patch.object(c, 'run_acceptance') as before:
            for path in invalid:
                self.assertEqual(c.capture_selection(path, self.repo), 'BLOCKED')
            before.assert_not_called()

    def test_preflight_skips_and_failures_refuse_source(self):
        for report in ({'state': 'BLOCKED', 'scope': 'SYNTHETIC_ONLY'},
                       {'state': 'PASS', 'scope': 'REAL'}, {'state': 'PASS'}):
            with patch.object(c, 'run_acceptance', return_value=report), \
                 patch.object(c, 'preserve_csv') as save:
                self.assertEqual(c.capture_selection(str(self.tick), self.repo), 'BLOCKED')
                save.assert_not_called()

    def test_failed_evidence_refuses_source(self):
        with patch.object(c, 'run_acceptance', return_value=self.ok), \
             patch.object(c, 'save_evidence', side_effect=OSError('PRIVATE SECRET')), \
             patch.object(c, 'preserve_csv') as save:
            self.assertEqual(c.capture_selection(str(self.tick), self.repo), 'BLOCKED')
            save.assert_not_called()

    def test_local_synthetic_copy_and_duplicate_refusal(self):
        before = self.tick.stat()
        with patch.object(c, 'run_acceptance', return_value=self.ok), \
             patch.object(c, 'save_evidence'):
            self.assertEqual(c.capture_selection(str(self.tick), self.repo),
                             'PRESERVED_UNAUTHENTICATED')
            self.assertEqual(c.capture_selection(str(self.tick), self.repo), 'BLOCKED')
        targets = list((self.repo / 'data/private/ms2_csv_snapshots').iterdir())
        self.assertEqual(len(targets), 1)
        self.assertEqual((targets[0] / self.tick.name).read_bytes(), TICK)
        record = json.loads((targets[0] / 'manifest.json').read_text())
        for key in ('source_authenticated', 'promotion_eligible', 'real_submit_allowed'):
            self.assertIs(record[key], False)
        self.assertEqual(self.tick.read_bytes(), TICK)
        self.assertEqual(self.tick.stat().st_mtime_ns, before.st_mtime_ns)

    def test_corrupt_source_is_unchanged(self):
        self.tick.write_bytes(b'bad\n')
        with patch.object(c, 'run_acceptance', return_value=self.ok), \
             patch.object(c, 'save_evidence'):
            self.assertEqual(c.capture_selection(str(self.tick), self.repo), 'BLOCKED')
        self.assertEqual(self.tick.read_bytes(), b'bad\n')

    def test_false_safety_claims_refuse_success(self):
        for flag in ('source_authenticated', 'promotion_eligible', 'real_submit_allowed'):
            result = {'state': 'PRESERVED_UNAUTHENTICATED',
                      'source_authenticated': False, 'promotion_eligible': False,
                      'real_submit_allowed': False}
            result[flag] = True
            with patch.object(c, 'run_acceptance', return_value=self.ok), \
                 patch.object(c, 'save_evidence'), patch.object(c, 'preserve_csv', return_value=result):
                self.assertEqual(c.capture_selection(str(self.tick), self.repo), 'BLOCKED')

    def test_frozen_synthetic_check_does_not_read_market(self):
        with patch.object(c.sys, 'frozen', True, create=True), \
             patch.object(c, 'run_acceptance', return_value=self.ok), \
             patch.object(c, 'save_evidence') as evidence, \
             patch.object(c, 'preserve_csv') as preserve, \
             patch.object(c, 'select_file') as picker, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(c.main(['--synthetic-check']), 0)
        evidence.assert_called_once_with(self.ok)
        picker.assert_not_called()
        preserve.assert_not_called()
        self.assertIn('PASS', output.getvalue())

    def test_frozen_synthetic_refuses_failed_preflight(self):
        with patch.object(c.sys, 'frozen', True, create=True), \
             patch.object(c, 'run_acceptance', return_value={'state': 'BLOCKED', 'scope': 'SYNTHETIC_ONLY'}), \
             patch.object(c, 'preserve_csv') as preserve, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(c.main(['--synthetic-check']), 1)
        preserve.assert_not_called()
        self.assertIn('BLOCKED', output.getvalue())

    def test_frozen_capture_uses_separate_private_root(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory)
            with patch.object(c, 'run_acceptance', return_value=self.ok), \
                 patch.object(c, 'save_evidence'), \
                 patch.object(c, 'private_root', return_value=local) as private, \
                 patch.object(c, 'preserve_csv', return_value={
                     'state': 'PRESERVED_UNAUTHENTICATED',
                     'source_authenticated': False, 'promotion_eligible': False,
                     'real_submit_allowed': False}) as preserved:
                self.assertEqual(c.capture_selection(str(self.tick)), 'PRESERVED_UNAUTHENTICATED')
            private.assert_called_once_with()
            preserved.assert_called_once_with(local, self.source, self.tick.name)

    def test_main_no_cli_market_path_or_exception_disclosure(self):
        out = io.StringIO()
        with patch.object(c, 'select_file') as picker, contextlib.redirect_stdout(out):
            self.assertEqual(c.main(['SECRET.csv']), 2)
        picker.assert_not_called()
        self.assertNotIn('SECRET', out.getvalue())
        out = io.StringIO()
        with patch.object(c, 'select_file', side_effect=RuntimeError('SECRET PC')), \
             contextlib.redirect_stdout(out):
            self.assertEqual(c.main([]), 1)
        self.assertNotIn('SECRET', out.getvalue())

    def test_main_fixed_status_exit_codes(self):
        for state, code in (('PRESERVED_UNAUTHENTICATED', 0), ('BLOCKED', 1), ('CANCELLED', 3)):
            out = io.StringIO()
            with patch.object(c, 'select_file', return_value='SECRET'), \
                 patch.object(c, 'capture_selection', return_value=state), \
                 contextlib.redirect_stdout(out):
                self.assertEqual(c.main([]), code)
            self.assertNotIn('SECRET', out.getvalue())


if __name__ == '__main__':
    unittest.main()
