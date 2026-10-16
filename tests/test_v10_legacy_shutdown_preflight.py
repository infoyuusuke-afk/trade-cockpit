"""P0-26 admission gate: disposable Windows processes, never a live shutdown."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
SCRIPT=REPO/"downloads"/"PREFLIGHT_V10_LEGACY_SHUTDOWN_V1.ps1"

@unittest.skipUnless(os.name=="nt" and os.environ.get("GITHUB_ACTIONS")=="true"
 and os.environ.get("RUNNER_OS")=="Windows","Windows Actions runner only")
class LegacyShutdownEligibility(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix="p0-26-legacy-",dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.repo=self.root/"synthetic-repo"
        self.runtime=self.root/"synthetic-runtime"
        (self.repo/"downloads").mkdir(parents=True)
        (self.repo/"scripts").mkdir(parents=True)
        self.runtime.mkdir()
        self.ctl=self.repo/"downloads"/"AI_COCKPIT_CONTROLLER_V10.ps1"
        self.ctl.write_text("Start-Sleep -Seconds 120\n",encoding="utf-8")
        self.controller=subprocess.Popen(
            ["powershell.exe","-NoProfile","-NonInteractive","-File",str(self.ctl)],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.cleanup_child,self.controller)
        time.sleep(0.5)
        self.assertIsNone(self.controller.poll())
        self.state_path=self.root/"V10_CONTROLLER_STATE.json"
        self.state={
            "controller_pid":self.controller.pid,"session_id":0,
            "started_at":(datetime.now(timezone.utc)-timedelta(seconds=8)).isoformat(),
            "repo_root":str(self.repo),"runtime_dir":str(self.runtime),
            "excel_pid":0,"watcher_pid":0,"heartbeat_pid":0,
            "collector_pid":0,"gateway_pid":0,"brain_gateway_pid":0,
            "voice_bridge_pid":0,"sbv2_pid":0,"shadow_supervisor_pid":0
        }
        self.save()

    def cleanup_child(self,p):
        if p.poll() is None: p.kill()
        p.wait(timeout=15)

    def save(self):
        self.state_path.write_text(json.dumps(self.state),encoding="utf-8")

    def invoke(self):
        p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive",
            "-ExecutionPolicy","Bypass","-File",str(SCRIPT),"-Root",str(self.root)],
            capture_output=True,text=True,errors="replace",timeout=40)
        self.assertIsNone(self.controller.poll(),"Preflight terminated Controller!")
        self.assertTrue(self.state_path.is_file())
        self.assertNotIn(str(self.root),p.stdout)
        self.assertNotIn(str(self.controller.pid),p.stdout)
        self.assertIn("STOP_ALLOWED=false",p.stdout)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",p.stdout)
        return p

    def test_eligible_legacy_controller_is_still_never_stopped(self):
        before=self.state_path.read_bytes()
        p=self.invoke()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("LEGACY_STATE_SCHEMA=COMPATIBLE",p.stdout)
        self.assertIn("TRACKED_LIVE_EXACT=1",p.stdout)
        self.assertIn("PREFLIGHT_RESULT=EVIDENCE_ONLY_PASS",p.stdout)
        self.assertEqual(before,self.state_path.read_bytes())

    def test_untracked_brain_candidate_blocks_readonly(self):
        observer=self.repo/"scripts"/"ai_brain_observer.py"
        observer.write_text("import time\ntime.sleep(120)\n",encoding="utf-8")
        child=subprocess.Popen([sys.executable,str(observer)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.cleanup_child,child)
        time.sleep(0.35)
        p=self.invoke()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("PREFLIGHT_BLOCK_REASON=UNTRACKED_BRAIN_CANDIDATE",p.stdout)
        self.assertIsNone(child.poll())

    def test_live_excel_process_is_explicit_veto(self):
        # Launch synthetic executable with normal script host; the PID field
        # is a trap. It must be vetoed *without* COM/Excel interaction.
        self.state["excel_pid"]=self.controller.pid
        self.save()
        p=self.invoke()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("PREFLIGHT_BLOCK_REASON=EXCEL_PROCESS_STILL_ALIVE",p.stdout)

    def test_controller_pid_reuse_or_foreign_name_blocks(self):
        self.state["controller_pid"]=os.getpid()
        self.save()
        p=self.invoke()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("PREFLIGHT_BLOCK_REASON=TRACKED_PROCESS_IDENTITY_NOT_PROVEN",p.stdout)

    def test_invalid_legacy_state_with_recorded_brain_rejected(self):
        self.state["brain_observer_pid"]=0
        self.save()
        p=self.invoke()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("PREFLIGHT_BLOCK_REASON=NOT_A_LEGACY_STATE",p.stdout)

    def test_missing_state_fields_fail_closed_without_mutation(self):
        del self.state["collector_pid"]
        self.save()
        original=self.state_path.read_bytes()
        p=self.invoke()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("PREFLIGHT_BLOCK_REASON=STATE_SCHEMA_INCOMPLETE",p.stdout)
        self.assertEqual(original,self.state_path.read_bytes())

if __name__=="__main__":unittest.main()
