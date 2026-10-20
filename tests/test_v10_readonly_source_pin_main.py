"""V10 source-only admission tests. All Windows fixtures live in GitHub Actions TEMP.

No Controller, Excel, MS2, broker, runtime deployment, real orders or stops.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "downloads" / "VERIFY_V10_SOURCE_PIN_READONLY.ps1"
SOURCE = SCRIPT.read_text(encoding="utf-8-sig")


class StaticSourceOnlyContract(unittest.TestCase):
    def test_diagnostic_only_no_runtime_mode(self):
        for unsafe in ("Start-Process", "Stop-Process", "Start-Job",
                       "Invoke-Expression", "Invoke-RestMethod",
                       "Invoke-WebRequest", "New-Item", "Set-Content"):
            self.assertNotIn(unsafe, SOURCE)
        self.assertIn("V10_READONLY_SOURCE=PASS", SOURCE)
        self.assertIn("OWNER_AUTHENTICATED=0", SOURCE)
        self.assertIn("REAL_SUBMIT_ALLOWED=0", SOURCE)
        self.assertIn("--no-optional-locks", SOURCE)

    def test_source_only_requires_full_sha_and_clean_git(self):
        self.assertIn("V10_FULL_SHA_REQUIRED", SOURCE)
        self.assertIn("V10_WORKTREE_NOT_CLEAN", SOURCE)
        self.assertIn("V10_BRANCH_IDENTITY_MISMATCH", SOURCE)
        self.assertIn("V10_SHA_IDENTITY_MISMATCH", SOURCE)
        self.assertIn('--porcelain=v1","--untracked-files=all"', SOURCE)
        self.assertIn("V10_APPROVED_SOURCE_REAL_SUBMIT_MUST_BE_FALSE", SOURCE)
        self.assertIn('"--show-prefix"', SOURCE)
        self.assertIn('"--is-inside-work-tree"', SOURCE)
        self.assertIn('"--is-bare-repository"', SOURCE)
        self.assertNotIn('Read-GitText $repo @("rev-parse","--show-toplevel")', SOURCE)

    def test_canonical_pin_is_gitignored_not_committed(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8-sig")
        self.assertIn("downloads/V10_APPROVED_SOURCE.json", ignore)
        self.assertFalse((ROOT / "downloads" / "V10_APPROVED_SOURCE.json").exists())


@unittest.skipUnless(
    sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "disposable Windows GitHub Actions only"
)
class WindowsGitIdentityFixture(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git") or not shutil.which("powershell.exe"):
            self.skipTest("Git and Windows PowerShell are required")
        self.temp = tempfile.TemporaryDirectory(prefix="v10-pin-", dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "checkout"
        self.repo.mkdir()
        self.run_git("init", "-b", "reviewed-v10")
        (self.repo / "downloads").mkdir()
        (self.repo / ".gitignore").write_text(
            "downloads/V10_APPROVED_SOURCE.json\n", encoding="utf-8")
        self.tracked = self.repo / "source.txt"
        self.tracked.write_text("reviewed\n", encoding="utf-8")
        self.run_git("add", ".gitignore", "source.txt")
        self.run_git("-c", "user.name=synthetic",
                     "-c", "user.email=synthetic@example.invalid",
                     "commit", "-m", "synthetic reviewed V10 source")
        self.sha = self.run_git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(len(self.sha), 40)
        self.pin = self.repo / "downloads" / "V10_APPROVED_SOURCE.json"

    def run_git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, text=True,
                              capture_output=True, check=True, timeout=20)

    def config(self, **overrides):
        cfg = {"schema": "v10_approved_source_v1",
               "branch": "reviewed-v10", "commit_sha": self.sha,
               "real_submit_allowed": False}
        cfg.update(overrides)
        return cfg

    def verify(self, cfg=None, *, missing=False, repo_dir=None, file_content=None):
        if missing:
            self.pin.unlink(missing_ok=True)
        elif file_content is not None:
            self.pin.write_text(file_content, encoding="utf-8")
        else:
            self.pin.write_text(json.dumps(self.config() if cfg is None else cfg),
                                encoding="utf-8")
        initial_sha = self.run_git("rev-parse", "HEAD").stdout.strip()
        proc = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
             "-RepoRoot", str(repo_dir or self.repo),
             "-ApprovalFile", str(self.pin)],
            text=True, capture_output=True, timeout=40)
        final_sha = self.run_git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(initial_sha, final_sha, "preflight must not move HEAD")
        message = proc.stdout + "\n" + proc.stderr
        self.assertIn("RUNTIME_FILES_TOUCHED=0", message)
        self.assertIn("CONTROLLER_STARTED=0", message)
        self.assertIn("REAL_SUBMIT_ALLOWED=0", message)
        self.assertFalse((self.repo / "V10_RUNTIME.json").exists())
        return proc.returncode, message

    def assert_block(self, marker, cfg=None, **kwargs):
        rc, message = self.verify(cfg, **kwargs)
        self.assertNotEqual(rc, 0, message[-3000:])
        self.assertIn("V10_READONLY_SOURCE=BLOCKED", message)
        self.assertIn(marker, message, message[-3000:])

    def test_clean_and_gitignored_pin_pass(self):
        rc, message = self.verify()
        self.assertEqual(rc, 0, message[-3000:])
        for marker in ("V10_READONLY_SOURCE=PASS", "GIT_BRANCH_AND_FULL_SHA_MATCH=1",
                       "GIT_WORKTREE_CLEAN=1", "OWNER_AUTHENTICATED=0",
                       "MS2_TOUCHED=0", "EXCEL_TOUCHED=0"):
            self.assertIn(marker, message)
        self.assertEqual(self.run_git("status", "--porcelain=v1").stdout.strip(), "")

    def test_unicode_checkout_root_passes_without_decoding_git_path(self):
        # The OWNER keeps V10 under D:/100億PROJECT. Windows PowerShell 5.1
        # can misdecode Git --show-toplevel's non-ASCII stdout.
        new = self.repo.with_name("100億PROJECT_日本語")
        self.repo.rename(new)
        self.repo = new
        self.pin = self.repo / "downloads" / "V10_APPROVED_SOURCE.json"
        rc, message = self.verify()
        self.assertEqual(rc, 0, message[-3000:])
        self.assertIn("V10_READONLY_SOURCE=PASS", message)

    def test_unicode_checkout_nested_root_is_rejected(self):
        new = self.repo.with_name("100億PROJECT_日本語")
        self.repo.rename(new)
        self.repo = new
        self.pin = self.repo / "downloads" / "V10_APPROVED_SOURCE.json"
        self.assert_block("V10_CHECKOUT_ROOT_MISMATCH",
                          repo_dir=self.repo / "downloads")

    def test_missing_pin_rejected(self):
        self.assert_block("V10_APPROVED_SOURCE_FILE_MISSING", missing=True)

    def test_malformed_json_rejected(self):
        self.assert_block("V10_READONLY_CHECK_ERROR", file_content="{broken")

    def test_bad_schema_rejected(self):
        self.assert_block("V10_APPROVED_SOURCE_SCHEMA_INVALID",
                          self.config(schema="wrong"))

    def test_unknown_schema_fields_rejected(self):
        self.assert_block("V10_APPROVED_SOURCE_SCHEMA_INVALID",
                          self.config(unexpected="not accepted"))

    def test_real_submit_true_rejected(self):
        self.assert_block("V10_APPROVED_SOURCE_REAL_SUBMIT_MUST_BE_FALSE",
                          self.config(real_submit_allowed=True))

    def test_real_submit_string_rejected(self):
        self.assert_block("V10_APPROVED_SOURCE_REAL_SUBMIT_MUST_BE_FALSE",
                          self.config(real_submit_allowed="false"))

    def test_short_sha_rejected(self):
        self.assert_block("V10_FULL_SHA_REQUIRED",
                          self.config(commit_sha=self.sha[:8]))

    def test_wrong_full_sha_rejected(self):
        self.assert_block("V10_SHA_IDENTITY_MISMATCH",
                          self.config(commit_sha="0" * 40))

    def test_wrong_branch_rejected(self):
        self.assert_block("V10_BRANCH_IDENTITY_MISMATCH",
                          self.config(branch="foreign-v10"))

    def test_invalid_branch_path_rejected(self):
        self.assert_block("V10_REVIEWED_BRANCH_INVALID",
                          self.config(branch="../unreviewed"))

    def test_staged_file_modification_rejected(self):
        self.tracked.write_text("modified\n", encoding="utf-8")
        self.run_git("add", "source.txt")
        self.assert_block("V10_WORKTREE_NOT_CLEAN")

    def test_unstaged_file_modification_rejected(self):
        self.tracked.write_text("modified\n", encoding="utf-8")
        self.assert_block("V10_WORKTREE_NOT_CLEAN")

    def test_untracked_source_rejected(self):
        (self.repo / "foreign.py").write_text("unreviewed\n", encoding="utf-8")
        self.assert_block("V10_WORKTREE_NOT_CLEAN")

    def test_nested_checkout_root_rejected(self):
        self.assert_block("V10_CHECKOUT_ROOT_MISMATCH",
                          repo_dir=self.repo / "downloads")

    def test_detached_head_refused(self):
        self.run_git("checkout", "--detach", "-q", "HEAD")
        self.assert_block("V10_GIT_CHECK_FAILED")

    def test_oversized_manifest_rejected(self):
        self.assert_block("V10_APPROVED_SOURCE_SIZE_INVALID",
                          file_content=" " * 5000)


if __name__ == "__main__":
    unittest.main()
