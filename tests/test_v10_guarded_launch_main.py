"""V10 guarded one-click entrance. Synthetic, no actual Owner runtime.

Windows subprocess tests use an entirely disposable Git checkout and
fake reviewed RUN that merely prints a fixed marker; no process is
started outside those bounded test PowerShell child processes.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "downloads" / "START_AI_COCKPIT_V10.ps1"
VERIFY = ROOT / "downloads" / "VERIFY_V10_SOURCE_PIN_READONLY.ps1"
CMD = ROOT / "downloads" / "START_AI_COCKPIT_V10.cmd"
SOURCE = GUARD.read_text(encoding="utf-8-sig")
CMD_TEXT = CMD.read_text(encoding="utf-8-sig")


class V10GuardedLaunchContract(unittest.TestCase):
    def test_canonical_oneclick_never_calls_old_launcher(self):
        self.assertIn("START_AI_COCKPIT_V10.ps1", CMD_TEXT)
        self.assertIn('"%LAUNCHER%" -ApprovalFile "%APPROVAL%"', CMD_TEXT)
        self.assertNotIn("RUN_AI_COCKPIT_V10.ps1", CMD_TEXT)
        self.assertNotIn("START_AI_COCKPIT_CLEAN", CMD_TEXT)
        self.assertNotIn("START_AI_COCKPIT_V9", CMD_TEXT)

    def test_source_verification_precedes_component_or_runner_calls(self):
        source_gate = SOURCE.index('V10_READONLY_SOURCE=PASS')
        bundle = SOURCE.index('foreach ($relative in $required)')
        handoff = SOURCE.index('V10_REVIEWED_RUNNER_HANDOFF=1')
        self.assertLess(source_gate, bundle)
        self.assertLess(bundle, handoff)
        self.assertIn('-File $verifier -RepoRoot $repo -ApprovalFile $ApprovalFile', SOURCE)
        self.assertIn('-File $runner -RepoRoot $repo -ApprovalFile $ApprovalFile', SOURCE)

    def test_gate_has_no_auto_checkout_or_runtime_repair(self):
        for forbidden in ("git reset", "git checkout", "git pull", "git fetch",
                          "Stop-Process", "Start-Process", "Remove-Item"):
            self.assertNotIn(forbidden, SOURCE)
        self.assertIn("V10_RELEASE_COMPONENT_MISSING", SOURCE)
        self.assertIn("V10_RUNNER_APPROVAL_CONTRACT_MISSING", SOURCE)
        self.assertIn("V10_START_PREFLIGHT=PASS_NO_RUNTIME", SOURCE)
        self.assertIn("RUNTIME_STATE=UNKNOWN_AFTER_RUNNER", SOURCE)

    def test_component_inventory_explicit_and_nonempty(self):
        self.assertEqual(len(self.component_paths()), 28)
        self.assertIn("downloads/STOP_AI_COCKPIT_V10.ps1", self.component_paths())
        self.assertIn("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", self.component_paths())
        self.assertIn("scripts/ai_brain_observer.py", self.component_paths())

    def test_candidate_manifest_has_exactly_17_expected_source_blobs(self):
        manifest = json.loads(
            (ROOT / "downloads" / "V10_RELEASE_BUNDLE_MANIFEST.json").read_text(
                encoding="utf-8-sig"
            )
        )
        self.assertEqual(manifest["schema"], "v10_release_candidate_blobs_v1")
        self.assertIs(manifest["real_submit_allowed"], False)
        self.assertEqual(
            {item["path"] for item in manifest["files"]},
            set(self.component_paths())
        )
        self.assertEqual(len(manifest["files"]), 28)
        self.assertIn("V10_RELEASE_SOURCE_BLOB_MISMATCH", SOURCE)
        self.assertIn("V10_RELEASE_MANIFEST_REAL_SUBMIT_MUST_BE_FALSE", SOURCE)
        self.assertLess(
            SOURCE.index("V10_RELEASE_SOURCE_BLOBS_MATCH=28"),
            SOURCE.index("V10_REVIEWED_RUNNER_HANDOFF=1")
        )

    @staticmethod
    def component_paths():
        match = re.search(r"\$required = @\((.*?)\)\s*foreach", SOURCE, re.S)
        if match is None:
            raise AssertionError("missing release file inventory")
        return re.findall(r'"([^"]+)"', match.group(1))


@unittest.skipUnless(
    sys.platform == "win32" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "Windows GitHub Actions disposable fixture only"
)
class WindowsGuardedOneClickFixture(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None or shutil.which("powershell.exe") is None:
            self.skipTest("Git or Windows PowerShell unavailable")
        self.temp = tempfile.TemporaryDirectory(
            prefix="v10-guarded-", dir=os.environ["RUNNER_TEMP"]
        )
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "synthetic_source"
        (self.repo / "downloads").mkdir(parents=True)
        self.git("init", "-b", "reviewed-v10")
        for file in (GUARD, VERIFY, CMD):
            shutil.copy2(file, self.repo / "downloads" / file.name)
        (self.repo / ".gitignore").write_text(
            "downloads/V10_APPROVED_SOURCE.json\n", encoding="utf-8"
        )
        self.git("add", ".")
        self.commit("initial reviewed scripts")
        self.pin = self.repo / "downloads" / "V10_APPROVED_SOURCE.json"
        self.write_pin()

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, capture_output=True,
                              text=True, check=True, timeout=20)

    def commit(self, message):
        self.git("-c", "user.name=synthetic",
                 "-c", "user.email=synthetic@example.invalid",
                 "commit", "-m", message)
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(len(self.sha), 40)

    def write_pin(self, **kwargs):
        cfg = {"schema": "v10_approved_source_v1", "branch": "reviewed-v10",
               "commit_sha": self.sha, "real_submit_allowed": False}
        cfg.update(kwargs)
        self.pin.write_text(json.dumps(cfg), encoding="utf-8")

    def invoke(self, *flags):
        before = self.git("rev-parse", "HEAD").stdout.strip()
        cmd = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-File",
               str(self.repo / "downloads" / GUARD.name),
               "-RepoRoot", str(self.repo), "-ApprovalFile", str(self.pin), *flags]
        result = subprocess.run(cmd, input="\n", capture_output=True,
                                text=True, timeout=55)
        self.assertEqual(before, self.git("rev-parse", "HEAD").stdout.strip(),
                         "V10 guard altered repo HEAD")
        return result.returncode, result.stdout + "\n" + result.stderr

    def install_dummy_release_bundle(self):
        for name in V10GuardedLaunchContract.component_paths():
            target = self.repo / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if name == "downloads/RUN_AI_COCKPIT_V10.ps1":
                # A harmless reviewed fake runner. This is NOT copied to
                # the actual app checkout and never invokes Excel/MS2.
                target.write_text(
                    "param([string]$RepoRoot='', [string]$ApprovalFile='')\n"
                    "# V10_MUTATING_START_REQUIRES_APPROVAL_FILE\n"
                    "# PINNED_SHA_MUST_BE_FULL_40_HEX\n"
                    "# V10_WORKTREE_NOT_CLEAN\n"
                    "# REAL_SUBMIT_ALLOWED=0\n"
                    "if (-not (Test-Path -LiteralPath $ApprovalFile)) { exit 4 }\n"
                    'Write-Output "SYNTHETIC_REVIEWED_RUN_CALLED=1"\n',
                    encoding="utf-8")
            else:
                target.write_text("SYNTHETIC_ONLY_NO_RUNTIME\n", encoding="utf-8")
        self.refresh_manifest()
        self.git("add", "-A")
        self.commit("bounded no-process fake V10 release components")
        self.write_pin()

    def refresh_manifest(self):
        files = []
        for relative in V10GuardedLaunchContract.component_paths():
            blob = self.git("hash-object", "--", relative).stdout.strip()
            self.assertEqual(len(blob), 40)
            files.append({"path": relative, "git_blob_sha": blob})
        self.manifest = self.repo / "downloads" / "V10_RELEASE_BUNDLE_MANIFEST.json"
        data = {"schema": "v10_release_candidate_blobs_v1",
                "candidate_source_commit": "e906dedc45448ca20428a7ca1afa1126eaeeedaa",
                "real_submit_allowed": False,
                "files": files}
        self.manifest.write_text(json.dumps(data, indent=2) + "\n",
                                 encoding="utf-8")

    def assert_block(self, code, *flags):
        rc, output = self.invoke(*flags)
        self.assertNotEqual(rc, 0, output[-3200:])
        self.assertIn("V10_START=BLOCKED", output)
        self.assertIn(code, output)
        self.assertNotIn("SYNTHETIC_REVIEWED_RUN_CALLED=1", output)
        self.assertIn("CONTROLLER_STARTED=0", output)
        self.assertIn("RUNTIME_FILES_TOUCHED=0", output)

    def test_correct_source_but_absent_runtime_never_launches(self):
        self.assert_block("V10_RELEASE_COMPONENT_MISSING")

    def test_unpinned_source_refused_before_component_checks(self):
        self.pin.unlink()
        self.assert_block("V10_SOURCE_ADMISSION_FAILED")
 
    def test_different_sha_refused_before_component_checks(self):
        self.write_pin(commit_sha="0" * 40)
        self.assert_block("V10_SOURCE_ADMISSION_FAILED")

    def test_dirty_checkout_refused_before_component_checks(self):
        (self.repo / "unreviewed.ps1").write_text("malicious\n", encoding="utf-8")
        self.assert_block("V10_SOURCE_ADMISSION_FAILED")

    def test_verification_only_passes_bundle_without_running_worker(self):
        self.install_dummy_release_bundle()
        rc, output = self.invoke("-VerifyOnly")
        self.assertEqual(rc, 0, output[-3200:])
        self.assertIn("V10_READONLY_SOURCE=PASS", output)
        self.assertIn("V10_RELEASE_COMPONENTS_PRESENT=1", output)
        self.assertIn("V10_START_PREFLIGHT=PASS_NO_RUNTIME", output)
        self.assertNotIn("SYNTHETIC_REVIEWED_RUN_CALLED=1", output)
        self.assertIn("CONTROLLER_STARTED=0", output)

    def test_clean_pinned_bundle_handoffs_to_synthetic_only(self):
        self.install_dummy_release_bundle()
        rc, output = self.invoke()
        self.assertEqual(rc, 0, output[-3200:])
        self.assertIn("V10_REVIEWED_RUNNER_HANDOFF=1", output)
        self.assertIn("SYNTHETIC_REVIEWED_RUN_CALLED=1", output)
        self.assertIn("REAL_SUBMIT_ALLOWED=0", output)

    def test_missing_runner_contract_prevents_handoff(self):
        self.install_dummy_release_bundle()
        runner = self.repo / "downloads" / "RUN_AI_COCKPIT_V10.ps1"
        runner.write_text(
            "param([string]$RepoRoot='', [string]$ApprovalFile='')\n"
            'Write-Output "SYNTHETIC_REVIEWED_RUN_CALLED=1"\n', encoding="utf-8")
        self.refresh_manifest()
        self.git("add", "-A")
        self.commit("fake unreviewed runner missing admission contracts")
        self.write_pin()
        self.assert_block("V10_RUNNER_APPROVAL_CONTRACT_MISSING")

    def test_missing_tracked_manifest_refuses_handoff(self):
        self.install_dummy_release_bundle()
        self.manifest.unlink()
        self.git("add", "-A")
        self.commit("synthetic manifest absent")
        self.write_pin()
        self.assert_block("V10_RELEASE_MANIFEST_MISSING")

    def test_manifest_allowing_real_orders_refuses_handoff(self):
        self.install_dummy_release_bundle()
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["real_submit_allowed"] = True
        self.manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("synthetic unsafe manifest must fail")
        self.write_pin()
        self.assert_block("V10_RELEASE_MANIFEST_REAL_SUBMIT_MUST_BE_FALSE")

    def test_commit_matching_pin_but_runtime_blob_mismatch_refused(self):
        self.install_dummy_release_bundle()
        asset = self.repo / "ms2_live" / "MS2_RSS_100_Collector.ps1"
        asset.write_text("DIFFERENT REVIEWED COMMIT SOURCE\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("synthetic collector changed while candidate blob pin stays old")
        self.write_pin()
        self.assert_block("V10_RELEASE_SOURCE_BLOB_MISMATCH")

    def test_extra_bundle_manifest_entry_refuses_handoff(self):
        self.install_dummy_release_bundle()
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["files"].append(dict(data["files"][0]))
        self.manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("synthetic duplicate pin added")
        self.write_pin()
        self.assert_block("V10_RELEASE_MANIFEST_FILE_COUNT_MISMATCH")

    def test_dirty_controller_file_prevents_handoff(self):
        self.install_dummy_release_bundle()
        controller = self.repo / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1"
        controller.write_text("DIRTY UNREVIEWED CONTROLLER\n", encoding="utf-8")
        self.assert_block("V10_SOURCE_ADMISSION_FAILED")


if __name__ == "__main__":
    unittest.main()
