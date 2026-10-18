"""Run the REAL Controller entrypoint in non-starting lock probe mode.

Windows GitHub Actions only: all state is under RUNNER_TEMP. This test
never starts Excel, MS2, a market gateway, workers, or an order endpoint.
"""
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

CONTROLLER = Path(__file__).resolve().parents[1] / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows"
    and shutil.which("powershell.exe"),
    "Disposable Windows hosted PowerShell test only",
)
class ControllerLifecycleLock(unittest.TestCase):
    def test_controller_refuses_competing_archive_and_can_probe_after_release(self):
        with tempfile.TemporaryDirectory(prefix="v10-controller-mutex-", dir=os.environ["RUNNER_TEMP"]) as tmp:
            root = Path(tmp) / "state root"
            root.mkdir()
            state = root / "V10_CONTROLLER_STATE.json"
            canonical = str(root.resolve()).rstrip("\\").upper()
            mutex_name = "Local\\AI_Cockpit_V10_Lifecycle_" + hashlib.sha256(
                canonical.encode("utf-8")
            ).hexdigest().upper()
            ready = root / "locked.marker"
            holder_script = root / "synthetic-lock.ps1"
            holder_script.write_text(
                "$ErrorActionPreference='Stop'\n"
                "$m=New-Object Threading.Mutex($false,'" + mutex_name + "')\n"
                "try {\n"
                "  if (-not $m.WaitOne(0)) { throw 'LOCK_NOT_ACQUIRED' }\n"
                "  [IO.File]::WriteAllText('" + str(ready).replace("'", "''") + "','ready')\n"
                "  Start-Sleep -Seconds 25\n"
                "} finally { try { $m.ReleaseMutex() } catch {}; $m.Dispose() }\n",
                encoding="utf-8",
            )
            holder = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(holder_script)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                deadline = time.monotonic() + 12
                while not ready.exists() and time.monotonic() < deadline:
                    self.assertIsNone(holder.poll(), "synthetic archive mutex holder failed")
                    time.sleep(0.1)
                self.assertTrue(ready.exists(), "synthetic lock was never acquired")
                args = ["powershell.exe", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-File", str(CONTROLLER),
                        "-Root", str(root), "-LifecycleLockProbeSelfTest"]
                blocked = subprocess.run(args, capture_output=True, text=True,
                                         errors="replace", timeout=20)
                self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
                self.assertIn("V10_LIFECYCLE_LOCK_BUSY", blocked.stdout + blocked.stderr)
                self.assertFalse(state.exists(), "blocked Controller modified its state")
            finally:
                if holder.poll() is None:
                    holder.kill()
                holder.wait(timeout=10)
            allowed = subprocess.run(args, capture_output=True, text=True,
                                     errors="replace", timeout=20)
            self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
            self.assertIn("V10_CONTROLLER_LIFECYCLE_LOCK=ACQUIRED", allowed.stdout)
            self.assertFalse(state.exists(), "lock self-test started a V10 session")
            self.assertEqual(list(root.glob("*.archived.*")), [])


if __name__ == "__main__":
    unittest.main()
