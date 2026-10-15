"""Allowlist and privacy tests for the offline code-only delivery bundle."""
from pathlib import Path
import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts import build_ms2_offline_bundle as b


class BundleTests(unittest.TestCase):
    def test_build_contains_exact_code_only_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = b.build_package(output_dir=folder)
            with ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), set(b.FILES))
                for item in b.FILES:
                    self.assertEqual(z.read(item), (b.ROOT / item).read_bytes())
            self.assertEqual(archive.name, b.ARCHIVE_NAME)

    def test_no_private_or_account_paths(self):
        for filename in b.FILES:
            self.assertFalse(Path(filename).is_absolute())
            self.assertNotIn('..', Path(filename).parts)
            self.assertNotIn('data', Path(filename).parts)
            self.assertNotIn('account', filename.lower())
            self.assertNotIn('secret', filename.lower())
            self.assertNotIn('kioxia_ticks_', filename.lower())

    def test_missing_allowlisted_file_refuses_without_archive(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            with self.assertRaises(OSError):
                b.build_package(root, out)
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_linked_output_refused_and_does_not_create_archive(self):
        with tempfile.TemporaryDirectory() as out:
            with patch.object(b, '_checked_path', side_effect=ValueError('PATH_LINK')):
                with self.assertRaises(ValueError):
                    b.build_package(output_dir=out)
            self.assertEqual(list(Path(out).iterdir()), [])

    def test_second_build_never_replaces_package(self):
        with tempfile.TemporaryDirectory() as out:
            archive = b.build_package(output_dir=out)
            first = archive.read_bytes()
            with self.assertRaises(FileExistsError):
                b.build_package(output_dir=out)
            self.assertEqual(archive.read_bytes(), first)

    def test_main_argument_refusal_does_not_read(self):
        capture = io.StringIO()
        with patch.object(b, 'build_package') as build, contextlib.redirect_stdout(capture):
            self.assertEqual(b.main(['private.csv']), 2)
        build.assert_not_called()
        self.assertNotIn('private.csv', capture.getvalue())

    def test_build_failure_never_prints_paths(self):
        capture = io.StringIO()
        with patch.object(b, 'build_package', side_effect=OSError('SECRET personal path')), \
             contextlib.redirect_stdout(capture):
            self.assertEqual(b.main([]), 1)
        self.assertNotIn('SECRET', capture.getvalue())


if __name__ == '__main__':
    unittest.main()
