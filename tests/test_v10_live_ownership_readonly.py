"""P0-25: real synthetic process enumeration; never stops a system process.

GitHub Windows Actions only, temporary paths and disposable Python child.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/"downloads"/"AUDIT_V10_LIVE_PROCESS_OWNERSHIP_READONLY.ps1"

@unittest.skipUnless(
    os.name=="nt" and os.environ.get("GITHUB_ACTIONS")=="true"
    and os.environ.get("RUNNER_OS")=="Windows",
    "Synthetic PID/port inventory restricted to GitHub Windows",
)
class LiveOwnershipReadOnly(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="p0-25-ownership-",dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/"V10_CONTROLLER_STATE.json"
        self.repo=self.root/"repo"
        self.script=self.repo/"scripts"/"ai_brain_observer.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("import time\ntime.sleep(120)\n",encoding="utf-8")
        self.runtime=self.root/"runtime"
        self.runtime.mkdir()
        self.child=subprocess.Popen(
            [sys.executable,str(self.script),
             "--live",str(self.runtime/"live_ms2.json"),
             "--status",str(self.runtime/"ai_brain_observer_status_v1.json")],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.addCleanup(self.stop_child)
        time.sleep(0.3)
        self.assertIsNone(self.child.poll())
        self.json={
            "controller_pid":os.getpid(),
            "repo_root":str(self.repo),
            "runtime_dir":str(self.runtime),
            "started_at":datetime.now(timezone.utc).isoformat(),
            "session_id":"ci-only",
            "excel_pid":0,
            "watcher_pid":0,
            "heartbeat_pid":0,
            "collector_pid":0,
            "gateway_pid":0,
            "brain_gateway_pid":0,
            "voice_bridge_pid":0,
            "sbv2_pid":0,
            "shadow_supervisor_pid":0,
        }
        self.save()

    def stop_child(self):
        if self.child.poll() is None:
            self.child.kill()
        self.child.wait(timeout=15)

    def save(self):
        self.state.write_text(json.dumps(self.json),encoding="utf-8")

    def run_audit(self):
        p=subprocess.run(
            ["powershell.exe","-NoProfile","-NonInteractive",
             "-ExecutionPolicy","Bypass","-File",str(AUDIT),
             "-Root",str(self.root)],
            capture_output=True,text=True,errors="replace",timeout=35,
        )
        self.assertIsNone(self.child.poll(),"read-only audit killed synthetic BRAIN")
        return p

    def assert_safe(self,p):
        self.assertIn("STOP_ALLOWED=false",p.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false",p.stdout)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",p.stdout)
        self.assertNotIn(str(self.root),p.stdout)
        self.assertNotIn(str(self.child.pid),p.stdout)
        self.assertNotIn(str(os.getpid()),p.stdout)
        self.assertNotIn("live_ms2.json",p.stdout)

    def test_legacy_missing_brain_pid_reports_live_untracked_candidate(self):
        original=self.state.read_bytes()
        p=self.run_audit()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("AUDIT_BRAIN_FIELD=LEGACY_MISSING",p.stdout)
        self.assertIn("AUDIT_BRAIN_EXACT_CANDIDATE_COUNT=1",p.stdout)
        self.assertIn("AUDIT_BRAIN_RECORDED_EXACT_COUNT=0",p.stdout)
        self.assertIn("AUDIT_RESULT=READ_ONLY_HOLD",p.stdout)
        self.assertEqual(self.state.read_bytes(),original)
        self.assert_safe(p)

    def test_tracked_brain_candidate_is_reported_without_killing(self):
        self.json["brain_observer_pid"]=self.child.pid
        self.save()
        original=self.state.read_bytes()
        p=self.run_audit()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("AUDIT_BRAIN_FIELD=PRESENT",p.stdout)
        self.assertIn("AUDIT_BRAIN_EXACT_CANDIDATE_COUNT=1",p.stdout)
        self.assertIn("AUDIT_BRAIN_RECORDED_EXACT_COUNT=1",p.stdout)
        self.assertEqual(self.state.read_bytes(),original)
        self.assert_safe(p)

    def test_brain_pid_points_to_foreign_process_is_unverified(self):
        self.json["brain_observer_pid"]=os.getpid()
        self.save()
        p=self.run_audit()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("AUDIT_BRAIN_RECORDED_EXACT_COUNT=0",p.stdout)
        self.assertIn("AUDIT_BRAIN_EXACT_CANDIDATE_COUNT=1",p.stdout)
        self.assert_safe(p)

    def test_corrupt_json_fails_closed_without_altering_source(self):
        self.state.write_bytes(b"{synthetic-corrupt-state")
        old=self.state.read_bytes()
        p=self.run_audit()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("AUDIT_RESULT=BLOCKED",p.stdout)
        self.assertEqual(self.state.read_bytes(),old)
        self.assert_safe(p)

    def test_empty_repo_root_fails_closed(self):
        self.json["repo_root"]=""
        self.save()
        p=self.run_audit()
        self.assertEqual(p.returncode,2,p.stdout+p.stderr)
        self.assertIn("AUDIT_BLOCK_REASON=STATE_ROOT_FIELDS_EMPTY",p.stdout)
        self.assert_safe(p)

if __name__=="__main__":
    unittest.main()
