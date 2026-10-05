import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "downloads" / "SYNC_100OKU_MASTER_SPEC.ps1"
REGISTER = ROOT / "downloads" / "REGISTER_100OKU_MASTER_SPEC_TASK.ps1"
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
        for path in (SYNC, REGISTER):
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), path.name)
            raw.decode("ascii")
        sync = SYNC.read_text(encoding="ascii")
        register = REGISTER.read_text(encoding="ascii")
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
        self.assertNotIn("RssOrder", sync)
        self.assertIn("TASK_TIME=16:45", register)
        self.assertIn("TASK_REGISTER=NOT_RUN", register)
        self.assertLess(register.index("TASK_REGISTER=NOT_RUN"), register.index("schtasks.exe"))

    def test_manifest_lists_the_working_copy(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["destination"], r"D:\100億PROJECT\MASTER_SPEC")
        self.assertIs(manifest["cloud_agent_can_write_destination"], False)
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
