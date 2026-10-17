"""P0-32: independent V2 metadata-only validation on disposable Windows hosts.

Original V1/P0-31 verifier and its tests remain unchanged. This suite never
acts on an OWNER machine, broker, workbook, or live cockpit.
"""
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v10_legacy_owner_readonly as owner
import test_v10_legacy_safe_stop as safe_stop

REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1"
V2 = REPO / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V2.ps1"


class MetadataOnlyStatic(unittest.TestCase):
    def test_v1_strict_verifier_preserved(self):
        original = V1.read_text(encoding="utf-8")
        new = V2.read_text(encoding="utf-8")
        self.assertIn('$fp.State=$fp.StateHash+"|"+$fp.StateTimestamp', original)
        self.assertIn('if($counts[$k] -cne "true"){Block ("CHANGED_DURING_CHECK_"+$k)}', original)
        self.assertNotIn("READONLY_METADATA_STABLE", original)
        self.assertIn("READONLY_METADATA_STABLE", new)
        self.assertIn('STATE_METADATA_ONLY_ACCEPTED', new)
        self.assertIn('STATE_RECHECK', new)
        self.assertIn('$recheck=Get-Fingerprint $rootFull', new)
        self.assertIn('$recheck.StateHash -ceq $before.StateHash', new)
        self.assertIn('$recheck.Listen -ceq $before.Listen', new)
        self.assertIn('$recheck.Excel -ceq $before.Excel', new)
        self.assertIn('$recheck.Launch -ceq $before.Launch', new)
        self.assertIn('$recheck.Result -ceq $before.Result', new)
        self.assertIn('$recheck.Evidence -ceq $before.Evidence', new)
        self.assertIn('@($entries | Where-Object { -not (Test-EntryAlive $_) }).Count -eq 0', new)
        self.assertIn('-not $IncludeStopDryRun', new)
        self.assertIn('if($counts.STATE_UNCHANGED -cne "true" -and -not $metadataAdmitted)', new)
        for s in ('STOP_ALLOWED=false', 'CUTOVER_ELIGIBLE=false', 'REAL_SUBMIT_ALLOWED=false',
                  'PROCESSES_STOPPED=0', 'EXCEL_ACTION=NONE'):
            self.assertIn('Write-Output "' + s + '"', new)
        for unsafe in ("Stop-Process", "Start-Process", "taskkill", "-ComObject", ".Kill("):
            self.assertNotIn(unsafe, new.split("#>", 1)[1])


@unittest.skipUnless(owner.ON_WINDOWS_ACTIONS, "Windows Actions synthetic session only")
class MetadataOnlyWindows(owner.OwnerReadonlyWindows):
    def run_verify_v2(self, *args, **kwargs):
        saved = owner.VERIFY
        try:
            owner.VERIFY = V2
            return self.run_verify(*args, **kwargs)
        finally:
            owner.VERIFY = saved

    def test_01_no_change_returns_original_readonly_result(self):
        self.start_session()
        original = self.state_path.read_bytes()
        r = self.run_verify_v2()
        self.assertEqual(r.returncode, 0)
        self.assertIn("P0_27_RESULT=READONLY_VERIFIED", r.stdout)
        self.assertIn("STATE_CHANGE_CLASS=NO_CHANGE", r.stdout)
        self.assertIn("STATE_RECHECK=NOT_REQUIRED", r.stdout)
        self.assert_session_untouched(original)

    def test_02_only_mtime_updates_can_be_rechecked_without_stop(self):
        self.start_session()
        original = self.state_path.read_bytes()
        stop = threading.Event()
        touches = [0]

        def touch():
            while not stop.is_set():
                os.utime(self.state_path, None)
                touches[0] += 1
                stop.wait(0.05)

        t = threading.Thread(target=touch, daemon=True)
        t.start()
        try:
            r = self.run_verify_v2()
        finally:
            stop.set()
            t.join(timeout=3)
        self.assertGreater(touches[0], 2)
        self.assertEqual(r.returncode, 0)
        for s in ("P0_27_RESULT=READONLY_METADATA_STABLE",
                  "STATE_CONTENT_UNCHANGED=true", "STATE_TIMESTAMP_UNCHANGED=false",
                  "STATE_CHANGE_CLASS=METADATA_ONLY", "STATE_UNCHANGED=false",
                  "STATE_METADATA_ONLY_ACCEPTED=true", "STATE_RECHECK=PASS"):
            self.assertIn(s, r.stdout)
        self.assert_session_untouched(original)

    def test_03_content_mutation_remains_blocked(self):
        self.start_session()
        stop = threading.Event()

        def mutate():
            while not stop.is_set():
                with self.state_path.open("ab") as stream:
                    stream.write(b" ")
                stop.wait(0.05)

        t = threading.Thread(target=mutate, daemon=True)
        t.start()
        try:
            r = self.run_verify_v2()
        finally:
            stop.set()
            t.join(timeout=3)
        self.assert_blocked(r, "CHANGED_DURING_CHECK_STATE_UNCHANGED")
        self.assertIn("STATE_CHANGE_CLASS=CONTENT_CHANGED", r.stdout)
        self.assertIn("STATE_METADATA_ONLY_ACCEPTED=false", r.stdout)
        self.assert_nothing_stopped()


# Do not re-run inherited stopping synthetic tests in this focused suite.
for _class in (owner.OwnerReadonlyWindows, safe_stop.LegacySessionSafeStop):
    for _name in dir(_class):
        if _name.startswith("test_"):
            setattr(MetadataOnlyWindows, _name, None)

if __name__ == "__main__":
    unittest.main()
