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


def owner_bootstrap_line(text):
    marker = "# OWNER_BOOTSTRAP_COMMAND\n# "
    start = text.index(marker) + len(marker)
    return text[start:].splitlines()[0].strip()


def bootstrap_stages(line):
    prefix = 'cmd /c "'
    if not line.startswith(prefix) or not line.endswith('"'):
        raise AssertionError("bootstrap must be one cmd /c string")
    inner = line[len(prefix):-1]
    if '"' in inner:
        raise AssertionError("bootstrap string contains a nested quote")
    stages = [part.strip() for part in inner.split("&&")]
    if len(stages) != 3:
        raise AssertionError("bootstrap must be fetch, show, and -File")
    return stages


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
        self.assertLess(guard.index("REGISTER_ABORT=WORKTREE_DIRTY"), guard.index('checkout", "--quiet", "--detach"'))
        self.assertLess(guard.index("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"), guard.index('checkout", "--quiet", "--detach"'))
        self.assertLess(guard.index("REGISTER_ABORT=HISTORY_DIVERGED"), guard.index('checkout", "--quiet", "--detach"'))
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
            self.assertNotIn(banned, code, banned)
        self.assertLess(text.index("REGISTER_ABORT=WORKTREE_DIRTY"), text.index("checkout"))
        self.assertLess(text.index("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE"), text.index("checkout"))
        self.assertLess(text.index("REGISTER_ABORT=HISTORY_DIVERGED"), text.index("checkout"))
        check = text.split("function Invoke-SafeRegisterCheck(", 1)[1].split("function Invoke-RegisterScript", 1)[0]
        helper = text.split("function Invoke-SafeGit(", 1)[1].split("function Invoke-SafeRegisterCheck", 1)[0]
        self.assertNotIn("reset --hard", check)
        self.assertIn('"--quiet"', check)
        self.assertIn("PSNativeCommandUseErrorActionPreference = $false", helper)
        self.assertIn("Stderr", helper)
        self.assertIn(
            "$check = Invoke-SafeRegisterCheck $root $RemoteBranch\n"
            "if ($check -ne 0) { exit $check }\n"
            "$registered = Invoke-RegisterScript $root $RemoteBranch",
            text,
        )
        owner = owner_bootstrap_line(text)
        self.assertTrue(owner.startswith('cmd /c "git -C '))
        self.assertNotIn("-Command", owner)
        self.assertNotIn("'", owner)
        self.assertNotIn("`", owner)
        self.assertEqual(owner.count('"'), 2)
        self.assertNotIn("checkout", owner)
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
            "CASE=STDERR_OK",
            "GIT_STDERR_CAPTURED=1",
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

    def test_bootstrap_extracts_script_without_checkout(self):
        pwsh = pwsh_path()
        if pwsh is None:
            self.skipTest("pwsh is not installed")
        import os
        import shutil
        import tempfile

        line = owner_bootstrap_line(SAFE.read_text(encoding="ascii"))
        fetch, show, launch = bootstrap_stages(line)
        self.assertTrue(fetch.startswith("git -C "))
        self.assertIn(" fetch origin refs/heads/cursor/master-spec-fetch-sync-d483:", fetch)
        self.assertIn(":downloads/SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1 > ", show)
        self.assertTrue(launch.startswith("powershell.exe -NoProfile -ExecutionPolicy Bypass -File "))
        self.assertIn(" -RepoRoot ", launch)
        self.assertNotIn("checkout", fetch + show)
        env = os.environ.copy()
        env["OWNER_LINE"] = line
        parsed = subprocess.run(
            [
                str(pwsh),
                "-NoProfile",
                "-Command",
                "$e=$null; $t=$null; "
                "$ast=[System.Management.Automation.Language.Parser]::ParseInput($env:OWNER_LINE, [ref]$t, [ref]$e); "
                "if ($e -and $e.Count -gt 0) { $e | ForEach-Object { $_.ToString() }; exit 1 }; "
                "$chains=$ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.PipelineChainAst] }, $true); "
                "if ($chains.Count -gt 0) { Write-Output 'PIPELINE_CHAIN'; exit 1 }; "
                "Write-Output PARSE51=PASS",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(parsed.returncode, 0, parsed.stdout + parsed.stderr)
        self.assertIn("PARSE51=PASS", parsed.stdout)

        branch = "cursor/master-spec-fetch-sync-d483"
        work_token = r"C:\Users\yusuk\code\trade-cockpit-100oku-master-sync"
        file_token = r"C:\Users\yusuk\code\SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
        stub = "\n".join(
            [
                'param([string]$RepoRoot = "", [string]$RemoteBranch = "", [switch]$Register)',
                '$stamp = Join-Path $RepoRoot "register-called.txt"',
                '[System.IO.File]::WriteAllText($stamp, "called")',
                'Write-Host "TASK_ACTION=powershell.exe -File C:\\repo\\downloads\\UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1 -RepoRoot C:\\repo"',
                'Write-Host "TASK_REGISTER=PASS"',
                "exit 0",
                "",
            ]
        )

        def git(*args):
            subprocess.run(["git", *args], check=True, capture_output=True, text=True)

        def head(path):
            return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()

        def porcelain(path):
            return subprocess.check_output(
                ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=normal"],
                text=True,
            )

        def build():
            temp = Path(tempfile.mkdtemp(prefix="bootstrap-register-"))
            bare = temp / "remote.git"
            main = temp / "main"
            dedicated = temp / "dedicated"
            outside = temp / "SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
            git("init", "-q", "--bare", str(bare))
            git("init", "-q", str(main))
            for key, value in (
                ("user.email", "sync-selftest@example.com"),
                ("user.name", "sync-selftest"),
                ("commit.gpgsign", "false"),
                ("core.autocrlf", "false"),
            ):
                git("-C", str(main), "config", key, value)
            (main / "note.txt").write_text("base\n", encoding="ascii")
            git("-C", str(main), "add", "--", ".")
            git("-C", str(main), "commit", "-q", "-m", "base")
            base = head(main)
            git("-C", str(main), "branch", "-M", branch)
            git("-C", str(main), "remote", "add", "origin", str(bare))
            git("-C", str(main), "push", "-q", "origin", "HEAD:refs/heads/" + branch)
            downloads = main / "downloads"
            downloads.mkdir()
            (downloads / "SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1").write_bytes(SAFE.read_bytes())
            (downloads / "REGISTER_100OKU_MASTER_SPEC_TASK.ps1").write_text(stub, encoding="ascii")
            git("-C", str(main), "add", "--", ".")
            git("-C", str(main), "commit", "-q", "-m", "safe")
            git("-C", str(main), "push", "-q", "origin", "HEAD:refs/heads/" + branch)
            tip = head(main)
            git("--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/" + branch)
            (main / "main-local.txt").write_text("leave-main\n", encoding="ascii")
            git("-C", str(main), "worktree", "add", "--detach", str(dedicated), base)
            return temp, main, dedicated, outside, base, tip

        def run(dedicated, outside, expect_script_absent):
            adapted = line.replace(work_token, str(dedicated)).replace(file_token, str(outside))
            stages = bootstrap_stages(adapted)
            before = head(dedicated)
            fetch_proc = subprocess.run(stages[0].split(), check=False, capture_output=True)
            self.assertEqual(fetch_proc.returncode, 0, fetch_proc.stderr.decode())
            self.assertEqual(head(dedicated), before)
            show_cmd, show_dest = stages[1].split(" > ", 1)
            show_proc = subprocess.run(show_cmd.split(), check=False, capture_output=True)
            self.assertEqual(show_proc.returncode, 0, show_proc.stderr.decode())
            Path(show_dest).write_bytes(show_proc.stdout)
            self.assertEqual(head(dedicated), before)
            self.assertEqual(Path(show_dest).read_bytes(), SAFE.read_bytes())
            script_in_tree = dedicated / "downloads" / "SAFE_REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
            self.assertEqual(expect_script_absent, not script_in_tree.exists())
            launch_args = stages[2].split()
            self.assertEqual(launch_args[0], "powershell.exe")
            launch_args[0] = str(pwsh)
            launched = subprocess.run(launch_args, check=False, capture_output=True, text=True)
            return before, launched

        temp, main, dedicated, outside, base, tip = build()
        try:
            main_head = head(main)
            (dedicated / "extra.txt").write_text("dirty\n", encoding="ascii")
            before, launched = run(dedicated, outside, True)
            self.assertNotEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertIn("REGISTER_ABORT=WORKTREE_DIRTY", launched.stdout)
            self.assertNotIn("TASK_REGISTER=PASS", launched.stdout)
            self.assertEqual(head(dedicated), before)
            self.assertEqual(head(main), main_head)
            self.assertIn("main-local.txt", porcelain(main))
            self.assertFalse((dedicated / "register-called.txt").exists())
        finally:
            shutil.rmtree(temp)

        temp, main, dedicated, outside, base, tip = build()
        try:
            (dedicated / "local.txt").write_text("local\n", encoding="ascii")
            git("-C", str(dedicated), "add", "--", ".")
            git("-C", str(dedicated), "commit", "-q", "-m", "local")
            local = head(dedicated)
            before, launched = run(dedicated, outside, True)
            self.assertNotEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertIn("REGISTER_ABORT=HISTORY_DIVERGED", launched.stdout)
            self.assertNotIn("TASK_REGISTER=PASS", launched.stdout)
            self.assertEqual(head(dedicated), local)
            self.assertFalse((dedicated / "register-called.txt").exists())
        finally:
            shutil.rmtree(temp)

        temp, main, dedicated, outside, base, tip = build()
        try:
            git("-C", str(dedicated), "checkout", "-q", "--detach", tip)
            (dedicated / "local.txt").write_text("local\n", encoding="ascii")
            git("-C", str(dedicated), "add", "--", ".")
            git("-C", str(dedicated), "commit", "-q", "-m", "local")
            local = head(dedicated)
            before, launched = run(dedicated, outside, False)
            self.assertNotEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertIn("REGISTER_ABORT=LOCAL_COMMITS_NOT_ON_REMOTE", launched.stdout)
            self.assertNotIn("TASK_REGISTER=PASS", launched.stdout)
            self.assertEqual(head(dedicated), local)
            self.assertEqual(before, local)
            self.assertFalse((dedicated / "register-called.txt").exists())
        finally:
            shutil.rmtree(temp)

        temp, main, dedicated, outside, base, tip = build()
        try:
            main_head = head(main)
            before, launched = run(dedicated, outside, True)
            self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
            self.assertIn("TASK_REGISTER=PASS", launched.stdout)
            self.assertIn("UPDATE_AND_SYNC_100OKU_MASTER_SPEC.ps1", launched.stdout)
            self.assertIn("REGISTER_CHECK=PASS", launched.stdout)
            self.assertEqual(head(dedicated), tip)
            self.assertNotEqual(before, tip)
            self.assertEqual(head(main), main_head)
            self.assertIn("main-local.txt", porcelain(main))
            self.assertTrue((dedicated / "register-called.txt").is_file())
        finally:
            shutil.rmtree(temp)
