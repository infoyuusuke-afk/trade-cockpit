"""P0-24C privacy-only diagnosis for inherited Controller state on disposable Windows."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "downloads" / "DIAGNOSE_V10_CONTROLLER_STATE_READONLY.ps1"

@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "disposable Windows runner only",
)
class ControllerStateDiagnose(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(prefix="state-diag-", dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.file = self.root / "V10_CONTROLLER_STATE.json"
        self.state = {
            "controller_pid":2147000000,
            "session_id":1,
            "started_at":"2026-10-15T09:00:00+09:00",
            "repo_root":"C:\\PRIVATE\\SENSITIVE_USER",
            "runtime_dir":"C:\\PRIVATE\\SENSITIVE_STATE",
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

    def save(self):
        self.file.write_text(json.dumps(self.state),encoding="utf-8")

    def invoke_diagnosis(self):
        return subprocess.run(
            ["powershell.exe","-NoProfile","-NonInteractive",
             "-ExecutionPolicy","Bypass","-File",str(SCRIPT),
             "-Root",str(self.root)],
            capture_output=True,text=True,errors="replace",timeout=35
        )

    def check_privacy(self, p):
        self.assertNotIn(str(self.root),p.stdout)
        self.assertNotIn("C:\\PRIVATE",p.stdout)
        self.assertNotIn("2147000000",p.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false",p.stdout)
        self.assertIn("REAL_SUBMIT_ALLOWED=false",p.stdout)

    def test_absent_state_is_readonly_no_recovery(self):
        p=self.invoke_diagnosis()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("STATE_SCHEMA=ABSENT",p.stdout)
        self.assertIn("DIAG_RESULT=READ_ONLY",p.stdout)
        self.assertFalse(self.file.exists())
        self.check_privacy(p)

    def test_complete_state_preserved_unchanged(self):
        self.save()
        before=self.file.read_bytes()
        p=self.invoke_diagnosis()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("STATE_SCHEMA=COMPLETE",p.stdout)
        self.assertIn("MISSING_REQUIRED_COUNT=0",p.stdout)
        self.assertIn("INVALID_REQUIRED_COUNT=0",p.stdout)
        self.assertIn("RECORDED_PID_ALIVE_COUNT=0",p.stdout)
        self.assertIn("STATE_FILE_MODIFIED=false",p.stdout)
        self.assertEqual(self.file.read_bytes(),before)
        self.check_privacy(p)

    def test_missing_brain_state_field_reports_only_field_name(self):
        self.state.pop("brain_observer_pid")
        self.save()
        before=self.file.read_bytes()
        p=self.invoke_diagnosis()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("STATE_SCHEMA=INCOMPLETE",p.stdout)
        self.assertIn("MISSING_REQUIRED_COUNT=1",p.stdout)
        self.assertIn("MISSING_FIELD=brain_observer_pid",p.stdout)
        self.assertEqual(self.file.read_bytes(),before)
        self.check_privacy(p)

    def test_incomplete_early_start_records_invalid_root_without_value(self):
        self.state["runtime_dir"]=""
        self.state["repo_root"]=""
        self.save()
        p=self.invoke_diagnosis()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("INVALID_REQUIRED_COUNT=2",p.stdout)
        self.assertIn("INVALID_FIELD=repo_root",p.stdout)
        self.assertIn("INVALID_FIELD=runtime_dir",p.stdout)
        self.check_privacy(p)

    def test_occupied_pid_detected_without_disclosing_pid(self):
        self.state["controller_pid"]=os.getpid()
        self.save()
        p=self.invoke_diagnosis()
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("RECORDED_PID_ALIVE_COUNT=1",p.stdout)
        self.check_privacy(p)

    def test_malformed_state_fails_closed_and_preserves_bytes(self):
        self.file.write_bytes(b"{broken file --- secret")
        before=self.file.read_bytes()
        p=self.invoke_diagnosis()
        self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertIn("DIAG_RESULT=BLOCKED",p.stdout)
        self.assertEqual(self.file.read_bytes(),before)
        self.check_privacy(p)

if __name__=="__main__":
    unittest.main()
