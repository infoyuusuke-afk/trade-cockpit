"""Windows Actions-only integration exercise of the *real* V10 safe-stop entrypoint.

Processes and state are synthetic, unique to an isolated RUNNER_TEMP folder.
No MS2, Excel, broker API, market data, workstation or service is accessed.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STOP = REPO / "downloads" / "STOP_AI_COCKPIT_V10.ps1"


@unittest.skipUnless(
    os.name == "nt"
    and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "OS-process integration is only permitted inside Windows GitHub Actions",
)
class SafeStopWindowsIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="v10-brain-safe-stop-",
            dir=os.environ["RUNNER_TEMP"],
        )
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.children = []
        self.controller_script = self.root / "AI_COCKPIT_CONTROLLER_V10.ps1"
        self.controller_script.write_text("Start-Sleep -Seconds 120\n", encoding="utf-8")
        self.controller = self.spawn([
            "powershell.exe", "-NoProfile", "-NonInteractive",
            "-File", str(self.controller_script),
        ])
        # Python -c executes only time.sleep, not the repository observer.
        # Its remaining argv imitates *exactly* the BRAIN launch identity.
        self.brain = self.spawn([
            sys.executable, "-c", "import time; time.sleep(120)",
            str(REPO / "scripts" / "ai_brain_observer.py"),
            "--live", str(self.runtime / "live_ms2.json"),
            "--status", str(self.runtime / "ai_brain_observer_status_v1.json"),
        ])
        self.foreign = self.spawn([
            sys.executable, "-c", "import time; time.sleep(120)",
            "UNRELATED_PYTHON_NO_BRAIN_IDENTITY",
        ])
        self.assertEqual(len({os.getpid(), self.controller.pid,
                              self.brain.pid, self.foreign.pid}), 4)
        time.sleep(1)
        for proc in self.children:
            self.assertIsNone(proc.poll(), "synthetic worker failed to start")
        self.state_path = self.root / "V10_CONTROLLER_STATE.json"
        self.state = {
            "controller_pid": self.controller.pid,
            "brain_observer_pid": self.brain.pid,
            "repo_root": str(REPO),
            "runtime_dir": str(self.runtime),
            "session_id": "ci-synthetic-only",
            "started_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
            "excel_pid": 0,
            "collector_pid": 0,
            "watcher_pid": 0,
        }

    def spawn(self, argv):
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.children.append(proc)
        self.addCleanup(self.cleanup_child, proc)
        return proc

    @staticmethod
    def cleanup_child(proc):
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    def write_state(self, state=None):
        self.state_path.write_text(
            json.dumps(self.state if state is None else state),
            encoding="utf-8",
        )

    def run_stop(self):
        self.assertTrue(STOP.is_file())
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-File", str(STOP), "-Root", str(self.root)],
            capture_output=True, text=True, errors="replace", timeout=45,
        )
        self.assertIsNone(self.foreign.poll(),
                          "Safe Stop touched unrelated Python process")
        return result

    def test_valid_owned_brain_is_really_stopped(self):
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(self.controller.poll(), "Controller is still alive")
        self.assertIsNotNone(self.brain.poll(), "BRAIN is still alive")
        self.assertFalse(self.state_path.exists(), "success retained state")
        self.assertIn("Stopped verified BRAIN observer", result.stdout)

    def test_wrong_pid_identity_is_refused_without_touching_worker(self):
        self.state["brain_observer_pid"] = self.foreign.pid
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(self.state_path.exists(), "evidence deleted on refusal")
        self.assertIsNone(self.brain.poll(), "correct BRAIN killed despite mismatch")
        self.assertIsNone(self.foreign.poll(), "unrelated Python killed")
        self.assertIsNone(self.controller.poll(), "foreign BRAIN PID must not stop Controller")
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_IDENTITY_UNVERIFIED", result.stdout)

    def test_zero_brain_pid_blocks_before_controller_stop(self):
        self.state["brain_observer_pid"] = 0
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(self.state_path.exists())
        self.assertIsNone(self.brain.poll(), "missing PID allowed broad scan")
        self.assertIsNone(self.controller.poll(), "partial stop on zero BRAIN PID")
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_PID_UNRECORDED", result.stdout)

    def test_owner_legacy_state_missing_brain_property_never_half_stops(self):
        self.state.pop("brain_observer_pid")
        self.write_state()
        before = self.state_path.read_bytes()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_PID_UNRECORDED", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertIsNone(self.controller.poll(), "Controller killed before legacy safety check")
        self.assertIsNone(self.brain.poll(), "BRAIN killed without recorded ownership")
        self.assertIsNone(self.foreign.poll(), "unrelated Python killed")

    def test_invalid_brain_pid_never_stops_controller(self):
        self.state["brain_observer_pid"] = "not-a-pid"
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_BRAIN_PID_UNRECORDED", result.stdout)
        self.assertIsNone(self.controller.poll())
        self.assertIsNone(self.brain.poll())

    def test_foreign_worker_refuses_before_controller_or_brain_stop(self):
        # Ownership mismatch for a tracked worker must not produce half-stop.
        self.state["shadow_supervisor_pid"] = self.foreign.pid
        self.write_state()
        old = self.state_path.read_bytes()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_FOREIGN_WORKER_PID", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), old)
        self.assertIsNone(self.controller.poll(), "Controller stopped before foreign worker check")
        self.assertIsNone(self.brain.poll(), "BRAIN stopped before foreign worker check")

    def test_unrelated_listener_prevents_false_stop_success(self):
        # Binding a V10 port is NOT permission to kill its owner. The state
        # must be retained if a listener survives the real process teardown.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            try:
                listener.bind(("127.0.0.1", 28584))
            except OSError:
                self.skipTest("V10 test port already occupied on Windows runner")
            listener.listen(1)
            self.write_state()
            result = self.run_stop()
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("SAFE_STOP_VERIFY=LISTEN_PORTS_REMAIN", result.stdout)
            self.assertTrue(self.state_path.exists(), "state erased with live V10 listener")
            self.assertIsNotNone(self.controller.poll(), "Controller not stopped in synthetic test")
            self.assertIsNotNone(self.brain.poll(), "BRAIN not stopped in synthetic test")
        finally:
            listener.close()

    def test_corrupt_state_does_not_kill_any_worker(self):
        self.state_path.write_text("{malformed", encoding="utf-8")
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIsNone(self.controller.poll())
        self.assertIsNone(self.brain.poll())
        self.assertTrue(self.state_path.exists())

    def test_foreign_controller_pid_blocks_before_teardown(self):
        self.state["controller_pid"] = self.foreign.pid
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIsNone(self.controller.poll())
        self.assertIsNone(self.brain.poll())
        self.assertTrue(self.state_path.exists())

    def test_recorded_brain_already_exited_is_idempotent(self):
        self.brain.kill()
        self.brain.wait(timeout=10)
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(self.controller.poll())
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
