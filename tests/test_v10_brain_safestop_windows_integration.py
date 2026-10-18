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
        # A private sleep-only script uses the actual Controller argv layout.
        # Never execute the repository observer or use -c as a positive fixture.
        self.fixture_repo = self.root / "synthetic repo"
        (self.fixture_repo / "scripts").mkdir(parents=True)
        self.brain_script = self.fixture_repo / "scripts" / "ai_brain_observer.py"
        self.brain_script.write_text("import time; time.sleep(120)\n", encoding="utf-8")
        self.brain_argv = [
            sys.executable, "-u", str(self.brain_script),
            "--live", str(self.runtime / "live_ms2.json"),
            "--status", str(self.runtime / "ai_brain_observer_status_v1.json"),
            "--interval", "5",
        ]
        self.brain = self.spawn(self.brain_argv)
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
            "repo_root": str(self.fixture_repo),
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

    def assert_decoy_refused(self, argv):
        decoy = self.spawn(argv)
        time.sleep(0.3)
        self.assertIsNone(decoy.poll())
        self.state["brain_observer_pid"] = decoy.pid
        self.write_state()
        before = self.state_path.read_bytes()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCKED_BRAIN_IDENTITY_UNVERIFIED", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), before)
        for proc in (decoy, self.controller, self.brain, self.foreign):
            self.assertIsNone(proc.poll(), "identity rejection must precede any stop")

    def test_python_c_with_all_brain_paths_is_not_owned(self):
        self.assert_decoy_refused([
            sys.executable, "-c", "import time; time.sleep(120)",
            *self.brain_argv[2:],
        ])

    def test_script_path_suffix_is_not_owned(self):
        decoy_script = Path(str(self.brain_script) + ".foreign.py")
        decoy_script.write_text("import time; time.sleep(120)\n", encoding="utf-8")
        args = list(self.brain_argv)
        args[2] = str(decoy_script)
        self.assert_decoy_refused(args)

    def test_duplicate_status_override_is_not_owned(self):
        self.assert_decoy_refused(self.brain_argv + ["--status", str(self.root / "foreign.json")])

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

    def test_valid_recorded_shadow_worker_is_stopped(self):
        script = self.fixture_repo / "scripts" / "ai_shadow_supervisor.py"
        script.write_text("import time; time.sleep(120)\n", encoding="utf-8")
        shadow = self.spawn([sys.executable, "-u", str(script)])
        time.sleep(0.3)
        self.assertIsNone(shadow.poll())
        self.state["shadow_supervisor_pid"] = shadow.pid
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(shadow.poll(), "recorded SHADOW worker survived valid stop")
        self.assertIsNotNone(self.controller.poll(), "Controller survived valid stop")
        self.assertIsNotNone(self.brain.poll(), "BRAIN survived valid stop")
        self.assertFalse(self.state_path.exists(), "verified stop retained state")

    def test_inert_worker_script_name_argument_cannot_authorize_stop(self):
        # A Python -c program mentioning the owned basename as inert argv
        # must not be mistaken for the managed SHADOW script.
        decoy = self.spawn([
            sys.executable, "-c", "import time; time.sleep(120)",
            "ai_shadow_supervisor.py",
        ])
        time.sleep(0.3)
        self.assertIsNone(decoy.poll())
        self.state["shadow_supervisor_pid"] = decoy.pid
        self.write_state()
        before = self.state_path.read_bytes()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCKED_FOREIGN_WORKER_PID", result.stdout)
        self.assertEqual(self.state_path.read_bytes(), before)
        for proc in (decoy, self.controller, self.brain, self.foreign):
            self.assertIsNone(proc.poll(), "inert script basename must not grant STOP ownership")

    def test_controller_name_in_powershell_command_cannot_authorize_stop(self):
        decoy = self.spawn([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "Start-Sleep -Seconds 120 # RUN_AI_COCKPIT_V10.ps1",
        ])
        time.sleep(0.3)
        self.assertIsNone(decoy.poll())
        self.state["controller_pid"] = decoy.pid
        self.write_state()
        before = self.state_path.read_bytes()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)
        for proc in (decoy, self.controller, self.brain, self.foreign):
            self.assertIsNone(proc.poll(), "PowerShell -Command mention must not grant ownership")

    def test_foreign_controller_pid_blocks_before_teardown(self):
        self.state["controller_pid"] = self.foreign.pid
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIsNone(self.controller.poll())
        self.assertIsNone(self.brain.poll())
        self.assertTrue(self.state_path.exists())

    def assert_nothing_stopped(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCKED_BRAIN_IDENTITY_UNVERIFIED", result.stdout)
        self.assertTrue(self.state_path.exists(), "evidence deleted on refusal")
        for proc in (self.controller, self.brain, self.foreign):
            self.assertIsNone(proc.poll(), "refusal must precede any stop")

    def test_brain_created_before_session_is_not_owned(self):
        # Exact argv, but the process predates the recorded session: PID reuse.
        self.state["started_at"] = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.write_state()
        self.assert_nothing_stopped(self.run_stop())

    def test_unparseable_session_time_fails_closed(self):
        self.state["started_at"] = "not-a-timestamp"
        self.write_state()
        self.assert_nothing_stopped(self.run_stop())

    def test_relative_repo_root_fails_closed(self):
        self.state["repo_root"] = "synthetic repo"
        self.write_state()
        self.assert_nothing_stopped(self.run_stop())

    def test_unrecorded_excel_collector_watcher_survive_valid_stop(self):
        # Synthetic look-alikes only: a renamed ping.exe and sleep-only scripts.
        fake_excel = self.root / "EXCEL.EXE"
        shutil.copyfile(Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE", fake_excel)
        bystanders = [self.spawn([str(fake_excel), "-n", "120", "127.0.0.1"])]
        for name in ("MS2_RSS_100_Collector.ps1", "Kioxia_RSS_Live_Watcher.ps1"):
            script = self.root / name
            script.write_text("Start-Sleep -Seconds 120\n", encoding="utf-8")
            bystanders.append(self.spawn([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script),
            ]))
        time.sleep(1)
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(self.brain.poll(), "BRAIN is still alive")
        for proc in bystanders:
            self.assertIsNone(proc.poll(), "unrecorded bystander process was stopped")

    @staticmethod
    def child_pids(parent_pid):
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter 'ParentProcessId = %d' | "
             "ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.Name }" % parent_pid],
            capture_output=True, text=True, timeout=30,
        ).stdout
        rows = [line.split(None, 1) for line in out.splitlines() if line.strip()]
        print("LAUNCHER_CHILDREN=" + ";".join(" ".join(r) for r in rows))
        # conhost.exe also hangs off console launchers; only the interpreter matters.
        return [int(r[0]) for r in rows
                if len(r) == 2 and r[1].lower() in ("python.exe", "pythonw.exe")]

    @staticmethod
    def pid_alive(pid):
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "[bool](Get-Process -Id %d -ErrorAction SilentlyContinue)" % pid],
            capture_output=True, text=True, timeout=30,
        ).stdout
        return out.strip() == "True"

    def kill_pid(self, pid):
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)

    def assert_launcher_stop_leaves_no_brain(self, launcher_argv):
        launcher = self.spawn(launcher_argv + self.brain_argv[1:])
        child = []
        for _ in range(40):
            time.sleep(0.25)
            child = self.child_pids(launcher.pid)
            if child:
                break
        self.assertEqual(len(child), 1, "launcher did not spawn exactly one python.exe child")
        self.addCleanup(self.kill_pid, child[0])
        self.state["brain_observer_pid"] = launcher.pid
        self.write_state()
        result = self.run_stop()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(launcher.poll(), "tracked launcher is still alive")
        for _ in range(20):
            if not self.pid_alive(child[0]):
                break
            time.sleep(0.25)
        self.assertFalse(self.pid_alive(child[0]), "BRAIN interpreter child survived Safe Stop")
        self.assertIsNone(self.brain.poll(), "unrecorded BRAIN-like process was stopped")

    def test_venv_redirector_brain_child_does_not_survive(self):
        venv = self.root / "venv"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                       check=True, timeout=120)
        self.assert_launcher_stop_leaves_no_brain([str(venv / "Scripts" / "python.exe")])

    def test_py_launcher_brain_child_does_not_survive(self):
        py = shutil.which("py.exe")
        if py is None:
            self.skipTest("PY_LAUNCHER_NOT_INSTALLED_ON_RUNNER")
        self.assert_launcher_stop_leaves_no_brain([py, "-3"])

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
