import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "downloads" / "SYNC_100OKU_MASTER_SPEC.ps1"
REGISTER = ROOT / "downloads" / "REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
SAFE = ROOT / "downloads" / "SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
WRAPPER = ROOT / "downloads" / "UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1"
MANIFEST = ROOT / "docs" / "100oku" / "SYNC_MANIFEST.json"
PWSH_CANDIDATES = (
    Path("/tmp/pwsh/pwsh"),
    Path("/usr/bin/pwsh"),
    Path("/usr/local/bin/pwsh"),
)


def pwsh_path():
    for candidate in PWSH_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


class MasterSpecSyncBridgeTests(unittest.TestCase):
    def test_scripts_stay_ascii_and_fail_closed(self):
        for path in (SYNC, REGISTER, SAFE, WRAPPER):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            raw.decode("ascii")
        sync = SYNC.read_text(encoding="ascii")
        register = REGISTER.read_text(encoding="ascii")
        wrapper = WRAPPER.read_text(encoding="ascii")
        for token in (
            "MASTER_SPEC_SYNC=FAIL",
            'return "EMPTY"',
            'return "MISSING"',
            "REASON=HASH_MISMATCH",
            "REASON=ARCHIVE_HASH_MISMATCH",
            "REASON=DESTINATION_DRIVE_MISSING",
            "cloud_agent_wrote_destination = $false",
            "CLOUD_AGENT_WROTE_D_DRIVE=0",
            "ARCHIVE=NONE_FIRST_SYNC",
            "SHA256",
            "LAST_SYNC.json",
        ):
            self.assertIn(token, sync)
        self.assertNotIn("real_submit_allowed = True", sync)
        self.assertNotIn("real_submit_allowed = True", register)
        self.assertNotIn("Stop-Process", sync)
        self.assertNotIn("Stop-Process", register)
        self.assertNotIn("Stop-Process", wrapper)
        self.assertNotIn("RssOrder", sync)
        self.assertNotIn("RssOrder", wrapper)
        self.assertNotIn("real_submit_allowed = True", wrapper)
        safe = SAFE.read_text(encoding="ascii")
        self.assertNotIn("Stop-Process", safe)
        self.assertNotIn("RssOrder", safe)
        self.assertNotIn("real_submit_allowed = True", safe)
        self.assertNotIn("schtasks.exe", safe)
        self.assertNotIn("OWNER_REGISTER_INNER", register)
        self.assertIn("TASK_TIME=16:45", register)
        self.assertIn("TASK_REGISTER=NOT_RUN", register)
        self.assertIn("REASON=PATH_HAS_SPACE_OR_QUOTE", register)
        self.assertIn('-File " + $wrapper + " -RepoRoot " + $root', register)
        self.assertNotIn('-File "\'', register)
        self.assertLess(register.index("TASK_REGISTER=NOT_RUN"), register.index("schtasks.exe"))
        self.assertLess(register.index("Invoke-RegisterGuard $root"), register.index("schtasks.exe"))
        guard = register.split("function Invoke-RegisterGuard(", 1)[1].split("function Invoke-RegisterCommit", 1)[0]
        self.assertNotIn("reset --hard", guard)
        self.assertLess(guard.index("REGISTER_ABORT=WORKTREE_DIRTY"), guard.index('checkout", "--detach"'))
        self.assertLess(guard.index("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"), guard.index('checkout", "--detach"'))
        self.assertLess(guard.index("REGISTER_ABORT=HISTORY_DIVERGED"), guard.index('checkout", "--detach"'))
        self.assertLess(guard.index('"--porcelain"'), guard.index('"merge-base"'))
        for token in (
            'Write-Fail "FETCH_FAILED"',
            'return "DIRTY"',
            'Write-Fail "LOCAL_COMMITS_NOT_ON_REMOTE"',
            'Write-Fail "HISTORY_DIVERGED"',
            'return "MISSING"',
            'Write-Fail "DESTINATION_HASH_MISMATCH"',
            "checkout", "--detach",
            "DRY_RUN_MOVE=NOT_APPLIED",
            "source_commit",
            "destination_sha256",
        ):
            self.assertIn(token, wrapper)
        update_body = wrapper.split("function Invoke-UpdateAndSync", 1)[1].split("function New-FixtureFiles", 1)[0]
        self.assertNotIn("reset --hard", update_body)

    def test_manifest_lists_the_working_copy(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["destination"], r"D:\100億PROJECT\MASTER_SPEC")
        self.assertIs(manifest["cloud_agent_can_write_destination"], False)
        self.assertEqual(manifest["remote_branch"], "cursor/master-spec-fetch-sync-d483")
        required = manifest["required"]
        self.assertEqual(
            required,
            [
                "docs/100oku/100億PROJECT_MASTER_SPEC.md",
                "docs/100oku/CURRENT_STATUS.md",
                "docs/100oku/CHANGELOG.md",
                "docs/100oku/HANDOVER.md",
            ],
        )
        for relative in required:
            file = ROOT / relative
            self.assertGreater(file.stat().st_size, 0, relative)
        handover = (ROOT / "docs/100oku/HANDOVER.md").read_text(encoding="utf-8")
        self.assertIn("cloud_agent_wrote_destination", handover)
        self.assertIn("D:\\100億PROJECT\\MASTER_SPEC", handover)

    def test_dry_run_and_self_test_do_not_write_d(self):
        pwsh = pwsh_path()
        if pwsh is None:
            self.skipTest("pwsh is not installed")
        dry = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(SYNC), "-RepoRoot", str(ROOT), "-DryRun"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("MASTER_SPEC_SYNC=DRY_RUN", dry.stdout)
        self.assertIn("CLOUD_AGENT_WROTE_D_DRIVE=0", dry.stdout)
        self.assertIn("DESTINATION_WRITTEN=0", dry.stdout)
        self.assertIn("DESTINATION=D:\\100億PROJECT\\MASTER_SPEC", dry.stdout)
        self.assertIn("100億PROJECT_MASTER_SPEC.docx", dry.stdout)
        self.assertNotIn("MASTER_SPEC_SYNC=PASS", dry.stdout)
        self.assertFalse((ROOT / "LAST_SYNC.json").exists())
        syntax = subprocess.run(
            [
                str(pwsh),
                "-NoProfile",
                "-Command",
                "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$e); if ($e) { $e | ForEach-Object { $_.ToString() }; exit 1 } else { 'PARSE_ERRORS=0' }"
                % str(SYNC),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stdout + syntax.stderr)
        self.assertIn("PARSE_ERRORS=0", syntax.stdout)
        selftest = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(SYNC), "-RepoRoot", str(ROOT), "-SelfTest"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(selftest.returncode, 0, selftest.stdout + selftest.stderr)
        self.assertIn("MASTER_SPEC_SYNC_SELFTEST=PASS", selftest.stdout)
        self.assertIn("SELFTEST_WROTE_D_DRIVE=0", selftest.stdout)
        self.assertIn("CLOUD_AGENT_WROTE_D_DRIVE=0", selftest.stdout)
        register = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(REGISTER), "-RepoRoot", str(ROOT)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(register.returncode, 0, register.stderr)
        self.assertIn("TASK_REGISTER=NOT_RUN", register.stdout)
        self.assertIn("TASK_TIME=16:45", register.stdout)
        self.assertIn("CLOUD_AGENT_WROTE_D_DRIVE=0", register.stdout)
        self.assertIn("UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1", register.stdout)
        self.assertNotIn("/SYNC_100OKU_MASTER_SPEC.ps1", register.stdout)
        wrapped = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(WRAPPER), "-SelfTest"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(wrapped.returncode, 0, wrapped.stdout + wrapped.stderr)
        for token in (
            "CASE=DIRTY",
            "CASE=FETCH_FAIL",
            "CASE=LOCAL_COMMITS",
            "CASE=DIVERGED",
            "CASE=DRY_RUN",
            "CASE=FAST_FORWARD",
            "CASE=UNCHANGED",
            "CASE=MISSING",
            "UPDATE_SYNC_SELFTEST=PASS",
            "SELFTEST_WROTE_D_DRIVE=0",
            "DESTINATION_WRITTEN=0",
            "SOURCE_COMMIT=",
        ):
            self.assertIn(token, wrapped.stdout, token)
        guard = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(REGISTER), "-GuardSelfTest"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(guard.returncode, 0, guard.stdout + guard.stderr)
        for token in (
            "REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE",
            "REGISTER_ABORT=WORKTREE_DIRTY",
            "REGISTER_ABORT=FETCH_FAILED",
            "REGISTER_ABORT=HISTORY_DIVERGED",
            "CASE=FAST_FORWARD",
            "CASE=UNCHANGED",
            "REGISTER_GUARD_SELFTEST=PASS",
            "SELFTEST_WROTE_D_DRIVE=0",
        ):
            self.assertIn(token, guard.stdout, token)
        self.assertNotIn("TASK_REGISTER=PASS", guard.stdout)

    def test_safe_register_file_parses_and_self_tests(self):
        pwsh = pwsh_path()
        if pwsh is None:
            self.skipTest("pwsh is not installed")
        text = SAFE.read_text(encoding="ascii")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn(" -Command", code)
        for banned in ("&&", "||", "??", "?.", "-Parallel"):
            self.assertNotIn(banned, text, banned)
        self.assertLess(text.index("REGISTER_ABORT=WORKTREE_DIRTY"), text.index("checkout"))
        self.assertLess(text.index("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"), text.index("checkout"))
        self.assertLess(text.index("REGISTER_ABORT=HISTORY_DIVERGED"), text.index("checkout"))
        check = text.split("function Invoke-SafeRegisterCheck(", 1)[1].split("function Invoke-RegisterScript", 1)[0]
        self.assertNotIn("reset --hard", check)
        self.assertIn(
            "$check = Invoke-SafeRegisterCheck $root $RemoteBranch\n"
            "if ($check -ne 0) { exit $check }\n"
            "$registered = Invoke-RegisterScript $root $RemoteBranch",
            text,
        )
        marker = "# OWNER_FILE_COMMAND\n# "
        start = text.index(marker) + len(marker)
        owner = text[start:].splitlines()[0].strip()
        self.assertTrue(owner.startswith("powershell.exe -NoProfile -ExecutionPolicy Bypass -File "))
        self.assertIn("SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1", owner)
        self.assertIn('-RepoRoot "', owner)
        self.assertNotIn("-Command", owner)
        self.assertNotIn("'", owner)
        self.assertEqual(owner.count('"'), 4)
        parsed = subprocess.run(
            [
                str(pwsh),
                "-NoProfile",
                "-Command",
                "$e=$null; $t=$null; "
                "[void][System.Management.Automation.Language.Parser]::ParseFile('"
                + str(SAFE)
                + "', [ref]$t, [ref]$e); "
                "if ($e -and $e.Count -gt 0) { $e | ForEach-Object { $_.ToString() }; exit 1 }; "
                "Write-Output PARSE=PASS",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
        self.assertIn("PARSE=PASS", parsed.stdout)
        ran = subprocess.run(
            [str(pwsh), "-NoProfile", "-File", str(SAFE), "-SelfTest"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        for token in (
            "REGISTER_ABORT=WORKTREE_DIRTY",
            "REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE",
            "REGISTER_ABORT=HISTORY_DIVERGED",
            "REGISTER_ABORT=FETCH_FAILED",
            "CASE=DIRTY",
            "CASE=LOCAL_ONLY",
            "CASE=DIVERGED",
            "CASE=FETCH_FAILED",
            "CASE=FAST_FORWARD",
            "CASE=UNCHANGED",
            "REGISTER_CALLED=0",
            "REGISTER_CALLED=1",
            "TASK_REGISTER=PASS",
            "UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1",
            "SAFE_REGISTER_SELFTEST=PASS",
            "SELFTEST_WROTE_D_DRIVE=0",
        ):
            self.assertIn(token, ran.stdout, token)
        dirty_at = ran.stdout.index("CASE=DIRTY")
        forward_at = ran.stdout.index("CASE=FAST_FORWARD")
        self.assertLess(dirty_at, forward_at)
        self.assertLess(ran.stdout.index("CASE=LOCAL_ONLY"), forward_at)
        self.assertLess(ran.stdout.index("CASE=DIVERGED"), forward_at)
        self.assertLess(ran.stdout.index("CASE=FETCH_FAILED"), forward_at)
        self.assertNotIn("SAFE_REGISTER_SELFTEST=FAIL", ran.stdout)
