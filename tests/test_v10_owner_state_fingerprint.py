"""P0-31: read-only state fingerprint classification on disposable Windows hosts.

Requires a running synthetic session. Never touches the OWNER's computer.
"""
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v10_legacy_owner_readonly as owner
import test_v10_legacy_safe_stop as safe_stop

VERIFY = Path(__file__).resolve().parents[1] / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1"


class StateFingerprintStatic(unittest.TestCase):
    def test_fail_closed_gate_is_identical(self):
        code = VERIFY.read_text(encoding="utf-8")
        self.assertIn('Sha256Bytes $b', code)
        self.assertIn('LastWriteTimeUtc.Ticks', code)
        self.assertIn('$fp.State=$fp.StateHash+"|"+$fp.StateTimestamp', code)
        self.assertIn('if($counts[$k] -cne "true"){Block ("CHANGED_DURING_CHECK_"+$k)}', code)
        for token in ('STATE_CONTENT_UNCHANGED', 'STATE_TIMESTAMP_UNCHANGED',
                      'STATE_CHANGE_CLASS', 'METADATA_ONLY', 'CONTENT_CHANGED', 'NO_CHANGE',
                      'STOP_ALLOWED=false', 'CUTOVER_ELIGIBLE=false', 'REAL_SUBMIT_ALLOWED=false'):
            self.assertIn(token, code)
        for leaked in ('Write-Output ("STATE_HASH=', 'Write-Output ("STATE_TIMESTAMP='):
            self.assertNotIn(leaked, code)


@unittest.skipUnless(owner.ON_WINDOWS_ACTIONS, "Windows GitHub Actions synthetic only")
class StateFingerprintLive(owner.OwnerReadonlyWindows):
    def test_01_touch_mtime_blocks_but_content_is_unchanged(self):
        self.start_session()
        baseline = self.state_path.read_bytes()
        stop = threading.Event()
        count = [0]

        def writer():
            while not stop.is_set():
                os.utime(self.state_path, None)  # metadata only, synthetic state
                count[0] += 1
                stop.wait(0.05)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            r = self.run_verify()
        finally:
            stop.set()
            thread.join(timeout=3)

        self.assertGreater(count[0], 2)
        self.assert_blocked(r, "CHANGED_DURING_CHECK_STATE_UNCHANGED")
        self.assertIn("P0_27_BLOCK_STAGE=FINGERPRINT_AFTER", r.stdout)
        self.assertIn("STATE_CONTENT_UNCHANGED=true", r.stdout)
        self.assertIn("STATE_TIMESTAMP_UNCHANGED=false", r.stdout)
        self.assertIn("STATE_CHANGE_CLASS=METADATA_ONLY", r.stdout)
        self.assertEqual(self.state_path.read_bytes(), baseline)
        self.assert_nothing_stopped()

    def test_02_valid_json_content_refresh_remains_blocked(self):
        self.start_session()
        stop = threading.Event()
        count = [0]

        def writer():
            # JSON stays valid (trailing whitespace), but bytes change.
            while not stop.is_set():
                with self.state_path.open("ab") as stream:
                    stream.write(b" ")
                count[0] += 1
                stop.wait(0.06)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        try:
            r = self.run_verify()
        finally:
            stop.set()
            thread.join(timeout=3)

        self.assertGreater(count[0], 2)
        self.assert_blocked(r, "CHANGED_DURING_CHECK_STATE_UNCHANGED")
        self.assertIn("P0_27_BLOCK_STAGE=FINGERPRINT_AFTER", r.stdout)
        self.assertIn("STATE_CONTENT_UNCHANGED=false", r.stdout)
        self.assertIn("STATE_CHANGE_CLASS=CONTENT_CHANGED", r.stdout)
        self.assert_nothing_stopped()


# Avoid inheriting safe-stop or other destructive tests into this focused suite.
for _name in dir(owner.OwnerReadonlyWindows):
    if _name.startswith("test_"):
        setattr(StateFingerprintLive, _name, None)
for _name in dir(safe_stop.LegacySessionSafeStop):
    if _name.startswith("test_"):
        setattr(StateFingerprintLive, _name, None)

if __name__ == "__main__":
    unittest.main()
