"""V10 source admission: git read-only startup must reject wrong branch/SHA.

All tests are synthetic. Windows tests use a temporary disposable Git
repository and intentionally WRONG admissions; the real Controller,
MS2/Excel, and broker are never launched.
"""
import json
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

    def test_read_only_preflight_checks_full_identity_before_any_deploy(self):
        self.assertIn("[switch]$VerifySourceOnly", SOURCE)
        self.assertIn("SOURCE_ONLY_REQUIRES_PINNED_SHA", SOURCE)
        self.assertIn("SOURCE_ONLY_FORBIDS_RUNTIME_ACTIONS", SOURCE)
        self.assertIn("V10_SOURCE_ONLY=PASS", SOURCE)
        self.assertIn("GIT_BRANCH_AND_FULL_SHA_MATCH=1", SOURCE)
        self.assertIn("SOURCE_AUTHENTICATED=0", SOURCE)
        self.assertIn("RUNTIME_FILES_TOUCHED=0", SOURCE)
        self.assertIn("CONTROLLER_STARTED=0", SOURCE)
        self.assertLess(SOURCE.index('if ($actualBranch -cne $Branch)'),
                        SOURCE.index('Write-Host "V10_SOURCE_ONLY=PASS"'))
        self.assertLess(SOURCE.index("PINNED_SHA_IDENTITY_MISMATCH"),
                        SOURCE.index('Write-Host "V10_SOURCE_ONLY=PASS"'))
        self.assertLess(SOURCE.index('Write-Host "V10_SOURCE_ONLY=PASS"'),
                        SOURCE.index('Write-Host "Deploying runtime scripts'))
        self.assertLess(SOURCE.index('if ($VerifySourceOnly -and $RuntimeAcceptSelfTest)'),
                        SOURCE.index('if ($RuntimeAcceptSelfTest)'))

    def test_one_click_has_no_implicit_old_branch_and_requires_local_pin(self):
        cmd = (ROOT / "downloads" / "START_AI_COCKPIT_V10.cmd").read_text(encoding="utf-8-sig")
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")
        self.assertIn('[string]$Branch = ""', SOURCE)
        self.assertIn("V10_NORMAL_START_REQUIRES_PINNED_SHA", SOURCE)
        self.assertIn("V10_REVIEWED_BRANCH_REQUIRED", SOURCE)
        self.assertIn("V10_APPROVED_SOURCE_FILE_MISSING", SOURCE)
        self.assertIn("V10_APPROVED_SOURCE_REAL_SUBMIT_MUST_BE_FALSE", SOURCE)
        self.assertIn("APPROVAL_FILE_DISALLOWS_OVERRIDE", SOURCE)
        self.assertIn('-ApprovalFile "%APPROVAL%"', cmd)
        self.assertIn("V10_APPROVED_SOURCE.json", cmd)
        self.assertNotIn("cursor/p0-stale-price-failclosed-d483", cmd)
        self.assertIn("downloads/V10_APPROVED_SOURCE.json", ignore)
        self.assertFalse((ROOT / "downloads" / "V10_APPROVED_SOURCE.json").exists(),
                         "Owner-local approved pin must never be committed")
        self.assertLess(SOURCE.index("V10_NORMAL_START_REQUIRES_PINNED_SHA"),
                        SOURCE.index('Write-Host "Deploying runtime scripts'))

    def test_worktree_clean_and_approval_gate_precede_runtime(self):
        self.assertIn("V10_WORKTREE_NOT_CLEAN", SOURCE)
        self.assertIn("V10_MUTATING_START_REQUIRES_APPROVAL_FILE", SOURCE)
        self.assertIn('git checkout', SOURCE)  # comments may mention recovery, never execute it
        self.assertIn('--porcelain=v1", "--untracked-files=all"', SOURCE)
        deploy = SOURCE.index('Write-Host "Deploying runtime scripts')
        self.assertLess(SOURCE.index("V10_WORKTREE_NOT_CLEAN"), deploy)
        self.assertLess(SOURCE.index("V10_MUTATING_START_REQUIRES_APPROVAL_FILE"), deploy)
        self.assertLess(SOURCE.index("V10_WORKTREE_NOT_CLEAN"),
                        SOURCE.index('Write-Host "V10_SOURCE_ONLY=PASS"'))

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

    def invoke_source_only(self, branch, sha, extra=()):
        state_root = self.root / "source_only_no_files"
        args = [
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
            "-RepoRoot", str(self.checkout),
            "-Root", str(state_root),
            "-Branch", branch,
            "-ExpectedSha", sha,
            "-VerifySourceOnly",
            *extra,
        ]
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.checkout,
                                text=True, capture_output=True, check=True).stdout.strip()
        result = subprocess.run(args, input="\n", text=True,
                                capture_output=True, timeout=35)
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.checkout,
                               text=True, capture_output=True, check=True).stdout.strip()
        self.assertEqual(before, after, "verify mode modified Git HEAD")
        self.assertFalse(state_root.exists(), "verify mode touched runtime state directory")
        return result, result.stdout + "\n" + result.stderr

    def test_source_only_positive_uses_matching_branch_and_full_sha(self):
        result, output = self.invoke_source_only("reviewed-v10", self.sha)
        self.assertEqual(result.returncode, 0, output[-3000:])
        for marker in ("V10_SOURCE_ONLY=PASS", "GIT_BRANCH_AND_FULL_SHA_MATCH=1",
                       "RUNTIME_FILES_TOUCHED=0", "CONTROLLER_STARTED=0",
                       "EXCEL_TOUCHED=0", "MS2_TOUCHED=0",
                       "SOURCE_AUTHENTICATED=0", "REAL_SUBMIT_ALLOWED=0"):
            self.assertIn(marker, output)

    def test_source_only_without_sha_fails_closed(self):
        result, output = self.invoke_source_only("reviewed-v10", "")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_ONLY_REQUIRES_PINNED_SHA", output)
        self.assertIn("V10_SOURCE_ONLY=BLOCKED", output)

    def test_source_only_with_deploy_flag_fails_closed(self):
        result, output = self.invoke_source_only("reviewed-v10", self.sha,
                                                  ("-DeployRuntimeOnly",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_ONLY_FORBIDS_RUNTIME_ACTIONS", output)

    def test_source_only_wrong_branch_fails_closed(self):
        result, output = self.invoke_source_only("foreign-branch", self.sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BRANCH_IDENTITY_MISMATCH", output)
        self.assertIn("V10_SOURCE_ONLY=BLOCKED", output)

    def test_source_only_with_selftest_refuses_before_writes(self):
        result, output = self.invoke_source_only("reviewed-v10", self.sha,
                                                  ("-RuntimeAcceptSelfTest",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_ONLY_FORBIDS_RUNTIME_ACTIONS", output)

    def invoke_approval(self, config, flags=('-VerifySourceOnly',)):
        approval_path = self.root / "synthetic_V10_APPROVED_SOURCE.json"
        if config is None:
            approval_path.unlink(missing_ok=True)
        elif isinstance(config, str):
            approval_path.write_text(config, encoding="utf-8")
        else:
            approval_path.write_text(json.dumps(config), encoding="utf-8")
        state_dir = self.root / "approval_only_no_runtime"
        args = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
                "-RepoRoot", str(self.checkout),
                "-Root", str(state_dir),
                "-ApprovalFile", str(approval_path), *flags]
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.checkout,
                                check=True, text=True, capture_output=True).stdout.strip()
        result = subprocess.run(args, capture_output=True, text=True,
                                input="\n", timeout=35)
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.checkout,
                               check=True, text=True, capture_output=True).stdout.strip()
        self.assertEqual(before, after, "pin parser modified Git HEAD")
        self.assertFalse(state_dir.exists(), "pin parser touched the state directory")
        return result, result.stdout + "\n" + result.stderr

    def reviewed(self, **overrides):
        config = {"schema": "v10_approved_source_v1",
                  "branch": "reviewed-v10", "commit_sha": self.sha,
                  "real_submit_allowed": False}
        config.update(overrides)
        return config

    def test_approved_local_pin_allows_source_only_without_runtime(self):
        res, output = self.invoke_approval(self.reviewed())
        self.assertEqual(res.returncode, 0, output[-3000:])
        self.assertIn("V10_SOURCE_ONLY=PASS", output)
        self.assertIn("REAL_SUBMIT_ALLOWED=0", output)

    def test_missing_local_pin_refused(self):
        res, output = self.invoke_approval(None)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("V10_APPROVED_SOURCE_FILE_MISSING", output)
        self.assertIn("V10_APPROVED_SOURCE=BLOCKED", output)

    def test_malformed_local_pin_refused(self):
        res, output = self.invoke_approval("{NOT JSON}")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("V10_APPROVED_SOURCE=BLOCKED", output)

    def test_local_pin_enabling_real_trading_refused(self):
        res, output = self.invoke_approval(self.reviewed(real_submit_allowed=True))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("V10_APPROVED_SOURCE_REAL_SUBMIT_MUST_BE_FALSE", output)

    def test_local_pin_short_sha_refused(self):
        res, output = self.invoke_approval(self.reviewed(commit_sha=self.sha[:8]))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("PINNED_SHA_MUST_BE_FULL_40_HEX", output)

    def test_local_pin_bad_branch_refused(self):
        res, output = self.invoke_approval(self.reviewed(branch="../unreviewed"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("V10_REVIEWED_BRANCH_INVALID", output)

    def test_local_pin_commandline_override_refused(self):
        res, output = self.invoke_approval(self.reviewed(),
                                           ("-VerifySourceOnly", "-Branch", "reviewed-v10"))
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("APPROVAL_FILE_DISALLOWS_OVERRIDE", output)

    def test_ordinary_unpinned_launcher_is_blocked_before_deploy(self):
        res, output = self.invoke_approval(None, flags=())
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("V10_APPROVED_SOURCE_FILE_MISSING", output)

    def test_direct_normal_launch_requires_sha_even_with_branch(self):
        state_dir = self.root / "direct_unpinned_never_started"
        args = ["powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
                "-RepoRoot", str(self.checkout),
                "-Root", str(state_dir), "-Branch", "reviewed-v10"]
        res = subprocess.run(args, text=True, capture_output=True, input="\n", timeout=35)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("V10_NORMAL_START_REQUIRES_PINNED_SHA", res.stdout)
        self.assertFalse(state_dir.exists())

    def test_dirty_tracked_checkout_refuses_read_only_pass(self):
        tracked = self.checkout / "tracked-v10-source.txt"
        tracked.write_text("known-good", encoding="utf-8")
        try:
            subprocess.run(["git", "add", tracked.name], cwd=self.checkout,
                           capture_output=True, text=True, check=True, timeout=15)
            result, output = self.invoke_source_only("reviewed-v10", self.sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("V10_WORKTREE_NOT_CLEAN", output)
            self.assertIn("V10_SOURCE_ONLY=BLOCKED", output)
        finally:
            subprocess.run(["git", "reset", "--quiet"], cwd=self.checkout,
                           capture_output=True, text=True, check=True, timeout=15)
            tracked.unlink(missing_ok=True)

    def test_untracked_checkout_refuses_read_only_pass(self):
        untracked = self.checkout / "foreign-entry.py"
        untracked.write_text("print('unreviewed')\n", encoding="utf-8")
        try:
            result, output = self.invoke_source_only("reviewed-v10", self.sha)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("V10_WORKTREE_NOT_CLEAN", output)
            self.assertIn("V10_SOURCE_ONLY=BLOCKED", output)
        finally:
            untracked.unlink(missing_ok=True)

    def test_cli_branch_sha_cannot_authorize_normal_runtime(self):
        state = self.root / "no_direct_mutating_runtime"
        args = ["powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
                "-RepoRoot", str(self.checkout), "-Root", str(state),
                "-Branch", "reviewed-v10", "-ExpectedSha", self.sha]
        result = subprocess.run(args, input="\n", capture_output=True,
                                text=True, timeout=35)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V10_MUTATING_START_REQUIRES_APPROVAL_FILE",
                      result.stdout + result.stderr)
        self.assertFalse(state.exists())

    def test_cli_branch_sha_cannot_authorize_deploy_only(self):
        state = self.root / "no_direct_deploy_runtime"
        args = ["powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(RUNNER),
                "-RepoRoot", str(self.checkout), "-Root", str(state),
                "-Branch", "reviewed-v10", "-ExpectedSha", self.sha,
                "-DeployRuntimeOnly"]
        result = subprocess.run(args, input="\n", capture_output=True,
                                text=True, timeout=35)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("V10_MUTATING_START_REQUIRES_APPROVAL_FILE",
                      result.stdout + result.stderr)
        self.assertFalse(state.exists())

    def test_wrong_branch_refused_before_runtime(self):
        self.invoke_invalid("unexpected-branch", self.sha, "BRANCH_IDENTITY_MISMATCH")

    def test_short_sha_refused_before_runtime(self):
        self.invoke_invalid("reviewed-v10", self.sha[:8], "PINNED_SHA_MUST_BE_FULL_40_HEX")

    def test_other_full_sha_refused_before_runtime(self):
        self.invoke_invalid("reviewed-v10", "0" * 40, "PINNED_SHA_IDENTITY_MISMATCH")


if __name__ == "__main__":
    unittest.main()
