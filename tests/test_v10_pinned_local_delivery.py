"""P0-23: no live OWNER machines, no network, no broker, no cutover.

Pins known-good Git blob hashes for P0-20/21/22 and exercises the delivery
bootstrap with disposable GitHub-hosted Windows fixtures only.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "downloads" / "RUN_V10_PRIVATE_MAP_AUDIT_V1.ps1"
DEPS = [
    "VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1",
    "VERIFY_V10_RESTORE_TARGET_MAP.ps1",
    "VERIFY_V10_ENCRYPTED_RESTORE_MAP.ps1",
]

@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "disposable Windows Actions only",
)
class PinnedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(prefix="v10-delivery-ci-", dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.repo = self.root / "repo"
        self.state = self.root / "starter"
        self.deps = self.root / "pinned-code"
        self.deps.mkdir()
        (self.repo / "downloads").mkdir(parents=True)
        self.state.mkdir()
        self.sentinel=self.repo / "DO_NOT_CHANGE.txt"
        self.sentinel.write_text("PRESERVE", encoding="utf-8")
        self.id = "20261017_045500_aabbccddee11"
        self.snapshot=self.state/"V10_cutover_snapshots"/self.id
        self.snapshot.mkdir(parents=True)
        spec=[
            ("starter/START_AI_COCKPIT.ps1",self.state/"START_AI_COCKPIT.ps1",b"old 1"),
            ("starter/AI_COCKPIT_START_DEBUG.cmd",self.state/"AI_COCKPIT_START_DEBUG.cmd",b"old 2"),
            ("repo/RUN_AI_COCKPIT_V10.ps1",self.repo/"downloads"/"RUN_AI_COCKPIT_V10.ps1",b"old 3"),
            ("repo/STOP_AI_COCKPIT_V10.ps1",self.repo/"downloads"/"STOP_AI_COCKPIT_V10.ps1",b"old 4"),
            ("repo/AI_COCKPIT_CONTROLLER_V10.ps1",self.repo/"downloads"/"AI_COCKPIT_CONTROLLER_V10.ps1",b"old 5"),
        ]
        entries=[]
        for rel,live,data in spec:
            live.parent.mkdir(parents=True,exist_ok=True)
            live.write_bytes(data)
            archive=self.snapshot / rel
            archive.parent.mkdir(parents=True,exist_ok=True)
            archive.write_bytes(data)
            entries.append({"name":rel,"bytes":len(data),
                "sha256":hashlib.sha256(data).hexdigest().upper()})
        manifest={
            "schema":"v10_cutover_backup_v1",
            "evidence_only":True,
            "no_changes_to_active_files":True,
            "real_submit_allowed":False,
            "source_pin_match":False,
            "desktop_inventory_complete":False,
            "unverified_desktop_indexes":[3],
            "cutover_eligible":False,
            "files":entries
        }
        (self.snapshot/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
        for filename in DEPS:
            # Windows checkout may convert LF to CRLF. Production delivery
            # downloads the raw Git blob, not checkout-expanded working bytes.
            # Reconstruct fixture exactly from the immutable Git object.
            raw=subprocess.check_output(
                ["git","show",f"HEAD:downloads/{filename}"],
                cwd=REPO, timeout=15
            )
            (self.deps/filename).write_bytes(raw)

    def run_audit(self, mode="Inspect", fixture=None, snapshot_id=None):
        args=[
            "powershell.exe","-NoLogo","-NoProfile","-NonInteractive",
            "-ExecutionPolicy","Bypass","-File",str(SCRIPT),
            "-Mode",mode,"-PinnedCommit","a"*40,
            "-SnapshotId",snapshot_id or self.id,
            "-RepoRoot",str(self.repo),"-StateRoot",str(self.state),
            "-FixtureRoot",str(fixture or self.deps)
        ]
        return subprocess.run(args,capture_output=True,text=True,errors="replace",timeout=55)

    def test_inspect_downloads_pinned_dependencies_and_cleans_temp(self):
        before={str(p.relative_to(self.root)):p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}
        p=self.run_audit()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("P0_23_RESULT=INSPECT_ONLY",p.stdout)
        self.assertIn("TARGET_MATCHED=5",p.stdout)
        self.assertIn("TARGET_MAP_STATUS=PARTIAL_HOLD",p.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false",p.stdout)
        self.assertNotIn(str(self.root),p.stdout)
        self.assertFalse((self.state/"V10_private_restore_maps").exists())
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes()
                      for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"),"PRESERVE")

    def test_single_execution_writes_and_verifies_private_evidence(self):
        p=self.run_audit(mode="SaveAndVerify")
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("P0_23_RESULT=ENCRYPTED_PARTIAL_HOLD",p.stdout)
        self.assertIn("ENCRYPTED_MAP_RECEIPT=VERIFIED_PARTIAL_HOLD",p.stdout)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",p.stdout)
        self.assertNotIn(str(self.root),p.stdout)
        private=list((self.state/"V10_private_restore_maps").glob("*.dpapi"))
        self.assertEqual(len(private),1)
        self.assertNotIn(b"START_AI_COCKPIT.ps1",private[0].read_bytes())
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"),"PRESERVE")

    def test_download_changed_bytes_refuses_before_any_scan_or_dpapi(self):
        path=self.deps/DEPS[1]
        path.write_bytes(path.read_bytes()+b"\n# tampered")
        p=self.run_audit(mode="SaveAndVerify")
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("P0_23_BLOCK_REASON=SCRIPT_BLOB_MISMATCH",p.stdout)
        self.assertIn("P0_23_RESULT=BLOCKED",p.stdout)
        self.assertFalse((self.state/"V10_private_restore_maps").exists())
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"),"PRESERVE")

    def test_missing_snapshot_denied_without_private_map(self):
        p=self.run_audit(mode="SaveAndVerify",snapshot_id="20261017_045500_123456789abc")
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("P0_23_BLOCK_REASON=SNAPSHOT_NOT_FOUND",p.stdout)
        self.assertFalse((self.state/"V10_private_restore_maps").exists())
        self.assertEqual(self.sentinel.read_text(encoding="utf-8"),"PRESERVE")

if __name__ == "__main__":
    unittest.main()
