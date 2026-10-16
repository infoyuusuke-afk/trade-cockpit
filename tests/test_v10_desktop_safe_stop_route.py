"""P0-15: read-only Desktop CMD -> verified local V10 STOP integration gates.

Only runs under Windows GitHub Actions; uses an isolated synthetic git checkout.
Never executes the inspected CMD or actual V10 Stop script.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "downloads" / "VERIFY_V10_DESKTOP_SAFE_STOP_ROUTE.ps1"
STOP = ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1"


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "Read-only Desktop route integration runs on isolated Windows Actions only",
)
class PinnedDesktopRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="v10-stop-route-", dir=os.environ["RUNNER_TEMP"],
        )
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.repo = self.folder / "repo"
        (self.repo / "downloads").mkdir(parents=True)
        self.stop = self.repo / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
        shutil.copyfile(STOP, self.stop)
        self.desktop = self.folder / "desktop"
        self.desktop.mkdir()
        self.cmd = self.desktop / "AIコクピット_安全停止.cmd"
        self.git("init", "-b", "ci-pin")
        self.git("add", "downloads/STOP_AI_COCKPIT_V10.ps1")
        self.git("-c", "user.name=V10-CI", "-c", "user.email=ci@example.invalid",
                 "commit", "-m", "synthetic stop fixture")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(len(self.sha), 40)
        self.write_cmd(self.stop)

    def git(self, *args):
        p = subprocess.run(["git", *args], cwd=self.repo,
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def write_cmd(self, stop, extra=""):
        self.cmd.write_text(
            "@echo off\n"
            "setlocal\n"
            f'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "{stop}"\n'
            + extra, encoding="utf-8",
        )

    def audit(self, *, expected_sha=None, expected_branch="ci-pin",
              cmd_path=None):
        return subprocess.run([
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-File", str(AUDITOR), "-RepoRoot", str(self.repo),
            "-DesktopStopCmd", str(cmd_path or self.cmd),
            "-ExpectedBranch", expected_branch,
            "-ExpectedSha", expected_sha or self.sha,
        ], capture_output=True, text=True, errors="replace", timeout=20)

    def check_block(self, result):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("V10_SAFE_STOP_ROUTE=BLOCKED", result.stdout)
        self.assertTrue(self.stop.exists())
        self.assertIn("REAL_SUBMIT_ALLOWED=0", result.stdout)

    def test_approved_local_absolute_route_only_reads(self):
        before = self.stop.read_bytes()
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("V10_SAFE_STOP_ROUTE=VERIFIED_READONLY", result.stdout)
        self.assertIn("OWNER_LIVE_STOP_VERIFIED=0", result.stdout)
        self.assertEqual(self.stop.read_bytes(), before)
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

    def test_legacy_broad_kill_script_is_rejected(self):
        self.write_cmd(self.repo / "downloads" / "STOP_AI_COCKPIT.ps1")
        self.check_block(self.audit())

    def test_two_commands_or_injection_rejected(self):
        self.write_cmd(self.stop, "taskkill /f /im python.exe\n")
        self.check_block(self.audit())
        self.write_cmd(str(self.stop) + '" & taskkill /f /im python.exe & echo "')
        self.check_block(self.audit())

    def test_wrong_sha_and_branch_rejected(self):
        self.check_block(self.audit(expected_sha="0"*40))
        self.check_block(self.audit(expected_branch="not-approved"))

    def test_tracked_checkout_dirty_is_rejected(self):
        with self.stop.open("a", encoding="utf-8") as handle:
            handle.write("\n# tampered AFTER pinned commit\n")
        self.check_block(self.audit())

    def test_desktop_relative_script_path_is_not_mistaken_for_repo(self):
        self.write_cmd("%~dp0STOP_AI_COCKPIT_V10.ps1")
        self.check_block(self.audit())

    def test_missing_desktop_cmd_is_refused(self):
        self.cmd.unlink()
        self.check_block(self.audit())

    def test_repository_wrapper_is_correct_route(self):
        fixture = self.repo / "downloads" / "STOP_AI_COCKPIT_V10.cmd"
        fixture.write_text(
            '@echo off\nsetlocal\nset "SCRIPT=%~dp0STOP_AI_COCKPIT_V10.ps1"\n'
            'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"\n'
            'set "RC=%ERRORLEVEL%"\nif not "%RC%"=="0" pause\nexit /b %RC%\n',
            encoding="utf-8",
        )
        result = self.audit(cmd_path=fixture)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
