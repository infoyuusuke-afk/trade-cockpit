"""P0-21: Windows-only synthetic archive/target comparison.

Must never access OWNER profile, MS2, broker CSVs or the real PC checkout.
"""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "downloads" / "VERIFY_V10_RESTORE_TARGET_MAP.ps1"

@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "synthetic Windows fixture only",
)
class ReadOnlyRestoreMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p0-21-", dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "current-repo"
        (self.repo / "downloads").mkdir(parents=True)
        self.state = self.root / "starter"
        self.state.mkdir()
        self.d1 = self.root / "first-current-desktop"
        self.d2 = self.root / "second-current-desktop"
        self.d1.mkdir()
        self.d2.mkdir()
        self.snap = self.root / "20261017_044407_aabbccddee11"
        self.snap.mkdir()
        self.entries = {
            "starter/START_AI_COCKPIT.ps1": (self.state / "START_AI_COCKPIT.ps1", b"# old starter"),
            "starter/AI_COCKPIT_START_DEBUG.cmd": (self.state / "AI_COCKPIT_START_DEBUG.cmd", b"@echo off old"),
            "repo/RUN_AI_COCKPIT_V10.ps1": (self.repo / "downloads" / "RUN_AI_COCKPIT_V10.ps1", b"# old run"),
            "repo/STOP_AI_COCKPIT_V10.ps1": (self.repo / "downloads" / "STOP_AI_COCKPIT_V10.ps1", b"# old stop"),
            "repo/AI_COCKPIT_CONTROLLER_V10.ps1": (self.repo / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1", b"# old ctl"),
            # Intentionally REVERSE the ordinal to reject ordinal-to-path assumptions.
            "desktop2/AI Cockpit STOP.cmd": (self.d1 / "AI Cockpit STOP.cmd", b"@echo off, shutdown placeholder"),
            "desktop1/AI Cockpit START.lnk": (self.d2 / "AI Cockpit START.lnk", b"synthetic fake LNK for hash only"),
        }
        self.expected = {}
        receipts=[]
        for rel,(dest,data) in self.entries.items():
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(data)
            source = self.snap / rel
            source.parent.mkdir(parents=True,exist_ok=True)
            source.write_bytes(data)
            self.expected[rel] = data
            receipts.append({"name":rel,"bytes":len(data),
                             "sha256":hashlib.sha256(data).hexdigest().upper()})
        self.manifest = {
            "schema":"v10_cutover_backup_v1",
            "evidence_only":True,
            "no_changes_to_active_files":True,
            "real_submit_allowed":False,
            "source_pin_match":False,
            "desktop_inventory_complete":False,
            "unverified_desktop_indexes":[3],
            "unverified_desktop_actions":["DESKTOP_ATTRIBUTES"],
            "cutover_eligible":False,
            "files":receipts,
        }
        self.save()

    def save(self):
        (self.snap / "manifest.json").write_text(json.dumps(self.manifest),encoding="utf-8")

    def invoke(self, roots=None, snap=None):
        def q(v):
            return "'" + str(v).replace("'", "''") + "'"
        if roots is None:
            roots=[self.d1,self.d2]
        cmd=(f"& {q(SCRIPT)} -Snapshot {q(snap or self.snap)} "
             f"-RepoRoot {q(self.repo)} -StateRoot {q(self.state)} "
             f"-DesktopRoots @({','.join(q(p) for p in roots)})")
        token=base64.b64encode(cmd.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            ["powershell.exe","-NoProfile","-NonInteractive",
             "-EncodedCommand",token],
            capture_output=True,text=True,errors="replace",timeout=30
        )

    def assert_safe(self,result):
        self.assertIn("REAL_SUBMIT_ALLOWED=false",result.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false",result.stdout)
        self.assertNotIn(str(self.root),result.stdout)
        self.assertNotIn("LIVE_FILES_MODIFIED=true",result.stdout)

    def test_reversed_desktop_ordinals_match_by_name_and_sha(self):
        before={str(p.relative_to(self.root)):p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}
        p=self.invoke()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        for marker in (
            "SNAPSHOT_ENTRY_COUNT=7","TARGET_MATCHED=7",
            "TARGET_MISSING_OR_CHANGED=0","TARGET_AMBIGUOUS=0",
            "DESKTOP_TARGETS_MATCHED=2","UNVERIFIED_DESKTOP_ROOTS=0",
            "SNAPSHOT_INVENTORY_PARTIAL=true",
            "ORIGINAL_ABSOLUTE_PATHS_EXPORTED=false",
            "TARGET_MAP_STATUS=PARTIAL_HOLD",
        ):
            self.assertIn(marker,p.stdout)
        self.assert_safe(p)
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()})

    def test_hash_collision_two_desktops_is_ambiguous(self):
        duplicate=self.d1/"AI Cockpit START.lnk"
        duplicate.write_bytes(self.entries["desktop1/AI Cockpit START.lnk"][1])
        p=self.invoke()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("TARGET_AMBIGUOUS=1",p.stdout)
        self.assertIn("TARGET_MAP_STATUS=PARTIAL_HOLD",p.stdout)
        self.assert_safe(p)

    def test_live_file_modified_since_backup_must_not_match(self):
        (self.state/"START_AI_COCKPIT.ps1").write_bytes(b"changed after backup")
        p=self.invoke()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("TARGET_MISSING_OR_CHANGED=1",p.stdout)
        self.assertIn("TARGET_MATCHED=6",p.stdout)
        self.assert_safe(p)

    def test_missing_shortcut_is_unmapped(self):
        (self.d2/"AI Cockpit START.lnk").unlink()
        p=self.invoke()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("DESKTOP_TARGETS_MATCHED=1",p.stdout)
        self.assertIn("TARGET_MISSING_OR_CHANGED=1",p.stdout)
        self.assert_safe(p)

    def test_unverified_third_root_is_not_silent(self):
        p=self.invoke([self.d1,self.d2,self.root/"old-account-not-used"])
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("UNVERIFIED_DESKTOP_ROOTS=1",p.stdout)
        self.assertIn("UNVERIFIED_DESKTOP_ROOT_INDEX=3",p.stdout)
        self.assertIn("TARGET_MAP_STATUS=PARTIAL_HOLD",p.stdout)
        self.assert_safe(p)

    def test_duplicate_root_is_fail_closed(self):
        p=self.invoke([self.d1,self.d1])
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("TARGET_MAP_STATUS=BLOCKED",p.stdout)
        self.assertIn("BLOCK_REASON=DUPLICATE_ROOT",p.stdout)
        self.assert_safe(p)

    def test_tampered_snapshot_refuses_all_mapping(self):
        (self.snap/"starter/START_AI_COCKPIT.ps1").write_bytes(b"TAMPERED")
        p=self.invoke()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("BLOCK_REASON=SNAPSHOT_NOT_VERIFIED",p.stdout)
        self.assertIn("TARGET_MAP_STATUS=BLOCKED",p.stdout)
        self.assert_safe(p)

    def test_manifest_real_submit_flag_refused(self):
        self.manifest["real_submit_allowed"]=True
        self.save()
        p=self.invoke()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("BLOCK_REASON=SNAPSHOT_NOT_VERIFIED",p.stdout)
        self.assert_safe(p)

    def test_unicode_name_matches_without_encoding_regression(self):
        name="AIコクピット_安全停止.cmd"
        data=b"synthetic unicode name"
        new=self.d1/name
        new.write_bytes(data)
        rel="desktop4/"+name
        snap=self.snap/rel
        snap.parent.mkdir(parents=True,exist_ok=True)
        snap.write_bytes(data)
        self.manifest["files"].append({
            "name":rel,"sha256":hashlib.sha256(data).hexdigest().upper(),
            "bytes":len(data)
        })
        self.save()
        p=self.invoke()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("TARGET_MATCHED=8",p.stdout)
        self.assertIn("DESKTOP_TARGETS_MATCHED=3",p.stdout)
        self.assert_safe(p)

if __name__=="__main__":
    unittest.main()
