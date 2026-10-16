"""P0-24: Switch and rollback only synthetic desktop launch shortcuts.

Runs only on disposable Windows Actions runner. No real user desktop, MS2, Excel,
BRAIN or broker account interactions are performed.
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
SCRIPT=REPO/"downloads"/"SWITCH_V10_OWNER_LAUNCH_ROUTE.ps1"
BRANCH="fix/p0-v10-brain-safe-stop-preflight-20261017"

@unittest.skipUnless(os.name=="nt" and os.environ.get("GITHUB_ACTIONS")=="true"
                     and os.environ.get("RUNNER_OS")=="Windows",
                     "Windows disposable GitHub runner only")
class SafeRouteSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="p0-route-",dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/"starter-state"
        self.state.mkdir()
        self.desktop=self.root/"active-desktop"
        self.desktop.mkdir()
        self.source=self.root/"git-source"
        self.source.mkdir()
        (self.source/"downloads").mkdir()
        for name in ["RUN_AI_COCKPIT_V10.ps1",
                     "STOP_AI_COCKPIT_V10.ps1",
                     "AI_COCKPIT_CONTROLLER_V10.ps1"]:
            shutil.copyfile(REPO/"downloads"/name,self.source/"downloads"/name)
        self.git("init","-b",BRANCH)
        self.git("add","downloads")
        self.git("-c","user.name=synthetic",
                 "-c","user.email=synthetic@example.invalid",
                 "commit","-m","CI dummy launcher fixture")
        self.sha=self.git("rev-parse","HEAD").stdout.strip()
        self.link=self.desktop/"AI Cockpit START.lnk"
        self.make_link(self.link)
        self.before=self.link.read_bytes()
        self.work_excel=self.root/"work-excel-not-to-touch.xlsx"
        self.work_excel.write_bytes(b"synthetic protected workbook placeholder")

    def git(self,*args):
        p=subprocess.run(["git",*args],cwd=self.source,
                         capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        return p

    def make_link(self,path):
        q=lambda x:"'"+str(x).replace("'","''")+"'"
        ps=(f"$s=New-Object -ComObject WScript.Shell; $l=$s.CreateShortcut({q(path)}); "
            f"$l.TargetPath='C:\\Windows\\System32\\cmd.exe'; "
            f"$l.Arguments='/k \"\"{self.state}\\AI_COCKPIT_START_DEBUG.cmd\"\"'; "
            f"$l.WorkingDirectory={q(self.state)}; $l.Save()")
        encoded=base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
                          "-EncodedCommand",encoded],
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def write_dormant_state(self, controller_pid=2147000000):
        state={
            "controller_pid":controller_pid,
            "session_id":1,
            "started_at":"2026-10-01T09:01:00",
            "repo_root":str(self.source),
            "runtime_dir":str(self.root/"runtime"),
            "brain_observer_pid":0,
            "excel_pid":0,
            "collector_pid":0,
            "watcher_pid":0,
            "heartbeat_pid":0,
            "gateway_pid":0,
            "brain_gateway_pid":0,
            "voice_bridge_pid":0,
            "shadow_supervisor_pid":0,
            "sbv2_pid":0
        }
        (self.state/"V10_CONTROLLER_STATE.json").write_text(
            json.dumps(state),encoding="utf-8")
        return (self.state/"V10_CONTROLLER_STATE.json").read_bytes()

    def run_switch(self,mode="Switch",pin=None,switch_id=None,
                   archive_stale=False):

        args=["powershell.exe","-NoProfile","-NonInteractive",
              "-ExecutionPolicy","Bypass","-File",str(SCRIPT),
              "-Mode",mode,"-StateRoot",str(self.state),
              "-FixtureRepo",str(self.source),
              "-FixtureDesktopRoot",str(self.desktop)]
        if mode=="Switch":
            args+=["-PinnedSha",pin or self.sha]
        else:
            args+=["-SwitchId",switch_id or ""]
        if archive_stale:
            args+=["-ArchiveVerifiedStaleState"]
        return subprocess.run(args,capture_output=True,text=True,
                              errors="replace",timeout=90)

    def assert_not_changed(self):
        self.assertEqual(self.work_excel.read_bytes(),
                         b"synthetic protected workbook placeholder")

    def test_switch_pinned_shortcut_without_starting(self):
        p=self.run_switch()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_SWITCH=PASS_NOT_STARTED",p.stdout)
        self.assertIn("NO_APP_STARTED=true",p.stdout)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",p.stdout)
        self.assertNotEqual(self.link.read_bytes(),self.before)
        stop=self.desktop/"AI Cockpit V10 SAFE STOP.lnk"
        self.assertTrue(stop.is_file())
        switch_id=re.findall(r"V10_SWITCH_ID=([0-9a-f]{32})",p.stdout)
        self.assertEqual(len(switch_id),1,p.stdout)
        backup_dir=self.state/("V10_route_cutover_"+switch_id[0])
        self.assertEqual((backup_dir/"original-start.lnk").read_bytes(),self.before)
        self.assertIn(self.sha,(backup_dir/"START_PINNED_V10.cmd").read_text())
        self.assertIn("STOP_AI_COCKPIT_V10.ps1",
                      (backup_dir/"STOP_PINNED_V10.cmd").read_text())
        self.assertTrue((backup_dir/"receipt.dpapi").is_file())
        self.assert_not_changed()

    def test_switch_then_explicit_rollback(self):
        sw=self.run_switch()
        self.assertEqual(sw.returncode,0,sw.stdout+sw.stderr)
        cutover=re.findall(r"V10_SWITCH_ID=([0-9a-f]{32})",sw.stdout)[0]
        rb=self.run_switch(mode="Rollback",switch_id=cutover)
        self.assertEqual(rb.returncode,0,rb.stdout+rb.stderr)
        self.assertIn("V10_ROUTE_ROLLBACK=PASS",rb.stdout)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assertFalse((self.desktop/"AI Cockpit V10 SAFE STOP.lnk").exists())
        self.assert_not_changed()

    def test_live_v10_state_blocks_before_clone_or_shortcut_change(self):
        (self.state/"V10_CONTROLLER_STATE.json").write_text("synthetic")
        p=self.run_switch()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=STATE_FILE_INVALID",p.stdout)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assertFalse(list(self.state.glob("V10_release_*")))
        self.assert_not_changed()

    def test_dormant_state_probe_does_not_modify_source(self):
        old=self.write_dormant_state()
        p=self.run_switch(mode="InspectState")
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("STATE_STATUS=VERIFIED_DORMANT",p.stdout)
        self.assertIn("STATE_FILE_MODIFIED=false",p.stdout)
        self.assertEqual((self.state/"V10_CONTROLLER_STATE.json").read_bytes(),old)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assertFalse(list(self.state.glob("V10_release_*")))
        self.assert_not_changed()

    def test_dormant_state_without_explicit_archive_blocks(self):
        old=self.write_dormant_state()
        p=self.run_switch()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=ACTIVE_V10_STATE",p.stdout)
        self.assertEqual((self.state/"V10_CONTROLLER_STATE.json").read_bytes(),old)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assert_not_changed()

    def test_explicit_archive_then_switch_and_rollback_restores_state(self):
        old=self.write_dormant_state()
        p=self.run_switch(archive_stale=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_SWITCH=PASS_NOT_STARTED",p.stdout)
        self.assertIn("OLD_STATE_ARCHIVED=true",p.stdout)
        self.assertFalse((self.state/"V10_CONTROLLER_STATE.json").exists())
        switch_id=re.findall(r"V10_SWITCH_ID=([0-9a-f]{32})",p.stdout)[0]
        backup=self.state/("V10_route_cutover_"+switch_id)
        self.assertEqual((backup/"prior-controller-state.json").read_bytes(),old)
        p2=self.run_switch(mode="Rollback",switch_id=switch_id)
        self.assertEqual(p2.returncode,0,p2.stdout+p2.stderr)
        self.assertIn("V10_ROUTE_ROLLBACK=PASS",p2.stdout)
        self.assertEqual((self.state/"V10_CONTROLLER_STATE.json").read_bytes(),old)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assert_not_changed()

    def test_state_recorded_pid_currently_alive_is_never_archived(self):
        old=self.write_dormant_state(controller_pid=os.getpid())
        p=self.run_switch(archive_stale=True)
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=STATE_TRACKED_PID_STILL_EXISTS",p.stdout)
        self.assertEqual((self.state/"V10_CONTROLLER_STATE.json").read_bytes(),old)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assertFalse(list(self.state.glob("V10_release_*")))
        self.assert_not_changed()

    def test_missing_brain_identity_in_state_is_not_guessed(self):
        self.write_dormant_state()
        state_file=self.state/"V10_CONTROLLER_STATE.json"
        doc=json.loads(state_file.read_text())
        doc.pop("brain_observer_pid")
        state_file.write_text(json.dumps(doc),encoding="utf-8")
        p=self.run_switch(archive_stale=True)
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=STATE_OWNERSHIP_INCOMPLETE",p.stdout)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assert_not_changed()

    def test_wrong_sha_fails_without_touching_original(self):
        p=self.run_switch(pin="0"*40)
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=COMMIT_NOT_PRESENT",p.stdout)
        self.assertEqual(self.link.read_bytes(),self.before)
        self.assert_not_changed()

    def test_changed_legacy_target_refuses_before_clone(self):
        self.make_link(self.link)
        q=lambda x:"'"+str(x).replace("'","''")+"'"
        ps=(f"$s=New-Object -ComObject WScript.Shell; "
            f"$l=$s.CreateShortcut({q(self.link)}); "
            "$l.Arguments='/k echo unreviewed'; $l.Save()")
        encoded=base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
                        "-EncodedCommand",encoded],
                       capture_output=True,text=True,timeout=20,check=True)
        changed=self.link.read_bytes()
        p=self.run_switch()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=LEGACY_SHORTCUT_CHANGED",p.stdout)
        self.assertEqual(self.link.read_bytes(),changed)
        self.assertFalse(list(self.state.glob("V10_release_*")))
        self.assert_not_changed()

    def test_missing_old_shortcut_refuses_without_clone(self):
        self.link.unlink()
        p=self.run_switch()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("V10_ROUTE_BLOCK_REASON=START_SHORTCUT_NOT_UNIQUE",p.stdout)
        self.assertFalse(list(self.state.glob("V10_release_*")))
        self.assert_not_changed()

if __name__=="__main__":
    unittest.main()
