"""Offline build-contract tests; no actual Windows packaging on Ubuntu."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import build_ms2_windows_exe as b


class WindowsExeTests(unittest.TestCase):
    def test_command_has_necessary_test_and_fingerprint_assets(self):
        command = b.installer_arguments()
        self.assertIn('--onedir', command)
        self.assertIn('tests.test_ms2_offline_csv_snapshot', command)
        for filename in b.CODE_FILES:
            self.assertTrue(any(str(Path(filename)) in argument for argument in command))
        self.assertNotIn('data/private', ' '.join(command))

    def test_no_argument_ever_accepted(self):
        output = io.StringIO()
        with patch.object(b, 'build') as build, contextlib.redirect_stdout(output):
            self.assertEqual(b.main(['private.csv']), 2)
        build.assert_not_called()
        self.assertNotIn('private.csv', output.getvalue())

    def test_missing_input_never_starts_build(self):
        with tempfile.TemporaryDirectory() as root, patch.object(b.subprocess, 'run') as proc:
            with self.assertRaises(OSError):
                b.build(Path(root))
            proc.assert_not_called()

    def test_exception_content_is_never_echoed(self):
        output = io.StringIO()
        with patch.object(b, 'build', side_effect=OSError('secret location')), \
             contextlib.redirect_stdout(output):
            self.assertEqual(b.main([]), 1)
        self.assertNotIn('secret', output.getvalue())


if __name__ == '__main__':
    unittest.main()
