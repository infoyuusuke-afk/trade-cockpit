"""Fixed allowlist and no security-bypass protection regression."""
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts import build_ms2_native_bundle as b

class NativeBundleTests(unittest.TestCase):
    def test_fixed_code_only_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            zpath = b.build(output_dir=folder)
            with ZipFile(zpath) as z:
                self.assertEqual(set(z.namelist()), set(b.FILES))
                for name in b.FILES:
                    self.assertEqual(z.read(name), (b.ROOT / name).read_bytes())
        for item in b.FILES:
            self.assertFalse(Path(item).is_absolute())
            self.assertNotIn('..', Path(item).parts)
            self.assertNotIn('data', Path(item).parts)
            self.assertFalse(item.lower().endswith(('.exe', '.csv', '.pem', '.pfx')))

    def test_no_windows_policy_bypass_or_network_api(self):
        text = (b.ROOT / 'scripts/ms2_native_offline_capture.ps1').read_text()
        cmd = (b.ROOT / 'START_MS2_SAFE_CAPTURE.cmd').read_text()
        combined = (text + cmd).casefold()
        for token in ('executionpolicy bypass', 'set-executionpolicy', 'unblock-file',
                      'invoke-webrequest', 'invoke-restmethod', 'start-process -verb runas',
                      'http://', 'https://', 'curl.exe'):
            self.assertNotIn(token, combined)
        self.assertIn('-NoProfile -STA -File', cmd)
        self.assertIn('D:\\AI_Cockpit_Data\\MS2_CSV', text)
        self.assertIn('Read-Stable', text)
        self.assertIn('PRESERVED_UNAUTHENTICATED', text)

    def test_reject_arguments(self):
        self.assertEqual(b.main(['secret.csv']), 2)

if __name__ == '__main__':
    unittest.main()
