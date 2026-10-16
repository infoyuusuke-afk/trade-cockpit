"""P0-19: disposal-only tests for the backup-only V10 cutover preparer.

Never deploys, stops a worker, modifies OWNER files or handles account CSV.
All mutations are inside GitHub-hosted Windows RUNNER_TEMP.
"""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "downloads" / "PREPARE_V10_SAFE_CUTOVER_V1.ps1"

@unittest.skipUnless(
    os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true"
    and os.environ.get("RUNNER_OS") == "Windows",
    "synthetic Windows Actions only",
)
class SafeCutoverBackup(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v10-cutover-", dir=os.environ["RUNNER_TEMP"])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        self.desktop = self.root / "desktop"
        self.backups = self.root / "snapshots"
        (self.repo / "downloads").mkdir(parents=True)
        self.state.mkdir()
        self.desktop.mkdir()
        self.orig = {}
        files = {
            "state/START_AI_COCKPIT.ps1": b"Write-Output 'old entry'\n",
            "state/AI_COCKPIT_START_DEBUG.cmd": b"@echo off\npowershell.exe old\n",
            "repo/downloads/RUN_AI_COCKPIT_V10.ps1": b"# Old V10 local runner\n",
            "repo/downloads/STOP_AI_COCKPIT_V10.ps1": b"# Old V10 local stop\n",
            "repo/downloads/AI_COCKPIT_CONTROLLER_V10.ps1": b"# Controller\n",
            "repo/downloads/AI_COCKPIT_GATEWAY_V10.ps1": b"# Gateway\n",
            "desktop/AI Cockpit START.lnk": b"disposable-shortcut-only",
            "desktop/AI Cockpit START.cmd": b"@echo off\nold-debug",
            "desktop/AI Cockpit STOP.cmd": b"@echo off\nold-stop",
        }
        for key, data in files.items():
            target = self.root / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.orig[key] = data
        # Must never enter manifest/backups even if living beside tracked files.
        (self.repo / "account_secret.csv").write_text("account,private\n1,yes", encoding="utf-8")
        (self.state / "broker_credentials.txt").write_text("SENSITIVE", encoding="utf-8")
        self.git("init", "-b", "old")
        self.git("add", "downloads")
        self.git("-c", "user.email=test@example.invalid", "-c", "user.name=ci",
                 "commit", "-m", "synthetic old local installation")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args):
        p = subprocess.run(["git", *args], cwd=self.repo, capture_output=True,
                           text=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def invoke_prepare(self, mode="Plan", sha=None, branch="old", backup=None, state=None):
        args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                "-Mode", mode, "-RepoRoot", str(self.repo),
                "-StateRoot", str(state or self.state), "-DesktopRoots", str(self.desktop),
                "-ExpectedBranch", branch, "-ExpectedSha", sha or self.sha,
                "-BackupRoot", str(backup or self.backups)]
        return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=35)

    def invoke_with_multiple_desktops(self, roots, mode="Plan"):
        # -File cannot bind PowerShell array arguments from a native process;
        # use WindowsPowerShell's UTF-16LE EncodedCommand in synthetic CI.
        def q(value):
            return "'" + str(value).replace("'", "''") + "'"
        list_arg = ",".join(q(p) for p in roots)
        command = (
            f"& {q(SCRIPT)} -Mode {mode} -RepoRoot {q(self.repo)} "
            f"-StateRoot {q(self.state)} -DesktopRoots @({list_arg}) "
            f"-ExpectedBranch 'old' -ExpectedSha {q(self.sha)} "
            f"-BackupRoot {q(self.backups)}"
        )
        token = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", token], capture_output=True, text=True,
            errors="replace", timeout=35
        )

    def assert_no_live_changes(self):
        for key, original in self.orig.items():
            self.assertEqual((self.root / key).read_bytes(), original, key)
        self.assertEqual((self.repo / "account_secret.csv").read_text(encoding="utf-8"),
                         "account,private\n1,yes")

    def test_plan_has_zero_write_side_effects(self):
        result = self.invoke_prepare()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SOURCE_PIN_MATCH=true", result.stdout)
        self.assertIn("CUTOVER_PLAN=READ_ONLY", result.stdout)
        self.assertFalse(self.backups.exists())
        self.assert_no_live_changes()

    def test_backup_only_snapshot_integrity_and_manifest(self):
        result = self.invoke_prepare(mode="BackupOnly")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BACKUP_RESULT=VERIFIED_LOCAL_ONLY", result.stdout)
        self.assertIn("CUTOVER_APPLIED=false", result.stdout)
        snapshots = list(self.backups.iterdir())
        self.assertEqual(len(snapshots), 1)
        manifest = json.loads((snapshots[0] / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], "v10_cutover_backup_v1")
        self.assertFalse(manifest["real_submit_allowed"])
        self.assertTrue(manifest["source_pin_match"])
        self.assertEqual(len(manifest["files"]), len(self.orig))
        for receipt in manifest["files"]:
            destination = snapshots[0] / receipt["name"]
            self.assertTrue(destination.is_file())
            digest = hashlib.sha256(destination.read_bytes()).hexdigest().upper()
            self.assertEqual(receipt["sha256"], digest)
        self.assertFalse(list(snapshots[0].rglob("*.csv")))
        self.assertFalse(list(snapshots[0].rglob("*credentials*")))
        self.assert_no_live_changes()

    def test_stale_local_git_still_permits_old_state_backup(self):
        result = self.invoke_prepare(mode="BackupOnly", sha="0" * 40, branch="future-uninstalled")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SOURCE_PIN_MATCH=false", result.stdout)
        snapshot = next(self.backups.iterdir())
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["source_pin_match"])
        self.assert_no_live_changes()

    def test_missing_debug_launcher_refuses_backup(self):
        (self.state / "AI_COCKPIT_START_DEBUG.cmd").unlink()
        result = self.invoke_prepare(mode="BackupOnly")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("CUTOVER_PLAN=BLOCKED", result.stdout)
        self.assertIn("BLOCK_STAGE=BACKUP_PRECONDITIONS", result.stdout)
        self.assertIn("BLOCK_REASON=BACKUP_INPUT_INCOMPLETE", result.stdout)
        self.assertFalse(self.backups.exists())

    def test_missing_stop_cmd_refuses_backup(self):
        (self.desktop / "AI Cockpit STOP.cmd").unlink()
        result = self.invoke_prepare(mode="BackupOnly")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.backups.exists())

    def test_missing_shortcut_refuses_backup(self):
        (self.desktop / "AI Cockpit START.lnk").unlink()
        result = self.invoke_prepare(mode="BackupOnly")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.backups.exists())

    def test_destination_inside_repo_refused(self):
        result = self.invoke_prepare(mode="BackupOnly", backup=self.repo / "backups")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((self.repo / "backups").exists())
        self.assertIn("BLOCK_STAGE=BACKUP_TARGET", result.stdout)
        self.assertIn("BLOCK_REASON=BACKUP_ROOT_INSIDE_SOURCE", result.stdout)

    def test_bad_pin_format_refused(self):
        result = self.invoke_prepare(mode="BackupOnly", sha="not-full-sha")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(self.backups.exists())
        self.assertIn("BLOCK_STAGE=VALIDATE_ARGS", result.stdout)
        self.assertIn("BLOCK_REASON=BAD_PIN", result.stdout)

    def test_plan_without_debug_is_observation_not_successful_backup(self):
        (self.state / "AI_COCKPIT_START_DEBUG.cmd").unlink()
        result = self.invoke_prepare(mode="Plan")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ESSENTIAL_MISSING=1", result.stdout)
        self.assertFalse(self.backups.exists())

    def test_missing_root_reports_safe_reason_not_private_path(self):
        missing = self.root / "missing-state-folder"
        result = self.invoke_prepare(state=missing)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCK_STAGE=VALIDATE_ROOTS", result.stdout)
        self.assertIn("BLOCK_REASON=PATH_NOT_FOUND", result.stdout)
        self.assertNotIn(str(self.root), result.stdout)
        self.assertFalse(self.backups.exists())

    def test_too_many_candidate_files_reports_discovery_block(self):
        for i in range(41):
            (self.desktop / f"AI_EXTRA_{i:02d}.cmd").write_text(
                "@echo off", encoding="ascii")
        result = self.invoke_prepare()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("BLOCK_STAGE=DISCOVER_CANDIDATES", result.stdout)
        self.assertIn("BLOCK_REASON=TOO_MANY_DESKTOP_ENTRIES", result.stdout)
        self.assertNotIn(str(self.root), result.stdout)
        self.assertFalse(self.backups.exists())

    def test_unrelated_desktop_files_excluded_from_plan_and_snapshot(self):
        # Desktop OneDrive may contain many unrelated files; only AI launcher
        # CMD/LNK entries should be enumerated or copied.
        (self.desktop / "ZZ_UNRELATED_LARGE_FILE.txt").write_bytes(b"x" * 2000000)
        (self.desktop / "Photo Archive.csv").write_text(
            "private,should_not_be_read", encoding="utf-8")
        for i in range(65):
            (self.desktop / f"Other_{i:03d}.txt").write_text(
                "unrelated", encoding="ascii")
        result = self.invoke_prepare(mode="Plan")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DESKTOP_CMD_COUNT=2", result.stdout)
        self.assertIn("DESKTOP_LNK_COUNT=1", result.stdout)
        self.assertFalse(self.backups.exists())
        result = self.invoke_prepare(mode="BackupOnly")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        snapshot = next(self.backups.iterdir())
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["files"]), len(self.orig))
        self.assertFalse(list(snapshot.rglob("*.csv")))
        self.assertFalse(list(snapshot.rglob("ZZ_*")))
        self.assertFalse(list(snapshot.rglob("Other_*")))
        self.assert_no_live_changes()

    def test_filter_scanning_and_indexed_fail_closed_diagnostics_contract(self):
        source = SCRIPT.read_text(encoding="ascii")
        self.assertIn('-Filter "AI*.cmd" -ErrorAction Stop', source)
        self.assertIn('-Filter "AI*.lnk" -ErrorAction Stop', source)
        self.assertNotIn("Get-ChildItem -LiteralPath $d -File -ErrorAction Stop", source)
        self.assertIn("BLOCK_DESKTOP_INDEX=", source)
        self.assertIn("BLOCK_DISCOVERY_ACTION=", source)
        self.assertIn('if ($stage -eq "DISCOVER_CANDIDATES")', source)
        self.assertIn('Write-Output ("BLOCK_REASON="+$reason)', source)
        self.assertIn('BACKUP_RESULT=VERIFIED_PARTIAL_LOCAL_ONLY', source)
        self.assertIn('CUTOVER_ELIGIBLE=false', source)

    def test_missing_optional_desktop_is_reported_not_silently_ignored(self):
        missing = self.root / "missing-public-desktop"
        plan = self.invoke_with_multiple_desktops([self.desktop, missing])
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        self.assertIn("CUTOVER_PLAN=READ_ONLY_PARTIAL", plan.stdout)
        self.assertIn("UNVERIFIED_DESKTOP_COUNT=1", plan.stdout)
        self.assertIn("UNVERIFIED_DESKTOP_INDEX=2", plan.stdout)
        self.assertIn("UNVERIFIED_DESKTOP_ACTION=DESKTOP_EXISTS", plan.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false", plan.stdout)
        self.assertNotIn(str(missing), plan.stdout)
        self.assertFalse(self.backups.exists())

        result = self.invoke_with_multiple_desktops(
            [self.desktop, missing], mode="BackupOnly")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BACKUP_RESULT=VERIFIED_PARTIAL_LOCAL_ONLY", result.stdout)
        snapshot = next(self.backups.iterdir())
        manifest = json.loads(
            (snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["desktop_inventory_complete"])
        self.assertFalse(manifest["cutover_eligible"])
        self.assertEqual(manifest["unverified_desktop_indexes"], [2])
        self.assertEqual(len(manifest["files"]), len(self.orig))
        self.assert_no_live_changes()

    def test_third_desktop_junction_is_quarantined_without_following(self):
        second = self.root / "second-desktop"
        second.mkdir()
        target = self.root / "junction-target"
        target.mkdir()
        (target / "AI_SECRET.cmd").write_text("do not read", encoding="utf-8")
        junction = self.root / "third-desktop-junction"
        create = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(junction), str(target)],
            capture_output=True, text=True, errors="replace", timeout=15
        )
        if create.returncode != 0:
            self.skipTest("Windows fixture cannot create an NTFS junction")
        plan = self.invoke_with_multiple_desktops(
            [self.desktop, second, junction])
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        self.assertIn("CUTOVER_PLAN=READ_ONLY_PARTIAL", plan.stdout)
        self.assertIn("UNVERIFIED_DESKTOP_INDEX=3", plan.stdout)
        self.assertIn("UNVERIFIED_DESKTOP_ACTION=DESKTOP_ATTRIBUTES", plan.stdout)
        self.assertIn("CUTOVER_ELIGIBLE=false", plan.stdout)
        self.assertNotIn(str(junction), plan.stdout)
        backup = self.invoke_with_multiple_desktops(
            [self.desktop, second, junction], mode="BackupOnly")
        self.assertEqual(backup.returncode, 0, backup.stdout + backup.stderr)
        self.assertIn("BACKUP_RESULT=VERIFIED_PARTIAL_LOCAL_ONLY", backup.stdout)
        snapshot = next(self.backups.iterdir())
        self.assertFalse(list(snapshot.rglob("AI_SECRET.cmd")))
        manifest = json.loads(
            (snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unverified_desktop_indexes"], [3])
        self.assertFalse(manifest["desktop_inventory_complete"])
        self.assertFalse(manifest["cutover_eligible"])
        self.assert_no_live_changes()

    def test_selftest_always_plan_only(self):
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                 "-File", str(SCRIPT), "-SelfTest"],
                                capture_output=True, text=True, errors="replace", timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: P0_19_PARSE_AND_PLAN_ENTRY", result.stdout)

if __name__ == "__main__":
    unittest.main()
