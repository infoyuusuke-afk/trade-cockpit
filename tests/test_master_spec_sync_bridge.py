import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "downloads" / "SYNC_100OKU_MASTER_SPEC.ps1"
REGISTER = ROOT / "downloads" / "REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
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
        for path in (SYNC, REGISTER, WRAPPER):
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

    def test_owner_register_line_checks_before_checkout(self):
        pwsh = pwsh_path()
        if pwsh is None:
            self.skipTest("pwsh is not installed")
        text = REGISTER.read_text(encoding="ascii")
        begin = text.index("# OWNER_REGISTER_INNER_BEGIN\n")
        end = text.index("# OWNER_REGISTER_INNER_END\n")
        body = text[begin:end].splitlines()[1:]
        self.assertEqual(len(body), 1)
        self.assertTrue(body[0].startswith("# "))
        inner = body[0][2:]
        self.assertNotIn("'", inner)
        prefix, suffix = inner.split("& powershell.exe", 1)
        self.assertIn("-Register -RepoRoot $r", suffix)
        self.assertIn("REGISTER_100OKU_MASTER_SPEC_TASK.ps1", suffix)
        self.assertLess(prefix.index("REGISTER_ABORT=WORKTREE_DIRTY"), prefix.index("checkout --detach"))
        self.assertLess(prefix.index("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"), prefix.index("checkout --detach"))
        self.assertLess(prefix.index("REGISTER_ABORT=HISTORY_DIVERGED"), prefix.index("checkout --detach"))
        self.assertLess(prefix.index("--porcelain"), prefix.index("merge-base"))
        self.assertLess(prefix.index("merge-base"), prefix.index("checkout --detach"))
        root_token = r"C:\Users\yusuk\code\trade-cockpit-100oku-master-sync"
        branch = "cursor/master-spec-fetch-sync-d483"

        def git(*args, cwd=None):
            subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

        def build():
            import tempfile
            from pathlib import Path as FsPath
            temp = FsPath(tempfile.mkdtemp(prefix="owner-register-"))
            bare = temp / "remote.git"
            seed = temp / "seed"
            clone = temp / "clone"
            dedicated = temp / "dedicated"
            git("init", "-q", "--bare", str(bare))
            git("init", "-q", str(seed))
            (seed / "note.txt").write_text("base\n", encoding="ascii")
            git("-C", str(seed), "add", "--", ".")
            git("-C", str(seed), "-c", "user.email=sync-selftest@example.com", "-c", "user.name=sync-selftest", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
            base = subprocess.check_output(["git", "-C", str(seed), "rev-parse", "HEAD"], text=True).strip()
            git("-C", str(seed), "branch", "-M", branch)
            git("-C", str(seed), "remote", "add", "origin", str(bare))
            git("-C", str(seed), "push", "-q", "origin", "HEAD:refs/heads/" + branch)
            git("--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/" + branch)
            git("clone", "-q", "-b", branch, str(bare), str(clone))
            git("-C", str(clone), "worktree", "add", "--detach", str(dedicated), base)
            return temp, seed, dedicated, base

        def invoke(dedicated, script):
            proc = subprocess.run([str(pwsh), "-NoProfile", "-Command", script], check=False, capture_output=True, text=True)
            head = subprocess.check_output(["git", "-C", str(dedicated), "rev-parse", "HEAD"], text=True).strip()
            return proc, head

        import shutil
        temp, seed, dedicated, base = build()
        try:
            (dedicated / "extra.txt").write_text("dirty\n", encoding="ascii")
            (seed / "note.txt").write_text("base\nforward\n", encoding="ascii")
            git("-C", str(seed), "add", "--", ".")
            git("-C", str(seed), "-c", "user.email=sync-selftest@example.com", "-c", "user.name=sync-selftest", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "forward")
            git("-C", str(seed), "push", "-q", "origin", "HEAD:refs/heads/" + branch)
            script = prefix.replace(root_token, str(dedicated)) + 'Write-Output "REGISTER_READY=1"'
            proc, head = invoke(dedicated, script)
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("REGISTER_ABORT=WORKTREE_DIRTY", proc.stdout)
            self.assertNotIn("REGISTER_READY=1", proc.stdout)
            self.assertEqual(head, base)
        finally:
            shutil.rmtree(temp)

        temp, seed, dedicated, base = build()
        try:
            (dedicated / "note.txt").write_text("base\nlocal\n", encoding="ascii")
            git("-C", str(dedicated), "add", "--", ".")
            git("-C", str(dedicated), "-c", "user.email=sync-selftest@example.com", "-c", "user.name=sync-selftest", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "local")
            local = subprocess.check_output(["git", "-C", str(dedicated), "rev-parse", "HEAD"], text=True).strip()
            script = prefix.replace(root_token, str(dedicated)) + 'Write-Output "REGISTER_READY=1"'
            proc, head = invoke(dedicated, script)
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE", proc.stdout)
            self.assertNotIn("REGISTER_READY=1", proc.stdout)
            self.assertEqual(head, local)
        finally:
            shutil.rmtree(temp)

        temp, seed, dedicated, base = build()
        try:
            (seed / "note.txt").write_text("base\nforward\n", encoding="ascii")
            git("-C", str(seed), "add", "--", ".")
            git("-C", str(seed), "-c", "user.email=sync-selftest@example.com", "-c", "user.name=sync-selftest", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "forward")
            git("-C", str(seed), "push", "-q", "origin", "HEAD:refs/heads/" + branch)
            tip = subprocess.check_output(["git", "-C", str(seed), "rev-parse", "HEAD"], text=True).strip()
            script = prefix.replace(root_token, str(dedicated)) + 'Write-Output "REGISTER_READY=1"'
            proc, head = invoke(dedicated, script)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("REGISTER_READY=1", proc.stdout)
            self.assertNotIn("REGISTER_ABORT=", proc.stdout)
            self.assertEqual(head, tip)
            (dedicated / "extra.txt").write_text("after\n", encoding="ascii")
            registered = subprocess.run(
                [str(pwsh), "-NoProfile", "-File", str(REGISTER), "-Register", "-RepoRoot", str(dedicated), "-RemoteBranch", branch],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(registered.returncode, 0, registered.stdout + registered.stderr)
            self.assertIn("REGISTER_ABORT=WORKTREE_DIRTY", registered.stdout)
            self.assertNotIn("TASK_REGISTER=PASS", registered.stdout)
            self.assertNotIn("SCHTASKS_MISSING", registered.stdout)
            self.assertEqual(subprocess.check_output(["git", "-C", str(dedicated), "rev-parse", "HEAD"], text=True).strip(), tip)
        finally:
            shutil.rmtree(temp)
