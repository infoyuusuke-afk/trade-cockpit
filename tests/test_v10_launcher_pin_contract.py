"""V10 source admission: git read-only startup must reject wrong branch/SHA.

All tests are synthetic. Windows tests use a temporary disposable Git
repository and intentionally WRONG admissions; the real Controller,
MS2/Excel, and broker are never launched.
"""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "downloads" / "RUN_AI_COCKPIT_V10.ps1"
SOURCE = RUNNER.read_text(encoding="utf-8-sig")


class V10SourceAdmissionContract(unittest.TestCase):
    def test_branch_admission_is_unconditional_even_when_updates_skipped(self):
        self.assertIn("$SkipGitUpdate = $true", SOURCE)
        self.assertIn("if ($actualBranch -cne $Branch)", SOURCE)
        self.assertNotIn("if (-not $SkipGitUpdate -and $actualBranch -ne $Branch)", SOURCE)
        self.assertIn("BRANCH_IDENTITY_MISMATCH", SOURCE)

    def test_sha_admission_rejects_prefix_and_compares_full_identity(self):
        self.assertIn("PINNED_SHA_MUST_BE_FULL_40_HEX", SOURCE)
        self.assertIn("^[0-9a-fA-F]{40}$", SOURCE)
        self.assertIn("[string]::Equals($actualSha, $ExpectedSha", SOURCE)
        self.assertNotIn("$actualSha.StartsWith($ExpectedSha)", SOURCE)
        self.assertIn("PINNED_SHA_IDENTITY_MISMATCH", SOURCE)

    def test_source_admission_occurs_before_any_runtime_deployment(self):
        admission = SOURCE.index('if ($actualBranch -cne $Branch)')
        sha_check = SOURCE.index('PINNED_SHA_MUST_BE_FULL_40_HEX')
        deployment = SOURCE.index('Write-Host "Deploying runtime scripts')
        self.assertLess(admission, sha_check)
        self.assertLess(sha_check, deployment)

    def test_offline_selftest_entry_stays_independent(self):
        self.assertIn("if ($RuntimeAcceptSelfTest)", SOURCE)
        self.assertLess(SOURCE.index("if ($RuntimeAcceptSelfTest)"),
                        SOURCE.index('if ($actualBranch -cne $Branch)'))


@unittest.skipUnless(sys.platform == "win32", "Windows PowerShell 5.1 negative acceptance")
class WindowsOfflineWrongSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("git") is None or shutil.which("powershell.exe") is None:
            raise unittest.SkipTest("git or Windows PowerShell unavailable")
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.checkout = cls.root / "synthetic_checkout"
        cls.checkout.mkdir()
        def git(*args):
            return subprocess.run(["git", *args], cwd=cls.checkout,
                                  text=True, capture_output=True, check=True, timeout=20)
        git("init", "-b", "reviewed-v10")
        git("-c", "user.name=synthetic", "-c", "user.email=synthetic@example.invalid",
            "commit", "--allow-empty", "-m", "synthetic reviewed source")
        cls.sha = git("rev-parse", "HEAD").stdout.strip()
        assert len(cls.sha) == 40

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def invoke_invalid(self, branch, expected_sha, marker):
        state_root = self.root / ("no_runtime_" + marker.lower())
        args = [
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
            "-RepoRoot", str(self.checkout),
            "-Root", str(state_root),
            "-Branch", branch,
            "-ExpectedSha", expected_sha,
            "-DeployRuntimeOnly",
        ]
        p = subprocess.run(args, input="\n", text=True,
                           capture_output=True, timeout=35)
        output = p.stdout + "\n" + p.stderr
        self.assertNotEqual(p.returncode, 0, output[-3000:])
        self.assertIn(marker, output, output[-3000:])
        self.assertFalse((state_root / "V10_RUNTIME.json").exists())
        self.assertFalse((state_root / "V10_CONTROLLER_STATE.json").exists())

    def test_wrong_branch_refused_before_runtime(self):
        self.invoke_invalid("unexpected-branch", self.sha, "BRANCH_IDENTITY_MISMATCH")

    def test_short_sha_refused_before_runtime(self):
        self.invoke_invalid("reviewed-v10", self.sha[:8], "PINNED_SHA_MUST_BE_FULL_40_HEX")

    def test_other_full_sha_refused_before_runtime(self):
        self.invoke_invalid("reviewed-v10", "0" * 40, "PINNED_SHA_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
