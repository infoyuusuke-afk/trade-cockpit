"""P0-26B: destructive acceptance of STOP_V10_LEGACY_SESSION_V1.ps1.

Windows GitHub Actions only. Every process is a disposable synthetic host
created here under RUNNER_TEMP: a looping Controller that launches and may
restart its workers, worker hosts with the exact legacy script identities,
JSON-bridge children listening on V10 ports, stand-ins named EXCEL.exe for
the managed and the business workbook, and unrelated Python. No MS2, Excel,
broker, market data or OWNER machine is involved.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STOP = REPO / "downloads" / "STOP_V10_LEGACY_SESSION_V1.ps1"
PS = "powershell.exe"

CONTROLLER = r'''param([string]$Spec)
$ErrorActionPreference = "Stop"
$cfg = [IO.File]::ReadAllText($Spec) | ConvertFrom-Json
$procs = @{}
$state = [ordered]@{ controller_pid = $PID; session_id = 0
  started_at = (Get-Date).ToString("o"); repo_root = $cfg.repo_root; runtime_dir = $cfg.runtime_dir
  excel_pid = [int]$cfg.excel_pid; watcher_pid = 0; heartbeat_pid = 0; collector_pid = 0
  gateway_pid = 0; brain_gateway_pid = 0; voice_bridge_pid = 0; sbv2_pid = 0; shadow_supervisor_pid = 0 }
function Save { $t = $cfg.state_path + ".tmp"
  [IO.File]::WriteAllText($t, (ConvertTo-Json $state), (New-Object Text.UTF8Encoding($false)))
  Move-Item -LiteralPath $t -Destination $cfg.state_path -Force }
function Launch($w) { Start-Process -FilePath $w.exe -ArgumentList @($w.args) -PassThru -WindowStyle Hidden }
foreach ($w in @($cfg.workers)) { $p = Launch $w; $procs[$w.role] = $p; $state[$w.role] = $p.Id }
if ($null -ne $cfg.brain) { [void](Launch $cfg.brain) }
Save
[IO.File]::WriteAllText($cfg.ready_path, "READY")
while ($true) {
  Start-Sleep -Milliseconds 150
  if (-not $cfg.restart) { continue }
  foreach ($w in @($cfg.workers)) {
    if ($procs[$w.role].HasExited) {
      $p = Launch $w; $procs[$w.role] = $p; $state[$w.role] = $p.Id; Save
      Add-Content -LiteralPath $cfg.restart_log -Value $w.role
    }
  }
}
'''

LISTEN_THEN_SLEEP = (
    "param([int]$Port,[string]$Mark)\n"
    "$l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)\n"
    "$l.Start()\nStart-Sleep -Seconds 300\n"
)

# A legacy worker that hands its port to a JSON-bridge child process.
BRIDGE_PARENT = (
    "param([int]$Port,[string]$Mark)\n"
    "$code = '$l=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,' + $Port + ');$l.Start();Start-Sleep 300 # ' + $Mark\n"
    "Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile','-Command',$code) -WindowStyle Hidden\n"
    "Start-Sleep -Seconds 300\n"
)

SLEEP_PS = "param([string]$Mark)\nStart-Sleep -Seconds 300\n"
SLEEP_PY = "import time\ntime.sleep(300)\n"

EXCEL_SOURCE = (
    "public static class P { public static void Main(string[] a) "
    "{ System.Threading.Thread.Sleep(300000); } }"
)

ALL_PORTS = (28580, 28581, 28582, 28583, 28584)


def port_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def alive(proc):
    return proc.poll() is None


def pid_alive(pid):
    out = subprocess.run([PS, "-NoProfile", "-Command",
                          f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'Y' }} else {{ 'N' }}"],
                         capture_output=True, text=True, timeout=30).stdout.strip()
    return out == "Y"


@unittest.skipUnless(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
                     and os.environ.get("RUNNER_OS") == "Windows", "Windows Actions runner only")
class LegacySessionSafeStop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bin = Path(tempfile.mkdtemp(prefix="p0-26b-bin-", dir=os.environ["RUNNER_TEMP"]))
        exe = cls.bin / "EXCEL.exe"
        subprocess.run([PS, "-NoProfile", "-Command",
                        f"Add-Type -OutputAssembly '{exe}' -OutputType ConsoleApplication -TypeDefinition '{EXCEL_SOURCE}'"],
                       check=True, timeout=120)
        cls.excel_exe = exe

    def setUp(self):
        for port in ALL_PORTS:
            if port_listening(port):
                self.skipTest("V10 port already occupied on runner")
        self.mark = "P026MARK" + uuid.uuid4().hex
        self.addCleanup(self.kill_marked)
        t = tempfile.TemporaryDirectory(prefix="p0-26b-", dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.repo = self.root / "repo"
        self.runtime = self.root / "runtime"
        self.sbv2 = self.root / "sbv2"
        for d in (self.repo / "downloads", self.repo / "scripts", self.runtime, self.sbv2):
            d.mkdir(parents=True)
        self.controller_script = self.repo / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"
        self.controller_script.write_text(CONTROLLER, encoding="ascii")
        files = {
            self.runtime / "Kioxia_RSS_Live_Watcher.ps1": BRIDGE_PARENT,
            self.runtime / "MS2_RSS_100_Collector.ps1": BRIDGE_PARENT,
            self.runtime / "Kioxia_Safety_Heartbeat.ps1": SLEEP_PS,
            self.repo / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1": LISTEN_THEN_SLEEP,
            self.repo / "downloads" / "AI_COCKPIT_VOICE_BRIDGE_V10.ps1": SLEEP_PS,
            self.repo / "scripts" / "ai_shadow_supervisor.py": SLEEP_PY,
            self.repo / "scripts" / "ai_brain_observer.py": SLEEP_PY,
            self.sbv2 / "server_fastapi.py": SLEEP_PY,
        }
        for path, body in files.items():
            path.write_text(body, encoding="ascii")
        self.state_path = self.root / "V10_CONTROLLER_STATE.json"
        self.ready = self.root / "ready.txt"
        self.restart_log = self.root / "restarts.txt"
        self.excel_managed = self.spawn([str(self.excel_exe), self.mark, "managed"])
        self.excel_business = self.spawn([str(self.excel_exe), self.mark, "business"])
        self.foreign_py = self.spawn([sys.executable, "-c", "import time; time.sleep(300)", self.mark])

    # -- helpers ---------------------------------------------------------
    def spawn(self, argv):
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(self.kill_proc, p)
        return p

    @staticmethod
    def kill_proc(p):
        if p.poll() is None:
            p.kill()
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass

    def kill_marked(self):
        subprocess.run([PS, "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { ([string]$_.CommandLine).Contains('"
                        + self.mark + "') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                        capture_output=True, timeout=60)
        deadline = time.time() + 15
        while time.time() < deadline and any(port_listening(p) for p in ALL_PORTS):
            time.sleep(0.2)

    def ps_worker(self, role, script, *extra):
        return {"role": role, "exe": PS,
                "args": ["-NoProfile", "-NonInteractive", "-File", str(script), *extra, "-Mark", self.mark]}

    def py_worker(self, role, script):
        return {"role": role, "exe": sys.executable, "args": [str(script), self.mark]}

    def start_session(self, restart=False, owned_brain=False):
        dl = self.repo / "downloads"
        workers = [
            self.ps_worker("watcher_pid", self.runtime / "Kioxia_RSS_Live_Watcher.ps1", "-Port", "28582"),
            self.ps_worker("heartbeat_pid", self.runtime / "Kioxia_Safety_Heartbeat.ps1"),
            self.ps_worker("collector_pid", self.runtime / "MS2_RSS_100_Collector.ps1", "-Port", "28580"),
            self.ps_worker("gateway_pid", dl / "AI_COCKPIT_GATEWAY_V10.ps1", "-Port", "28581"),
            self.ps_worker("brain_gateway_pid", dl / "AI_COCKPIT_GATEWAY_V10.ps1", "-Port", "28583"),
            self.ps_worker("voice_bridge_pid", dl / "AI_COCKPIT_VOICE_BRIDGE_V10.ps1"),
            self.py_worker("sbv2_pid", self.sbv2 / "server_fastapi.py"),
            self.py_worker("shadow_supervisor_pid", self.repo / "scripts" / "ai_shadow_supervisor.py"),
        ]
        brain = None
        if owned_brain:
            brain = {"role": "brain", "exe": sys.executable, "args": [
                str(self.repo / "scripts" / "ai_brain_observer.py"),
                "--live", str(self.runtime / "live_ms2.json"),
                "--status", str(self.runtime / "ai_brain_observer_status_v1.json"), self.mark]}
        spec = {"repo_root": str(self.repo), "runtime_dir": str(self.runtime),
                "excel_pid": self.excel_managed.pid, "workers": workers, "brain": brain,
                "restart": restart, "state_path": str(self.state_path),
                "ready_path": str(self.ready), "restart_log": str(self.restart_log)}
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        self.controller = self.spawn([PS, "-NoProfile", "-NonInteractive", "-File",
                                      str(self.controller_script), "-Spec", str(spec_path)])
        deadline = time.time() + 60
        while time.time() < deadline and not self.ready.exists():
            time.sleep(0.2)
        self.assertTrue(self.ready.exists(), "synthetic Controller did not start")
        deadline = time.time() + 60
        while time.time() < deadline and not all(port_listening(p) for p in (28580, 28581, 28582, 28583)):
            time.sleep(0.3)
        self.assertTrue(all(port_listening(p) for p in (28580, 28581, 28582, 28583)),
                        "synthetic listeners did not start")
        time.sleep(1)
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertNotIn("brain_observer_pid", self.state)

    def run_stop(self, *extra):
        r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", str(STOP), "-Root", str(self.root), *extra],
                           capture_output=True, text=True, errors="replace", timeout=240)
        out = r.stdout
        print(f"--- {self._testMethodName} exit={r.returncode}\n{out}{r.stderr[-2000:]}")
        self.assertIn("REAL_SUBMIT_ALLOWED=false", out)
        self.assertIn("EXCEL_ACTION=NONE", out)
        self.assertNotIn(str(self.root), out)
        self.assertTrue(alive(self.foreign_py), "unrelated Python was stopped")
        self.assertTrue(alive(self.excel_managed), "managed Excel stand-in was touched")
        self.assertTrue(alive(self.excel_business), "business Excel stand-in was touched")
        return r

    def worker_pids(self):
        return [int(self.state[k]) for k in self.state if k.endswith("_pid") and k not in ("controller_pid", "excel_pid")]

    def evidence_dirs(self):
        ev = self.root / "V10_LEGACY_STOP_EVIDENCE"
        return sorted(ev.iterdir()) if ev.exists() else []

    def assert_nothing_stopped(self):
        self.assertTrue(alive(self.controller), "Controller stopped on a refusal")
        for pid in self.worker_pids():
            self.assertTrue(pid_alive(pid), "a worker was stopped on a refusal")
        self.assertTrue(self.state_path.exists())

    # -- 1, 5, 6, 7, 8: legacy state without BRAIN, full verified stop ----
    def test_01_legacy_state_without_brain_stops_everything_verified(self):
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 0)
        self.assertIn("LEGACY_STOP_RESULT=STOPPED_VERIFIED", r.stdout)
        self.assertIn("BRAIN_STATUS=ABSENT_VERIFIED", r.stdout)
        self.assertIn("MANAGED_PIDS_ALIVE=0", r.stdout)
        self.assertIn("V10_LISTEN_PORTS=0", r.stdout)
        self.assertIn("EXCEL_SET_UNCHANGED=true", r.stdout)
        self.assertIn("ADMITTED_PROCESSES=11", r.stdout)  # Controller + 8 workers + 2 bridge children
        self.assertFalse(alive(self.controller))
        for pid in self.worker_pids():
            self.assertFalse(pid_alive(pid))
        self.assertFalse(any(port_listening(p) for p in ALL_PORTS))
        self.assertFalse(self.state_path.exists())
        ev = self.evidence_dirs()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0] / "V10_CONTROLLER_STATE.legacy.json").read_bytes(), before)
        self.assertEqual((ev[0] / "V10_CONTROLLER_STATE.before.json").read_bytes(), before)
        result = json.loads((ev[0] / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["result"], "STOPPED_VERIFIED")
        roles = [k["role"] for k in result["kills"]]
        self.assertEqual(roles[0], "controller_pid")
        self.assertEqual(roles.count("bridge_child"), 2)
        self.assertNotIn(self.excel_managed.pid, [k["pid"] for k in result["kills"]])
        self.assertNotIn(self.excel_business.pid, [k["pid"] for k in result["kills"]])
        # 12. A rerun after success reports, never re-stops.
        again = self.run_stop("-Execute")
        self.assertEqual(again.returncode, 0)
        self.assertIn("LEGACY_STOP_RESULT=ALREADY_STOPPED", again.stdout)

    def test_02_dry_run_pins_but_stops_nothing(self):
        self.start_session()
        r = self.run_stop()
        self.assertEqual(r.returncode, 0)
        self.assertIn("LEGACY_STOP_RESULT=DRY_RUN_READY", r.stdout)
        self.assertIn("ADMITTED_PROCESSES=11", r.stdout)
        self.assert_nothing_stopped()
        self.assertEqual(self.evidence_dirs(), [])

    # -- 2. BRAIN present ------------------------------------------------
    def test_03_controller_owned_brain_is_admitted_and_stopped(self):
        self.start_session(owned_brain=True)
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 0)
        self.assertIn("BRAIN_STATUS=OWNED_CHILD_ADMITTED", r.stdout)
        self.assertIn("BRAIN_HOSTS_LEFT=0", r.stdout)
        self.assertIn("LEGACY_STOP_RESULT=STOPPED_VERIFIED", r.stdout)

    def test_04_orphan_brain_not_owned_by_controller_blocks_before_any_stop(self):
        self.start_session()
        orphan = self.spawn([sys.executable, str(self.repo / "scripts" / "ai_brain_observer.py"),
                             "--live", str(self.runtime / "live_ms2.json"), self.mark])
        time.sleep(0.5)
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 2)
        self.assertIn("LEGACY_STOP_REASON=UNTRACKED_BRAIN_CANDIDATE", r.stdout)
        self.assertTrue(alive(orphan))
        self.assert_nothing_stopped()

    # -- 3. PID reuse / ownership mismatch --------------------------------
    def test_05_foreign_pid_in_state_blocks_before_any_stop(self):
        self.start_session()
        self.state["watcher_pid"] = self.foreign_py.pid
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 2)
        self.assertIn("LEGACY_STOP_REASON=TRACKED_PROCESS_IDENTITY_NOT_PROVEN", r.stdout)
        self.assertTrue(alive(self.controller))
        self.assertTrue(self.state_path.exists())

    def test_06_excel_pid_equal_to_worker_blocks(self):
        self.start_session()
        self.state["excel_pid"] = self.state["heartbeat_pid"]
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 2)
        self.assertIn("LEGACY_STOP_REASON=EXCEL_PID_COLLIDES_WITH_WORKER", r.stdout)
        self.assert_nothing_stopped()

    # -- 4. Controller restart prevention ---------------------------------
    def test_07_restarting_controller_is_stopped_first_and_never_restarts(self):
        self.start_session(restart=True)
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 0)
        self.assertIn("LEGACY_STOP_RESULT=STOPPED_VERIFIED", r.stdout)
        time.sleep(2)
        self.assertFalse(self.restart_log.exists(), "Controller restarted a worker during Safe Stop")
        self.assertFalse(any(port_listening(p) for p in ALL_PORTS))

    # -- 9, 12. Worker stop failure keeps evidence; rerun completes -------
    def test_08_worker_stop_failure_is_partial_and_rerun_completes(self):
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.run_stop("-Execute", "-SimulateKillFailureRole", "gateway_pid")
        self.assertEqual(r.returncode, 3)
        self.assertIn("LEGACY_STOP_RESULT=PARTIAL_STOP", r.stdout)
        self.assertIn("LEGACY_STOP_REASON=MANAGED_PROCESS_NOT_STOPPED", r.stdout)
        self.assertIn("STATE_FILE=RETAINED", r.stdout)
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertFalse(alive(self.controller))
        self.assertTrue(pid_alive(int(self.state["gateway_pid"])))
        ev = self.evidence_dirs()
        self.assertEqual(len(ev), 1)
        result = json.loads((ev[0] / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["result"], "PARTIAL_STOP")
        self.assertIn("KILL_FAILED_SIMULATED", [k["outcome"] for k in result["kills"]])
        again = self.run_stop("-Execute")
        self.assertEqual(again.returncode, 0)
        self.assertIn("LEGACY_STOP_RESULT=STOPPED_VERIFIED", again.stdout)
        self.assertFalse(pid_alive(int(self.state["gateway_pid"])))
        self.assertFalse(any(port_listening(p) for p in ALL_PORTS))

    # -- 10. A listener that survives teardown fails the stop --------------
    def test_09_port_listening_after_teardown_is_partial(self):
        self.start_session()
        voice = int(self.state["voice_bridge_pid"])
        # Untracked process that binds a V10 port the moment Voice exits.
        late = self.spawn([sys.executable, "-c",
                           "import ctypes,socket,sys,time\n"
                           "k=ctypes.windll.kernel32\n"
                           "h=k.OpenProcess(0x00100000,False,int(sys.argv[1]))\n"
                           "k.WaitForSingleObject(h,0xFFFFFFFF)\n"
                           "s=socket.socket(); s.bind(('127.0.0.1',28584)); s.listen(1); time.sleep(300)\n",
                           str(voice), self.mark])
        time.sleep(0.5)
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 3)
        self.assertIn("LEGACY_STOP_REASON=V10_PORTS_STILL_LISTENING", r.stdout)
        self.assertIn("STATE_FILE=RETAINED", r.stdout)
        self.assertTrue(self.state_path.exists())
        self.assertTrue(alive(late), "an unadmitted listener owner was stopped")

    # -- 11. Corrupt state ------------------------------------------------
    def test_10_corrupt_state_is_refused_without_side_effects(self):
        self.start_session()
        self.state_path.write_text("{malformed", encoding="utf-8")
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 2)
        self.assertIn("LEGACY_STOP_RESULT=BLOCKED", r.stdout)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "{malformed")
        self.assertTrue(alive(self.controller))
        self.assertTrue(pid_alive(int(self.state["gateway_pid"])))

    def test_11_state_with_brain_pid_belongs_to_normal_stop(self):
        self.start_session()
        self.state["brain_observer_pid"] = 0
        self.state_path.write_text(json.dumps(self.state), encoding="utf-8")
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 2)
        self.assertIn("LEGACY_STOP_REASON=NOT_A_LEGACY_STATE", r.stdout)
        self.assertTrue(alive(self.controller))

    def test_12_missing_state_without_previous_success_is_blocked(self):
        r = self.run_stop("-Execute")
        self.assertEqual(r.returncode, 2)
        self.assertIn("LEGACY_STOP_REASON=STATE_MISSING", r.stdout)


if __name__ == "__main__":
    unittest.main()
