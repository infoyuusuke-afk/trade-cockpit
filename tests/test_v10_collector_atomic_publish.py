"""Synthetic-only Collector atomic publish contract; no Excel or V10 start."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"


class AtomicPublishTests(unittest.TestCase):
    def _function(self):
        text = COLLECTOR.read_text(encoding="utf-8-sig")
        start = text.index("function Write-AtomicUtf8(")
        end = text.index("\nfunction Ensure-Csv(", start)
        return text[start:end]

    def test_static_no_fixed_tmp_and_no_overwrite_move_item(self):
        src = self._function()
        self.assertIn("[Guid]::NewGuid()", src)
        self.assertIn("[IO.File]::Replace", src)
        self.assertIn("[IO.File]::Move", src)
        self.assertNotIn("Move-Item -Force", src)
        self.assertIn("finally", src)

    def test_windows_replace_and_initial_create_preserve_complete_json(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("Windows PowerShell 5.1 required, synthetic Windows job validates")
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "test-publish.json"
            ps = self._function() + "\n" + r'''
$ErrorActionPreference='Stop'
$p=$env:COCKPIT_ATOMIC_TEST_PATH
Write-AtomicUtf8 $p '{"generation":1}'
if(-not [IO.File]::Exists($p)){throw 'FIRST_PUBLISH_FAILED'}
Write-AtomicUtf8 $p '{"generation":2}'
$a=[IO.File]::ReadAllText($p)
if($a -ne '{"generation":2}'){throw 'SECOND_PUBLISH_FAILED'}
if(@(Get-ChildItem -LiteralPath (Split-Path $p) -Filter '*.tmp').Count -ne 0){throw 'STAGING_LEAK'}
if(@(Get-ChildItem -LiteralPath (Split-Path $p) -Filter '*.bak').Count -ne 0){throw 'BACKUP_LEAK'}
'''
            result = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", ps],
                env={**os.environ, "COCKPIT_ATOMIC_TEST_PATH": str(destination)},
                capture_output=True, text=True, timeout=15, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)


    def test_windows_locked_reader_cannot_destroy_previous_good_snapshot(self):
        exe = shutil.which("powershell.exe")
        if not exe:
            self.skipTest("Windows PowerShell 5.1 required")
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "test-publish.json"
            ps = self._function() + "\n" + r'''
$ErrorActionPreference='Stop'
$p=$env:COCKPIT_ATOMIC_TEST_PATH
Write-AtomicUtf8 $p '{"generation":1}'
# A reader intentionally disallows DELETE sharing, as on some antivirus
# and browser/bridge access paths. Publication must fail boundedly and
# leave the last complete snapshot available to readers.
$reader = [IO.File]::Open($p,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
$blocked=$false
try {
    try { Write-AtomicUtf8 $p '{"generation":2}' }
    catch { $blocked=$true }
}
finally { $reader.Dispose() }
if (-not $blocked) { throw 'LOCKED_REPLACE_NOT_BLOCKED' }
if ([IO.File]::ReadAllText($p) -ne '{"generation":1}') { throw 'LAST_GOOD_NOT_PRESERVED' }
Write-AtomicUtf8 $p '{"generation":3}'
if ([IO.File]::ReadAllText($p) -ne '{"generation":3}') { throw 'POST_LOCK_RETRY_FAILED' }
if (@(Get-ChildItem -LiteralPath (Split-Path $p) -Filter '*.tmp').Count -ne 0) { throw 'STAGING_LEAK' }
if (@(Get-ChildItem -LiteralPath (Split-Path $p) -Filter '*.bak').Count -ne 0) { throw 'BACKUP_LEAK' }
'''
            result = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", ps],
                env={**os.environ, "COCKPIT_ATOMIC_TEST_PATH": str(destination)},
                capture_output=True, text=True, timeout=15, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)



if __name__ == "__main__":
    unittest.main()
