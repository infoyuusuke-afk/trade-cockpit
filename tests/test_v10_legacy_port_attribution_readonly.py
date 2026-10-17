"""P0-28 read-only per-port owner attribution. Synthetic Windows hosts only."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v10_legacy_safe_stop as tsl

REPO = Path(__file__).resolve().parents[1]
DIAG = REPO / "downloads" / "DIAGNOSE_V10_LEGACY_PORT_OWNER_READONLY_V1.ps1"
WIN_CI = (os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
          and os.environ.get("RUNNER_OS") == "Windows")


class StaticSafety(unittest.TestCase):
    def test_diagnostic_is_readonly_and_always_refuses_stop(self):
        text = DIAG.read_text(encoding="utf-8")
        executable = text.split("#>", 1)[1]
        for forbidden in ("Stop-Process", ".Kill(", "Start-Process", "Stop-Service",
                          "Move-Item", "Rename-Item", "Remove-Item", "-ComObject",
                          "Set-Content", "Out-File", "taskkill", "RssOrder"):
            self.assertNotIn(forbidden, executable, forbidden)
        for expected in ("STOP_ALLOWED=false", "CUTOVER_ELIGIBLE=false",
                         "REAL_SUBMIT_ALLOWED=false", "PROCESSES_STOPPED=0",
                         "EXCEL_ACTION=NONE", "SESSION_CHANGED_DURING_AUDIT",
                         "START_JOB_ARGV_MISMATCH", "PARENT_NOT_COLLECTOR_OR_WATCHER"):
            self.assertIn(expected, executable)

    def test_output_does_not_emit_process_identity(self):
        code = DIAG.read_text(encoding="utf-8")
        self.assertNotIn("Write-Host", code)
        for label in ("CommandLine", "ExecutablePath", "ParentProcessId",
                      "CreationDate", "FullName"):
            self.assertNotIn('Write-Output ($key+"_"+'+label, code)


@unittest.skipUnless(WIN_CI, "Windows GitHub Actions only")
class WindowsAttribution(tsl.LegacySessionSafeStop):
    def execute(self):
        out = subprocess.run([
            tsl.PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(DIAG), "-Root", str(self.root)
        ], capture_output=True, text=True, errors="replace", timeout=90)
        print("--- P0-28", self._testMethodName, out.returncode, out.stdout,
              out.stderr[-500:])
        self.assertNotIn(str(self.root), out.stdout)
        self.assertNotIn(str(self.repo), out.stdout)
        self.assertNotIn(str(self.runtime), out.stdout)
        for l in out.stdout.splitlines():
            self.assertRegex(l, r"^[A-Z0-9_]+=[A-Za-z0-9_]+$")
        for tag in ("PROCESSES_STOPPED=0", "EXCEL_ACTION=NONE",
                    "STOP_ALLOWED=false", "CUTOVER_ELIGIBLE=false",
                    "REAL_SUBMIT_ALLOWED=false", "STATE_MODIFIED=false"):
            self.assertIn(tag, out.stdout)
        self.assertTrue(tsl.alive(self.excel_managed))
        self.assertTrue(tsl.alive(self.excel_business))
        self.assertTrue(tsl.alive(self.foreign_py))
        return out

    def test_01_admitted_job_and_tracked_hosts_classified_without_stop(self):
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.execute()
        self.assertEqual(r.returncode, 0)
        self.assertIn("P0_28_RESULT=CLASSIFIED", r.stdout)
        for p in (28580, 28582):
            self.assertIn(f"PORT_{p}=JOB_BRIDGE_VERIFIED", r.stdout)
        for p in (28581, 28583):
            self.assertIn(f"PORT_{p}=TRACKED_RECORDED", r.stdout)
        self.assertIn("PORT_28584=NOT_LISTENING", r.stdout)
        self.assertEqual(before, self.state_path.read_bytes())
        self.assert_nothing_stopped()

    def test_02_unapproved_non_job_bridge_refused_without_stop(self):
        self.start_session(bridge="raw")
        before = self.state_path.read_bytes()
        r = self.execute()
        self.assertEqual(r.returncode, 2)
        self.assertIn("P0_28_RESULT=ATTRIBUTION_UNVERIFIED", r.stdout)
        self.assertIn("PORT_28580=UNVERIFIED", r.stdout)
        self.assertIn("PORT_28580_REASON=START_JOB_ARGV_MISMATCH", r.stdout)
        self.assertEqual(before, self.state_path.read_bytes())
        self.assert_nothing_stopped()

    def test_03_untracked_listener_refused_without_stop(self):
        self.start_session()
        late = self.spawn([sys.executable, "-c",
                           "import socket,time\n"
                           "s=socket.socket();s.bind(('127.0.0.1',28584));"
                           "s.listen(1);time.sleep(300)", self.mark])
        limit = time.monotonic() + 30
        while time.monotonic() < limit and not tsl.port_listening(28584):
            time.sleep(0.25)
        r = self.execute()
        self.assertEqual(r.returncode, 2)
        self.assertIn("PORT_28584=UNVERIFIED", r.stdout)
        self.assertIn("PORT_28584_REASON=PARENT_NOT_COLLECTOR_OR_WATCHER", r.stdout)
        self.assertTrue(tsl.alive(late))
        self.assert_nothing_stopped()

    def test_04_corrupt_or_missing_state_is_blocked(self):
        self.start_session()
        original = self.state_path.read_bytes()
        self.state_path.write_text("{broken", encoding="utf-8")
        try:
            r = self.execute()
            self.assertEqual(r.returncode, 2)
            self.assertIn("P0_28_RESULT=BLOCKED", r.stdout)
        finally:
            self.state_path.write_bytes(original)
        self.assert_nothing_stopped()

    def test_05_untracked_state_owner_never_grants_stop(self):
        self.start_session()
        original = self.state_path.read_bytes()
        fake = dict(self.state, collector_pid=self.foreign_py.pid)
        self.state_path.write_text(json.dumps(fake), encoding="utf-8")
        try:
            r = self.execute()
            self.assertEqual(r.returncode, 2)
            self.assertIn("P0_28_RESULT=ATTRIBUTION_UNVERIFIED", r.stdout)
            self.assertIn("PORT_28580=UNVERIFIED", r.stdout)
        finally:
            self.state_path.write_bytes(original)
        self.assert_nothing_stopped()


# Do not inherit destructive safe-stop tests in this diagnostic suite.
for _name in dir(tsl.LegacySessionSafeStop):
    if _name.startswith("test_"):
        setattr(WindowsAttribution, _name, None)

if __name__ == "__main__":
    unittest.main()
