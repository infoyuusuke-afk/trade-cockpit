"""P0-20: isolated GitHub Windows tests for local snapshot restore rehearsal.

The test does not operate any live OWNER shortcut, Git checkout or workbook.
"""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "downloads" / "VERIFY_V10_SNAPSHOT_RESTORE_REHEARSAL.ps1"

@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "Windows-only disposable snapshot testing",
)
class RehearseSnapshotTest(unittest.TestCase):
    def setUp(self):
        # Keep fixture within Windows' actual OS TEMP for strict destination gate.
        self.temp = tempfile.TemporaryDirectory(prefix="p0-20-", dir=os.environ["TEMP"])
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.snapshot=self.root/"20261017_194420_abcdef012345"
        self.snapshot.mkdir()
        self.stage=self.root/"staging"
        self.entries={
            "starter/START_AI_COCKPIT.ps1":b"synthetic old starter",
            "starter/AI_COCKPIT_START_DEBUG.cmd":b"synthetic old debug",
            "repo/RUN_AI_COCKPIT_V10.ps1":b"synthetic V10 runner",
            "repo/STOP_AI_COCKPIT_V10.ps1":b"synthetic old V10 stop",
            "repo/AI_COCKPIT_CONTROLLER_V10.ps1":b"synthetic old Controller",
            "desktop1/AI_COCKPIT_STOP.cmd":b"synthetic stop cmd",
            "desktop2/AI Cockpit START.lnk":b"synthetic fake shortcut bytes",
        }
        receipts=[]
        for rel,data in self.entries.items():
            loc=self.snapshot/rel
            loc.parent.mkdir(parents=True,exist_ok=True)
            loc.write_bytes(data)
            receipts.append({"name":rel,
                "sha256":hashlib.sha256(data).hexdigest().upper(),
                "bytes":len(data)})
        self.manifest={
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
        self.outside=self.root/"active-not-to-touch"
        self.outside.mkdir()
        (self.outside/"AI_COCKPIT_CONTROLLER_V10.ps1").write_text("LIVE-DO-NOT-TOUCH",encoding="utf-8")

    def save(self):
        (self.snapshot/"manifest.json").write_text(json.dumps(self.manifest),encoding="utf-8")

    def verify(self, mode="VerifyOnly", parent=None):
        return subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
            "-ExecutionPolicy","Bypass","-File",str(SCRIPT),
            "-Snapshot",str(self.snapshot),"-Mode",mode,
            "-StageParent",str(parent or self.stage)],
            capture_output=True,text=True,errors="replace",timeout=30)

    def check_block(self,result,reason):
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertIn("SNAPSHOT_RECEIPT=BLOCKED",result.stdout)
        self.assertIn("BLOCK_REASON="+reason,result.stdout)
        self.assertNotIn(str(self.root),result.stdout)
        self.assertFalse(self.stage.exists())

    def test_verify_only_is_readonly_and_reports_partial(self):
        before={str(p.relative_to(self.snapshot)):p.read_bytes()
                for p in self.snapshot.rglob("*") if p.is_file()}
        p=self.verify()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        for token in ["SNAPSHOT_FILES_VERIFIED=7",
                      "SNAPSHOT_INVENTORY=PARTIAL",
                      "SNAPSHOT_RECEIPT=VERIFY_PASS",
                      "CUTOVER_ELIGIBLE=false","REAL_SUBMIT_ALLOWED=false"]:
            self.assertIn(token,p.stdout)
        self.assertFalse(self.stage.exists())
        self.assertEqual(before,{str(p.relative_to(self.snapshot)):p.read_bytes()
                            for p in self.snapshot.rglob("*") if p.is_file()})
        self.assertEqual((self.outside/"AI_COCKPIT_CONTROLLER_V10.ps1").read_text(
            encoding="utf-8"),"LIVE-DO-NOT-TOUCH")

    def test_rehearsal_copies_to_new_temp_with_hashes(self):
        p=self.verify(mode="Rehearse")
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("SNAPSHOT_RECEIPT=REHEARSAL_PASS",p.stdout)
        self.assertIn("REHEARSAL_ISOLATED_TEMP=true",p.stdout)
        self.assertIn("LIVE_FILES_MODIFIED=false",p.stdout)
        targets=list(self.stage.iterdir())
        self.assertEqual(len(targets),1)
        for rel,data in self.entries.items():
            self.assertEqual((targets[0]/rel).read_bytes(),data)
            self.assertEqual((self.snapshot/rel).read_bytes(),data)
        self.assertEqual((self.outside/"AI_COCKPIT_CONTROLLER_V10.ps1").read_text(
            encoding="utf-8"),"LIVE-DO-NOT-TOUCH")

    def test_modified_source_hash_refused_without_stage(self):
        (self.snapshot/"starter/START_AI_COCKPIT.ps1").write_bytes(b"tampered")
        self.check_block(self.verify(mode="Rehearse"),"ENTRY_SIZE_MISMATCH")

    def test_same_length_modified_hash_refused(self):
        path=self.snapshot/"starter/START_AI_COCKPIT.ps1"
        path.write_bytes(b"x"*len(self.entries["starter/START_AI_COCKPIT.ps1"]))
        self.check_block(self.verify(mode="Rehearse"),"ENTRY_HASH_MISMATCH")

    def test_path_traversal_refused(self):
        self.manifest["files"][0]["name"]="../outside/AI.cmd"
        self.save()
        self.check_block(self.verify(mode="Rehearse"),"UNSAFE_ENTRY_PATH")

    def test_duplicate_case_insensitive_entries_refused(self):
        self.manifest["files"].append(dict(self.manifest["files"][0]))
        self.manifest["files"][-1]["name"]="starter/start_ai_cockpit.ps1"
        self.save()
        # Lower-case starter file matches allow-list case-sensitively and
        # will be denied as unsafe rather than silently overwriting it.
        result=self.verify(mode="Rehearse")
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)
        self.assertIn("SNAPSHOT_RECEIPT=BLOCKED",result.stdout)
        self.assertFalse(self.stage.exists())

    def test_missing_required_entry_refused(self):
        self.manifest["files"]=[x for x in self.manifest["files"]
            if x["name"]!="starter/AI_COCKPIT_START_DEBUG.cmd"]
        self.save()
        self.check_block(self.verify(mode="Rehearse"),"REQUIRED_ENTRY_ABSENT")

    def test_manifest_cannot_enable_real_trades(self):
        self.manifest["real_submit_allowed"]=True
        self.save()
        self.check_block(self.verify(mode="Rehearse"),"MANIFEST_CONTRACT_INVALID")

    def test_stage_must_be_in_temp(self):
        self.check_block(self.verify(mode="Rehearse",parent=Path("C:/Windows/Temp")/
                                     "V10-UNAPPROVED-LOCATION"),"STAGING_MUST_BE_IN_TEMP")

    def test_stage_parent_junction_cannot_redirect_copy(self):
        real=self.root/"junction-target"
        real.mkdir()
        (real/"must_remain").write_text("PRESERVED",encoding="utf-8")
        junction=self.root/"stage-junction"
        mk=subprocess.run(["cmd.exe","/c","mklink","/J",str(junction),str(real)],
            capture_output=True,text=True,timeout=15)
        if mk.returncode!=0:
            self.skipTest("Unable to create temporary junction")
        p=self.verify(mode="Rehearse",parent=junction)
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("BLOCK_REASON=REPARSE_REFUSED",p.stdout)
        self.assertIn("SNAPSHOT_RECEIPT=BLOCKED",p.stdout)
        self.assertEqual((real/"must_remain").read_text(encoding="utf-8"),
                         "PRESERVED")
        self.assertEqual([x.name for x in real.iterdir()],["must_remain"])

    def test_snapshot_directory_reparse_refused(self):
        actual=self.root/"real-source"
        actual.mkdir()
        for p in self.snapshot.iterdir():
            target=actual/p.name
            if p.is_file():
                target.write_bytes(p.read_bytes())
            elif p.is_dir():
                target.mkdir()
                for q in p.iterdir():
                    (target/q.name).write_bytes(q.read_bytes())
        # Make the snapshot path a junction; the auditor must not follow it.
        import shutil
        shutil.rmtree(self.snapshot)
        create=subprocess.run(["cmd.exe","/c","mklink","/J",
            str(self.snapshot),str(actual)],capture_output=True,text=True,timeout=15)
        if create.returncode!=0:
            self.skipTest("Unable to create synthetic NTFS reparse fixture")
        self.check_block(self.verify(mode="Rehearse"),"REPARSE_REFUSED")

if __name__=="__main__":
    unittest.main()
