"""Acceptance packaging, fail-closed reporting and disclosure regression tests."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import ms2_offline_acceptance as a


class AcceptanceTests(unittest.TestCase):
    def test_frozen_root_points_to_executable_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(a.sys, 'frozen', True, create=True), \
                 patch.object(a.sys, 'executable', str(Path(directory) / 'MS2_Local_CSV.exe')):
                self.assertEqual(a.runtime_root(), Path(directory).resolve())

    def test_actual_synthetic_contract(self):
        report = a.run_acceptance()
        self.assertEqual(len(report['checks']), 14)
        self.assertIn(report['state'], ('PASS', 'BLOCKED'))
        self.assertEqual(report['state'] == 'PASS', all(c['status'] == 'PASS' for c in report['checks']))
        for key in ('real_submit_allowed', 'source_authenticated', 'promotion_eligible',
                    'owner_ms2_verified', 'real_market_capture_verified', 'pair_atomic'):
            self.assertIs(report[key], False)
        self.assertEqual(report['scope'], 'SYNTHETIC_ONLY')
        self.assertEqual(set(report['code_sha256']), set(a.CODE_FILES))
        text = json.dumps(report)
        self.assertNotIn(str(a.ROOT), text)
        self.assertNotIn('2026-01-02 09:00:00', text)

    def test_exception_masking_and_nonzero(self):
        output = io.StringIO()
        with patch.object(a, 'run_acceptance', side_effect=OSError('SECRET account path')), contextlib.redirect_stdout(output):
            self.assertEqual(a.main([]), 1)
        self.assertNotIn('SECRET', output.getvalue())

    def test_untrusted_arguments_not_echoed_or_read(self):
        with patch.object(a, 'run_acceptance') as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(a.main(['SECRET.csv']), 2)
        run.assert_not_called()
        self.assertNotIn('SECRET', output.getvalue())

    def test_failure_and_skip_cannot_pass_or_leak(self):
        from tests.test_ms2_offline_csv_snapshot import SnapshotTests
        for mode in ('failure', 'skip', 'exception'):
            def fake(test, result):
                print('SECRET')
                if mode == 'exception':
                    raise RuntimeError('SECRET')
                result.startTest(test)
                if mode == 'skip':
                    result.addSkip(test, 'SECRET')
                else:
                    result.addFailure(test, (AssertionError, AssertionError('SECRET'), None))
                result.stopTest(test)
            with patch.object(SnapshotTests, 'run', fake), contextlib.redirect_stdout(io.StringIO()) as output:
                report = a.run_acceptance()
            self.assertEqual(report['state'], 'BLOCKED')
            self.assertNotIn('SECRET', json.dumps(report) + output.getvalue())

    def test_evidence_exclusive_and_prior_data_unchanged(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(a, 'ROOT', Path(temp)):
            report = {'state': 'BLOCKED'}
            a.save_evidence(report)
            a.save_evidence(report)
            files = list((Path(temp) / 'data/private/ms2_offline_acceptance').glob('*.json'))
            self.assertEqual(len(files), 2)
            self.assertTrue(all(json.loads(p.read_text()) == report for p in files))

    def test_evidence_write_failure_blocks(self):
        with patch.object(a, 'run_acceptance', return_value={'state': 'PASS'}), patch.object(a, 'save_evidence', side_effect=OSError('SECRET')), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(a.main([]), 1)
        self.assertNotIn('SECRET', output.getvalue())

    def test_success_and_blocked_exit_status_with_evidence(self):
        for state, expected in (('PASS', 0), ('BLOCKED', 1)):
            report = {'state': state}
            with patch.object(a, 'run_acceptance', return_value=report), patch.object(a, 'save_evidence') as save, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(a.main([]), expected)
            save.assert_called_once_with(report)

    def test_linked_evidence_directory_refused(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(a, 'ROOT', Path(temp)), patch.object(a, '_checked_path', side_effect=ValueError('PATH_LINK')):
            with self.assertRaises(ValueError):
                a.save_evidence({'state': 'PASS'})
            self.assertEqual(list(Path(temp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
