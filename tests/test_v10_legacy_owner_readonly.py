"""P0-27: non-stopping, SHA-pinned OWNER acceptance entry for the legacy V10 session.

Static checks run everywhere. The live checks run only on a Windows GitHub
Actions runner, against the same disposable synthetic legacy session as
test_v10_legacy_safe_stop.py (looping Controller, worker hosts, Start-Job
bridges, EXCEL.exe stand-ins, unrelated Python). No OWNER machine, MS2,
Excel or broker is involved, and nothing here stands in for the OWNER run.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_v10_legacy_safe_stop as tsl  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
VERIFY = REPO / "downloads" / "VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1"
PINNED = "4e4b59e4f054cd91d0122f717f0f6d60c28d70d5"
COMPONENTS = ("PREFLIGHT_V10_LEGACY_SHUTDOWN_V1.ps1", "STOP_V10_LEGACY_SESSION_V1.ps1")
PS = tsl.PS
ON_WINDOWS_ACTIONS = (os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
                      and os.environ.get("RUNNER_OS") == "Windows")


def git_blob(name):
    """Raw Git blob bytes at HEAD (what raw.githubusercontent.com serves)."""
    return subprocess.run(["git", "show", f"HEAD:downloads/{name}"], cwd=REPO,
                          capture_output=True, check=True).stdout


def blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class OwnerReadonlyStatic(unittest.TestCase):
    def setUp(self):
        self.text = VERIFY.read_text(encoding="utf-8")
        self.code = "\n".join(l for l in self.text.split("#>", 1)[1].splitlines()
                              if not l.lstrip().startswith("#"))

    def test_pinned_blobs_are_the_reviewed_components(self):
        self.assertIn(f'$ReviewedCommit="{PINNED}"', self.text)
        for name in COMPONENTS:
            pinned = re.search(re.escape(name) + r'";Blob="([0-9a-f]{40})"', self.text).group(1)
            self.assertEqual(blob_sha1(git_blob(name)), pinned, name)

    def test_never_stops_switches_or_touches_excel(self):
        for token in ("Stop-Process", ".Kill(", "Stop-Service", "-ComObject", "Move-Item",
                      "Set-Content", "Out-File", "Rename-Item", "taskkill", "Start-Process",
                      '"-Execute"', "'-Execute'", "-Execute "):
            self.assertNotIn(token, self.code, token)
        for line in self.code.splitlines():
            if "Remove-Item" in line:
                self.assertIn("-LiteralPath $tempRoot", line)

    def test_delivery_procedure_pins_this_entry_by_commit_blob_and_sha256(self):
        doc = (REPO / "docs" / "V10_P0_27_OWNER_READONLY_DELIVERY.md").read_text(encoding="utf-8")
        entry = subprocess.run(["git", "show", "HEAD:downloads/VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1"], cwd=REPO,
                               capture_output=True, check=True).stdout
        self.assertIn(f"`{blob_sha1(entry)}`", doc)
        self.assertIn(f"$h='{hashlib.sha256(entry).hexdigest().upper()}'", doc)
        commit = re.search(r"\$c='([0-9a-f]{40})'", doc).group(1)
        self.assertIn(f"`{commit}`", doc)
        self.assertIn("raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/$c/downloads/", doc)
        self.assertIn(f"-PinnedCommit {PINNED}", doc)
        block = doc.split("```powershell", 1)[1].split("```", 1)[0]
        self.assertNotIn("-IncludeStopDryRun", block)
        self.assertNotIn("-Execute", block)

    def test_always_reports_no_permission(self):
        for line in ("STOP_ALLOWED=false", "CUTOVER_ELIGIBLE=false", "REAL_SUBMIT_ALLOWED=false",
                     "PROCESSES_STOPPED=0", "EXCEL_ACTION=NONE", "EXCEL_WORKBOOK_COEXISTENCE=NOT_EVALUATED"):
            self.assertIn(f'Write-Output "{line}"', self.code)


@unittest.skipUnless(ON_WINDOWS_ACTIONS, "Windows Actions runner only")
class OwnerReadonlyWindows(tsl.LegacySessionSafeStop):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fixture = cls.bin / "pinned"
        cls.fixture.mkdir()
        for name in COMPONENTS:
            (cls.fixture / name).write_bytes(git_blob(name))

    def setUp(self):
        super().setUp()
        self.temp_before = self.own_temp_dirs()
        (self.root / "START_AI_COCKPIT_V10.cmd").write_text("@echo synthetic\r\n", encoding="ascii")

    def py_worker(self, role, script):
        return {"role": role, "exe": getattr(self, "py_exe", sys.executable), "args": [str(script), self.mark]}

    @staticmethod
    def own_temp_dirs():
        t = Path(tempfile.gettempdir())
        return {p.name for p in t.iterdir() if p.name.startswith(("v10-owner-readonly-", "v10-legacy-stop-dryrun-"))}

    def run_verify(self, *extra, fixture=None, exe=PS, commit=PINNED, root=None, use_fixture=True):
        argv = [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(VERIFY),
                "-PinnedCommit", commit, "-Root", str(root or self.root)]
        if use_fixture:
            argv += ["-FixtureRoot", str(fixture or self.fixture)]
        r = subprocess.run(argv + list(extra), capture_output=True, text=True, errors="replace", timeout=300)
        out = r.stdout
        print(f"--- {self._testMethodName} exit={r.returncode}\n{out}{r.stderr[-2000:]}")
        for line in ("STOP_ALLOWED=false", "CUTOVER_ELIGIBLE=false", "REAL_SUBMIT_ALLOWED=false",
                     "PROCESSES_STOPPED=0", "EXCEL_ACTION=NONE", "EXCEL_WORKBOOK_COEXISTENCE=NOT_EVALUATED",
                     "TEMP_REMOVED=true"):
            self.assertIn(line, out)
        self.assertNotIn(str(self.root), out)
        self.assertNotIn(tempfile.gettempdir(), out)
        for line in out.splitlines():
            self.assertRegex(line, r"^[A-Z0-9_]+=[A-Za-z0-9_]+$")
        pids = [self.excel_managed.pid, self.excel_business.pid, self.foreign_py.pid]
        if getattr(self, "state", None):
            pids += [int(v) for k, v in self.state.items() if k.endswith("_pid") and int(v) > 0]
        # Counts on the output are small; only a PID that cannot be a count proves a leak.
        for pid in (p for p in pids if p >= 100):
            self.assertNotRegex(out, re.compile(rf"={pid}$", re.M))
        self.assertTrue(tsl.alive(self.foreign_py))
        self.assertTrue(tsl.alive(self.excel_managed))
        self.assertTrue(tsl.alive(self.excel_business))
        self.assertEqual(self.own_temp_dirs(), self.temp_before, "temporary folder left behind")
        self.assertEqual(self.evidence_dirs(), [])
        self.assertFalse((self.root / "V10_LEGACY_STOP_RESULT.json").exists())
        return r

    def assert_blocked(self, r, reason):
        self.assertEqual(r.returncode, 2)
        self.assertIn("P0_27_RESULT=BLOCKED", r.stdout)
        self.assertIn(f"P0_27_BLOCK_REASON={reason}", r.stdout)

    def assert_session_untouched(self, before):
        self.assert_nothing_stopped()
        self.assertEqual(self.state_path.read_bytes(), before)
        self.assertTrue(all(tsl.port_listening(p) for p in (28580, 28581, 28582, 28583)))

    # -- normal ------------------------------------------------------------
    def test_01_live_session_is_verified_read_only_with_business_excel_open(self):
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.run_verify()
        self.assertEqual(r.returncode, 0)
        for line in ("P0_27_RESULT=READONLY_VERIFIED", "READ_SCOPE=STRICT_OWN_TEMP_ONLY",
                     "PINNED_COMMIT_VERIFIED=true", "SCRIPT_BLOBS_VERIFIED=2",
                     "ADMITTED_PROCESSES=11", "CONTROLLER_HOST=CONTROLLER_SCRIPT", "WORKERS_LIVE=8",
                     "VENV_CHILDREN=0", "BRIDGE_CHILDREN=2", "BRAIN_STATUS=ABSENT_VERIFIED",
                     "MANAGED_EXCEL_LIVE=true", "EXCEL_PROCESSES=2", "V10_LISTEN_PORTS=4",
                     "LISTEN_ATTRIBUTED=4", "LEGACY_RECOVERY_ACTION=NO_STOP_ATTEMPT_FOR_THIS_STATE",
                     "STATE_UNCHANGED=true", "ROOT_RESULT_AND_EVIDENCE_UNCHANGED=true",
                     "EXCEL_SET_UNCHANGED=true", "LISTENERS_UNCHANGED=true",
                     "MANAGED_PROCESSES_UNCHANGED=true", "LAUNCH_FILES_UNCHANGED=true"):
            self.assertIn(line, r.stdout)
        self.assertGreaterEqual(int(re.search(r"LAUNCH_FILES_CHECKED=(\d+)", r.stdout).group(1)), 1)
        self.assertIn("LAUNCH_SCOPE=LISTED_FOLDERS_ONLY", r.stdout)
        self.assertGreaterEqual(int(re.search(r"LAUNCH_DIRS_CHECKED=(\d+)", r.stdout).group(1)), 1)
        self.assertRegex(r.stdout, r"LAUNCH_DIRS_ABSENT=\d+")
        self.assert_session_untouched(before)

    def test_02_stop_dry_run_mode_is_distinct_and_leaves_no_temp(self):
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.run_verify("-IncludeStopDryRun")
        self.assertEqual(r.returncode, 0)
        self.assertIn("P0_27_RESULT=DRY_RUN_READY", r.stdout)
        self.assertIn("READ_SCOPE=STOP_DRY_RUN_TEMP_ALLOWED", r.stdout)
        self.assertIn("STOP_DRY_RUN_TEMP_LEFT=false", r.stdout)
        self.assertNotIn("READONLY_VERIFIED", r.stdout)
        self.assert_session_untouched(before)

    # -- SHA / package -----------------------------------------------------
    def test_03_mismatched_or_short_commit_is_blocked(self):
        self.start_session()
        before = self.state_path.read_bytes()
        self.assert_blocked(self.run_verify(commit="0" * 40), "PINNED_COMMIT_MISMATCH")
        self.assert_blocked(self.run_verify(commit=PINNED[:7]), "PINNED_COMMIT_FORMAT")
        self.assert_blocked(self.run_verify(commit=PINNED.upper()), "PINNED_COMMIT_FORMAT")
        self.assert_session_untouched(before)

    def test_04_old_or_missing_local_component_is_blocked(self):
        self.start_session()
        before = self.state_path.read_bytes()
        old = self.root / "old-local"
        old.mkdir()
        for name in COMPONENTS:
            shutil.copy(self.fixture / name, old / name)
        stop = old / COMPONENTS[1]
        stop.write_bytes(stop.read_bytes().replace(b"-RecoveryCheck", b"-RecoveryCheckOld", 1))
        self.assert_blocked(self.run_verify(fixture=old), "SCRIPT_BLOB_MISMATCH")
        crlf = self.root / "crlf-local"
        crlf.mkdir()
        for name in COMPONENTS:
            (crlf / name).write_bytes((self.fixture / name).read_bytes().replace(b"\n", b"\r\n"))
        self.assert_blocked(self.run_verify(fixture=crlf), "SCRIPT_BLOB_MISMATCH")
        (old / COMPONENTS[0]).unlink()
        self.assert_blocked(self.run_verify(fixture=old), "SCRIPT_MISSING")
        self.assert_session_untouched(before)

    # -- OWNER target absent -----------------------------------------------
    def test_05_absent_target_is_blocked(self):
        self.assert_blocked(self.run_verify(root=self.root / "missing"), "ROOT_NOT_FOUND")
        self.assert_blocked(self.run_verify(), "STATE_MISSING")
        self.assert_blocked(self.run_verify(root="relative\\root"), "TARGET_PATH_INVALID")

    # -- unknown PID / listener / bridge -------------------------------------
    def test_06_unknown_pid_or_untracked_listener_is_blocked(self):
        self.start_session()
        original = self.state_path.read_bytes()
        forged = dict(self.state, watcher_pid=self.foreign_py.pid)
        self.state_path.write_text(json.dumps(forged), encoding="utf-8")
        r = self.run_verify()
        self.assert_blocked(r, "PREFLIGHT_TRACKED_PROCESS_IDENTITY_NOT_PROVEN")
        self.assertEqual(json.loads(self.state_path.read_text(encoding="utf-8")), forged)
        self.state_path.write_bytes(original)
        late = self.spawn([sys.executable, "-c",
                           "import socket,time\ns=socket.socket(); s.bind(('127.0.0.1',28584)); s.listen(1); time.sleep(300)",
                           self.mark])
        deadline = time.time() + 30
        while time.time() < deadline and not tsl.port_listening(28584):
            time.sleep(0.2)
        self.assert_blocked(self.run_verify(), "PREFLIGHT_PORT_CHILD_IDENTITY_NOT_PROVEN")
        self.assertTrue(tsl.alive(late))
        self.assert_session_untouched(original)

    def test_07_port_child_that_is_not_a_job_host_is_blocked(self):
        self.start_session(bridge="raw")
        before = self.state_path.read_bytes()
        r = self.run_verify()
        self.assert_blocked(r, "PREFLIGHT_PORT_CHILD_IDENTITY_NOT_PROVEN")
        self.assertIn("P0_27_BLOCK_PORT=28580", r.stdout)
        self.assertIn("P0_27_BLOCK_DETAIL=", r.stdout)
        self.assert_session_untouched(before)

    # -- Excel ---------------------------------------------------------------
    def test_08_excel_pid_equal_to_worker_is_blocked(self):
        self.start_session()
        forged = dict(self.state, excel_pid=self.state["heartbeat_pid"])
        self.state_path.write_text(json.dumps(forged), encoding="utf-8")
        before = self.state_path.read_bytes()
        self.assert_blocked(self.run_verify(), "PREFLIGHT_EXCEL_PID_COLLIDES_WITH_WORKER")
        self.assert_session_untouched(before)

    # -- permissions -----------------------------------------------------------
    def test_09_unreadable_state_or_protected_process_is_blocked(self):
        self.start_session()
        before = self.state_path.read_bytes()
        user = os.environ.get("USERNAME", "")
        subprocess.run(["icacls", str(self.state_path), "/deny", f"{user}:(RD)"], check=True, capture_output=True)
        self.addCleanup(subprocess.run, ["icacls", str(self.state_path), "/remove:d", user], capture_output=True)
        self.assert_blocked(self.run_verify(), "STATE_UNREADABLE")
        subprocess.run(["icacls", str(self.state_path), "/remove:d", user], check=True, capture_output=True)
        self.assertEqual(self.state_path.read_bytes(), before)
        services = int(subprocess.run([PS, "-NoProfile", "-Command", "(Get-Process -Name services).Id"],
                                      capture_output=True, text=True, check=True).stdout.strip())
        self.state_path.write_text(json.dumps(dict(self.state, heartbeat_pid=services)), encoding="utf-8")
        self.assert_blocked(self.run_verify(), "PREFLIGHT_TRACKED_PROCESS_IDENTITY_NOT_PROVEN")
        self.state_path.write_bytes(before)
        self.assert_session_untouched(before)

    def test_10_other_powershell_is_blocked(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh not installed on runner")
        self.start_session()
        before = self.state_path.read_bytes()
        self.assert_blocked(self.run_verify(exe=pwsh), "ENVIRONMENT_UNSUPPORTED")
        self.assert_session_untouched(before)

    # -- real launch forms ---------------------------------------------------------
    def test_11_run_host_and_controller_owned_brain(self):
        self.start_session(controller=self.root / "RUN_AI_COCKPIT_V10.ps1", owned_brain=True)
        before = self.state_path.read_bytes()
        r = self.run_verify()
        self.assertEqual(r.returncode, 0)
        self.assertIn("P0_27_RESULT=READONLY_VERIFIED", r.stdout)
        self.assertIn("CONTROLLER_HOST=RUN_HOST", r.stdout)
        self.assertIn("BRAIN_STATUS=OWNED_CHILD_ADMITTED", r.stdout)
        self.assertIn("ADMITTED_PROCESSES=12", r.stdout)
        self.assert_session_untouched(before)

    def test_12_venv_python_workers_admit_their_interpreter_child(self):
        venv = self.bin / "venv"
        if not venv.exists():
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=300)
        self.py_exe = str(venv / "Scripts" / "python.exe")
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.run_verify()
        self.assertEqual(r.returncode, 0)
        self.assertIn("P0_27_RESULT=READONLY_VERIFIED", r.stdout)
        self.assertIn("VENV_CHILDREN=2", r.stdout)
        self.assertIn("ADMITTED_PROCESSES=13", r.stdout)
        self.assert_session_untouched(before)

    def test_13_orphan_brain_is_blocked(self):
        self.start_session()
        before = self.state_path.read_bytes()
        orphan = self.spawn([sys.executable, str(self.repo / "scripts" / "ai_brain_observer.py"),
                             "--live", str(self.runtime / "live_ms2.json"), self.mark])
        time.sleep(0.5)
        self.assert_blocked(self.run_verify(), "PREFLIGHT_UNTRACKED_BRAIN_CANDIDATE")
        self.assertTrue(tsl.alive(orphan))
        self.assert_session_untouched(before)

    # -- the real OWNER fetch path, no fixture -------------------------------------
    def test_14_pinned_components_fetched_from_github_match(self):
        self.start_session()
        before = self.state_path.read_bytes()
        r = self.run_verify(use_fixture=False)
        self.assertEqual(r.returncode, 0)
        self.assertIn("P0_27_RESULT=READONLY_VERIFIED", r.stdout)
        self.assertIn("SCRIPT_BLOBS_VERIFIED=2", r.stdout)
        self.assert_session_untouched(before)


OwnerReadonlyWindows.test_15_delivery_url_serves_the_documented_entry = lambda self: self._delivery()


def _delivery(self):
    doc = (REPO / "docs" / "V10_P0_27_OWNER_READONLY_DELIVERY.md").read_text(encoding="utf-8")
    commit = re.search(r"\$c='([0-9a-f]{40})'", doc).group(1)
    sha = re.search(r"\$h='([0-9A-F]{64})'", doc).group(1)
    url = f"https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/{commit}/downloads/VERIFY_V10_LEGACY_OWNER_READONLY_V1.ps1"
    out = subprocess.run([PS, "-NoProfile", "-Command",
                          "[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; "
                          f"$f=Join-Path $env:TEMP ('v10-entry-check-'+[guid]::NewGuid().ToString('N')+'.ps1'); "
                          f"Invoke-WebRequest -UseBasicParsing -Uri '{url}' -OutFile $f; "
                          "$s=[Security.Cryptography.SHA256]::Create(); ([BitConverter]::ToString($s.ComputeHash([IO.File]::ReadAllBytes($f)))).Replace('-',''); "
                          "Remove-Item -LiteralPath $f"],
                         capture_output=True, text=True, timeout=120)
    self.assertEqual(out.stdout.strip(), sha, out.stderr[-1000:])


OwnerReadonlyWindows._delivery = _delivery

# Only the P0-27 cases run here; the inherited Safe Stop cases have their own step.
for _name in dir(tsl.LegacySessionSafeStop):
    if _name.startswith("test_"):
        setattr(OwnerReadonlyWindows, _name, None)


if __name__ == "__main__":
    unittest.main()
