"""Read-only STOP identity regression contract; no process termination."""
import re
import unittest
from pathlib import Path

STOP = (Path(__file__).resolve().parents[1] / "downloads" / "STOP_AI_COCKPIT_V10.ps1")

class StopWorkerIdentityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STOP.read_text(encoding="utf-8-sig")
        cls.block = cls.source.split("function Test-OwnedPidIdentity(", 1)[1].split(
            "function Test-BrainCommandLine(", 1)[0]

    def test_controller_and_workers_share_identity_checks(self):
        s = self.block
        for required in ("$wmi.CreationDate", "$proc.StartTime", "$proc.SessionId",
                         "$selfSession", "$proc.Handle", "$wmi.ProcessId"):
            with self.subTest(required=required):
                self.assertIn(required, s)
        self.assertNotIn('if ($Field -eq "controller_pid") {\n            return', s)

    def test_script_name_token_boundary_and_known_interpreters(self):
        s = self.block
        self.assertIn("[regex]::Escape($name)", s)
        self.assertIn("(?<![A-Za-z0-9_.-])", s)
        self.assertIn("pythonw", s)
        self.assertIn("RUN_AI_COCKPIT_V10.ps1", s)

    def test_refusal_precedes_controller_stop(self):
        src = self.source
        preflight = src.index("SAFE_STOP_PREFLIGHT=BLOCKED_FOREIGN_WORKER_PID")
        controller_stop = src.index("Stop-Process -Id $controllerPid")
        self.assertLess(preflight, controller_stop)

if __name__ == "__main__":
    unittest.main()
