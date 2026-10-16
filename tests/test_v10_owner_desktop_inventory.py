"""P0-16: isolated Windows read-only desktop entry inventory.

All paths below RUNNER_TEMP; no connection to a real Desktop, Excel or MS2.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
AUDITOR = SOURCE_ROOT / "downloads" / "INVENTORY_V10_OWNER_DESKTOP_READONLY.ps1"
STOP = SOURCE_ROOT / "downloads" / "STOP_AI_COCKPIT_V10.ps1"


@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "Owner Desktop inventory only tests in Windows GitHub Actions",
)
class OwnerDesktopReadOnlyFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="v10-owner-readonly-", dir=os.environ["RUNNER_TEMP"]
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "checkout"
        (self.repo / "downloads").mkdir(parents=True)
        self.stop = self.repo / "downloads" / "STOP_AI_COCKPIT_V10.ps1"
        shutil.copy2(STOP, self.stop)
        shutil.copy2(SOURCE_ROOT / "downloads" / "RUN_AI_COCKPIT_V10.ps1",
                     self.repo / "downloads" / "RUN_AI_COCKPIT_V10.ps1")
        self.desktop = self.root / "desktop"
        self.desktop.mkdir()
        self.start = self.desktop / "AIコクピット_起動.cmd"
        self.stopcmd = self.desktop / "AIコクピット_安全停止.cmd"
        self.write_cmd(self.start, self.repo / "downloads" / "RUN_AI_COCKPIT_V10.ps1")
        self.write_cmd(self.stopcmd, self.stop)
        self.git("init", "-b", "ci-pin")
        self.git("add", "downloads/STOP_AI_COCKPIT_V10.ps1",
                 "downloads/RUN_AI_COCKPIT_V10.ps1")
        self.git("-c", "user.name=P0-CI", "-c", "user.email=ci@example.invalid",
                 "commit", "-m", "synthetic fixture only")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()

    def write_cmd(self, dest, target, extra=""):
        dest.write_text(
            "@echo off\nsetlocal\n"
            'powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "'
            + str(target) + '"\n' + extra, encoding="utf-8",
        )

    def git(self, *args):
        p = subprocess.run(
            ["git", *args], cwd=self.repo, capture_output=True,
            text=True, errors="replace", timeout=20,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def audit(self, sha=None, branch="ci-pin", desktop=None):
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
             str(AUDITOR), "-RepoRoot", str(self.repo),
             "-DesktopRoot", str(desktop or self.desktop),
             "-ExpectedBranch", branch, "-ExpectedSha", sha or self.sha],
            capture_output=True, text=True, errors="replace", timeout=25,
        )
        return p

    def assert_blocked(self, result, reason=None):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("V10_OWNER_DESKTOP_INVENTORY=BLOCKED", result.stdout)
        self.assertIn("REAL_SUBMIT_ALLOWED=0", result.stdout)
        self.assertNotIn(str(self.repo), result.stdout)
        self.assertNotIn(str(self.desktop), result.stdout)
        if reason is not None:
            self.assertIn(reason, result.stdout)

    def test_correct_pinned_desktop_routes_readonly(self):
        before = (self.stop.read_bytes(), self.start.read_bytes(),
                  self.stopcmd.read_bytes())
        p = self.audit()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        for token in (
            "V10_PIN=VERIFIED", "V10_STOP_SOURCE=PRESENT",
            "V10_START_SOURCE=PRESENT",
            "DESKTOP_START_ROUTE=EXPECTED", "DESKTOP_STOP_ROUTE=EXPECTED",
            "V10_OWNER_DESKTOP_INVENTORY=ROUTES_READONLY_VERIFIED",
            "OWNER_LIVE_RUNTIME_VERIFIED=0", "REAL_SUBMIT_ALLOWED=0",
        ):
            self.assertIn(token, p.stdout)
        self.assertEqual(before, (self.stop.read_bytes(), self.start.read_bytes(),
                                  self.stopcmd.read_bytes()))
        self.assertEqual(self.git("status", "--porcelain").stdout.strip(), "")

    def test_legacy_stop_rejected(self):
        self.write_cmd(self.stopcmd, self.repo / "downloads" / "STOP_AI_COCKPIT.ps1")
        self.assert_blocked(self.audit(), "DESKTOP_STOP_ROUTE=LEGACY_OR_FOREIGN")

    def test_legacy_start_rejected(self):
        self.write_cmd(self.start, self.repo / "downloads" / "RUN_AI_COCKPIT_V9.ps1")
        self.assert_blocked(self.audit(), "DESKTOP_START_ROUTE=LEGACY_OR_FOREIGN")

    def test_missing_stop_refused(self):
        self.stopcmd.unlink()
        self.assert_blocked(self.audit(), "DESKTOP_STOP_ROUTE=MISSING")

    def test_missing_start_script_does_not_pass_even_with_correct_cmd(self):
        (self.repo / "downloads" / "RUN_AI_COCKPIT_V10.ps1").unlink()
        self.assert_blocked(self.audit(), "V10_PIN=BLOCKED")

    def test_missing_start_refused(self):
        self.start.unlink()
        self.assert_blocked(self.audit(), "DESKTOP_START_ROUTE=MISSING")

    def test_command_injection_refused(self):
        self.write_cmd(self.stopcmd, self.stop, "taskkill /f /im python.exe\n")
        self.assert_blocked(self.audit(), "DESKTOP_STOP_ROUTE=BLOCKED")

    def test_wrong_branch_or_sha_refused(self):
        self.assert_blocked(self.audit(branch="unapproved"), "V10_PIN=BLOCKED")
        self.assert_blocked(self.audit(sha="0" * 40), "V10_PIN=BLOCKED")

    def test_dirty_tracked_source_refused(self):
        with self.stop.open("a", encoding="utf-8") as f:
            f.write("\n# modified after the approved commit\n")
        self.assert_blocked(self.audit(), "V10_PIN=BLOCKED")

    def test_absent_desktop_refused(self):
        self.assert_blocked(
            self.audit(desktop=self.root / "nonexistent"),
            "DESKTOP_STOP_ROUTE=MISSING",
        )

    def test_parser_selftest(self):
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
             str(AUDITOR), "-SelfTest"],
            capture_output=True, text=True, errors="replace", timeout=15,
        )
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("PASS: P0_16_DESKTOP_ROUTE_PARSER", p.stdout)


if __name__ == "__main__":
    unittest.main()
