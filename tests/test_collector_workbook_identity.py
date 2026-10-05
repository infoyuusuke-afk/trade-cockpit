"""Collector workbook identity and the 285A diagnostic quote.

The fixture price is synthetic. This file does not claim a live market PASS.
"""

import base64
import gzip
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V9.ps1"


def _ps_here(text, name):
    token = "$%s = @'\n" % name
    start = text.index(token) + len(token)
    end = text.index("\n'@", start)
    return text[start:end]


def _function_body(text, name):
    match = re.search(r"function %s\b.*?\{" % re.escape(name), text)
    if match is None:
        raise AssertionError(name + " is missing")
    start = match.end()
    depth = 1
    index = start
    while index < len(text) and depth:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return text[start:index - 1]


class CollectorWorkbookIdentityContract(unittest.TestCase):
    def setUp(self):
        self.collector = COLLECTOR.read_text(encoding="utf-8")
        self.gateway = GATEWAY.read_text(encoding="utf-8")

    def test_selection_locks_the_canonical_file_and_does_not_scan_other_books(self):
        self.assertIn("BindToMoniker($script:canonicalWorkbookPath)", self.collector)
        self.assertIn("Test-CollectorWorkbookIdentity", self.collector)
        self.assertIn("workbook_full_name", self.collector)
        self.assertIn("workbook_identity_verified", self.collector)
        self.assertIn('$script:IdentityTicker = "285A.T"', self.collector)
        self.assertNotIn("Kioxia_MS2_RSS_Live_Signals*.xlsx", self.collector)
        self.assertNotIn('.Workbooks', self.collector)
        self.assertNotIn('Worksheets.Item("DASHBOARD")', self.collector)
        self.assertNotIn('GetActiveObject("Excel.Application")', self.collector)
        self.assertNotIn("RssOrder", self.collector)
        self.assertIn("$AutoOrderEnabled = $false", self.collector)
        self.assertIn("real_submit_allowed=$false", self.collector)
        self.assertIn("real_submit_allowed = $false", self.collector)

    def test_published_symbol_comes_from_the_285a_row(self):
        block = self.collector.split("$identityQuote = Get-IdentityQuote $results", 1)[1]
        block = block.split("real_submit_allowed = $false", 1)[0]
        self.assertIn("symbol = $identityQuote.symbol", block)
        self.assertIn("current_price = $identityQuote.current_price", block)
        self.assertNotIn("diagnosticSamples[0]", block)

    def test_gateway_uses_the_same_gate_and_keeps_real_submit_false(self):
        for name in (
            "Get-NormalizedLocalWorkbookPath",
            "Test-SameCanonicalWorkbookFile",
            "Get-PublishedWorkbookGate",
        ):
            self.assertEqual(_function_body(self.collector, name), _function_body(self.gateway, name))
        self.assertIn("Get-PublishedWorkbookGate", self.gateway)
        self.assertIn("real_submit_allowed = $false", self.gateway)
        self.assertNotIn("RssOrder", self.gateway)
        self.assertIn('Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"', self.gateway)

    def test_code_column_read_stays_on_the_single_column_b_range(self):
        self.assertIn('Data = $sheet.Range("B2:B101").Value2', self.collector)
        self.assertIn("$sheet.Cells.Item($row,2).Value2 = $tickerText", self.collector)
        self.assertIn("Get-TableValue $table $row 1 1", self.collector)

    def test_deploy_runtime_only_does_not_start_excel_or_stop_the_collector(self):
        runner = (ROOT / "downloads" / "RUN_AI_COCKPIT_V9.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$DeployRuntimeOnly", runner)
        self.assertIn("DeployRuntimeOnly requires -ExpectedSha", runner)
        self.assertIn("function Get-IdentityQuote", runner)
        self.assertIn("RUNTIME_ROLLBACK_BLOCKED", runner)
        self.assertIn("[switch]$AcceptRuntimeCollector", runner)
        self.assertIn("AcceptRuntimeCollector requires -ExpectedSha", runner)
        self.assertIn("RUNTIME_SHA256_MATCH=1", runner)
        self.assertIn("EXCEL_TOUCHED=0", runner)
        self.assertIn("COLLECTOR_PROCESS_STOPPED=0", runner)
        self.assertIn("COLLECTOR_BEFORE_SHA256=", runner)
        self.assertIn("COLLECTOR_AFTER_SHA256=", runner)
        self.assertIn("RUNTIME_DIR_CODEPOINTS=", runner)
        only = runner.split("if ($DeployRuntimeOnly) {", 1)[1]
        only = only.split("Starting Controller V9", 1)[0]
        self.assertIn("exit 0", only)
        self.assertNotIn("Stop-Process", only)
        self.assertNotIn("AI_COCKPIT_CONTROLLER_V9.ps1", only)
        self.assertLess(runner.find("exit 0"), runner.find("Starting Controller V9"))

    def test_windows_powershell_selftest_accepts_285a_and_rejects_8035(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell is not installed in this environment")
        proc = subprocess.run(
            [shell, "-NoProfile", "-File", str(COLLECTOR), "-WorkbookIdentitySelfTest"],
            check=False,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertIn("WORKBOOK_IDENTITY_SELFTEST PASS", proc.stdout)
        self.assertNotIn("LIVE PASS", proc.stdout)

    def test_preopen_zero_price_keeps_285a_and_session_zero_does_not(self):
        self.assertIn("function Test-PreopenZeroPriceIdentity", self.collector)
        self.assertIn("$script:preopenIdentitySpare", self.collector)
        self.assertIn("workbook_identity_verified = [bool]$identityVerified", self.collector)

    def test_pinned_b81b887_collector_hash_is_the_deploy_anchor(self):
        digest = "510ACF2E8F962A9B9D7AA2777955E60DC2247C34C232EFBE9F50CCFFAB7C424F"
        runner = (ROOT / "downloads" / "RUN_AI_COCKPIT_V9.ps1").read_text(encoding="utf-8")
        self.assertIn(digest, runner)
        # Pull-request checkouts are shallow and do not contain this parent
        # commit. Verify the blob only when the object is already local.
        probe = subprocess.run(
            ["git", "cat-file", "-e", "b81b8877b12a33368e91e5e156a2fc7ac4529349"],
            cwd=str(ROOT),
            capture_output=True,
        )
        if probe.returncode == 0:
            blob = subprocess.check_output(
                [
                    "git",
                    "show",
                    "b81b8877b12a33368e91e5e156a2fc7ac4529349:ms2_live/MS2_RSS_100_Collector.ps1",
                ],
                cwd=str(ROOT),
            )
            self.assertEqual(hashlib.sha256(blob).hexdigest().upper(), digest)
        accept = runner.split("if ($AcceptRuntimeCollector) {", 1)[1].split("Starting Controller V9", 1)[0]
        self.assertIn("exit 0", accept)
        self.assertIn("CONTROLLER_STARTED=0", accept)
        self.assertIn("ROLLBACK=0", accept)
        self.assertNotIn("AI_COCKPIT_CONTROLLER_V9.ps1", accept)
        self.assertIn("function Get-CollectorHandoffMode", runner)
        self.assertIn("CONTROLLER_RESTARTS", runner)
        self.assertIn("DIRECT_START", runner)
        self.assertNotIn("refusing to restart Collector while Controller is running", runner)
        self.assertIn("MS2_RSS_100_Collector.acceptance.stderr.log", runner)
        self.assertIn("COLLECTOR_EXITED", runner)
        collector = COLLECTOR.read_text(encoding="utf-8")
        keep, _, after_keep = collector.partition("LIVE_SHEET_KEEP")
        self.assertIn("LIVE_SHEET_KEEP_END", after_keep)
        kept, _, rest = after_keep.partition("LIVE_SHEET_KEEP_END")
        self.assertNotIn("FormulaLocal", kept)
        self.assertIn("existing 100", kept)
        self.assertIn("if (-not $liveSheetReady)", rest)
        self.assertLess(rest.find("JNX RSS式設定"), rest.find("Start-LocalJsonBridge $jsonPath 28580"))
        self.assertIn("deferFirstTdnet", collector)

    def test_owner_command_is_encoded_and_has_no_dollar_sign(self):
        """Interactive PowerShell rejected a 28770-char EncodedCommand.

        The console input buffer truncates a line of that size, so the
        pasted value is no longer valid Base64 and acceptance never starts.
        The pasted line has to stay under 8000 characters, inside the
        8191-character console limit that already accepted a shorter command.
        """
        text = (ROOT / "downloads" / "ACCEPT_OWNER_RUNTIME.ps1").read_text(encoding="utf-8")
        inner = _ps_here(text, "inner").strip()
        stub = _ps_here(text, "stub").strip()
        self.assertNotIn("\n", stub)
        self.assertNotIn("\r", stub)
        blob = re.search(r"\$b='([A-Za-z0-9+/=]+)'", stub).group(1)
        expanded = gzip.decompress(base64.b64decode(blob)).decode("utf-8").strip()
        self.assertEqual(expanded, inner)
        encoded = base64.b64encode(stub.encode("utf-16-le")).decode("ascii")
        command = (
            "powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -EncodedCommand "
            + encoded
        )
        self.assertNotIn("$", command)
        self.assertNotIn("\n", command)
        self.assertLess(len(command), 8000)
        self.assertRegex(encoded, r"^[A-Za-z0-9+/=]+$")
        self.assertEqual(len(encoded) % 4, 0)
        base64.b64decode(encoded, validate=True)
        for banned in ("Stop-Process", "card_system.js", "-Depth", "origin/cursor/", "checkout -B"):
            self.assertNotIn(banned, inner)
        for required in (
            "rev-parse --verify FETCH_HEAD",
            "merge-base --is-ancestor",
            "checkout -f --detach",
            "811f97aba5a5c3057636c152eddada53e97b3685",
            "-AcceptRuntimeCollector",
            "V9_CONTROLLER_STATE.json",
            "Win32_Process",
            "REPO_MATCH_COUNT=",
        ):
            self.assertIn(required, inner)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()
        self.assertEqual(len(digest), 64)

    def test_runtime_accept_selftest_passes(self):
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell is not installed in this environment")
        proc = subprocess.run(
            [shell, "-NoProfile", "-File", str(ROOT / "downloads" / "RUN_AI_COCKPIT_V9.ps1"), "-RuntimeAcceptSelfTest"],
            check=False,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)
        self.assertIn("RUNTIME_ACCEPT_SELFTEST PASS", proc.stdout)

    def test_fetch_head_pin_when_remote_tracking_ref_is_absent(self):
        """Owner failure: fetch stores the branch only in FETCH_HEAD.

        A single-branch clone does not create origin/cursor/... after
        `git fetch origin <branch>`. Checking that ref out fails with
        "is not a commit". The pin is detached from FETCH_HEAD instead.
        """
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        env = os.environ.copy()
        env.update(
            {
                "GIT_AUTHOR_NAME": "owner-pin-test",
                "GIT_AUTHOR_EMAIL": "owner-pin-test@example.com",
                "GIT_COMMITTER_NAME": "owner-pin-test",
                "GIT_COMMITTER_EMAIL": "owner-pin-test@example.com",
            }
        )

        def git(cwd, *args, check=True):
            return subprocess.run(
                ["git", "-C", str(cwd), *args],
                check=check,
                capture_output=True,
                text=True,
                env=env,
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote"
            remote.mkdir()
            self.assertEqual(git(remote, "init", "-b", "main").returncode, 0)
            (remote / "README").write_text("main\n", encoding="utf-8")
            self.assertEqual(git(remote, "add", "README").returncode, 0)
            self.assertEqual(git(remote, "commit", "-m", "main").returncode, 0)
            branch = "cursor/p0-stale-price-failclosed-d483"
            self.assertEqual(git(remote, "checkout", "-b", branch).returncode, 0)
            (remote / "pin.txt").write_text("pin\n", encoding="utf-8")
            self.assertEqual(git(remote, "add", "pin.txt").returncode, 0)
            self.assertEqual(git(remote, "commit", "-m", "pin").returncode, 0)
            pin = git(remote, "rev-parse", "HEAD").stdout.strip()
            (remote / "tip.txt").write_text("tip\n", encoding="utf-8")
            self.assertEqual(git(remote, "add", "tip.txt").returncode, 0)
            self.assertEqual(git(remote, "commit", "-m", "tip").returncode, 0)
            tip = git(remote, "rev-parse", "HEAD").stdout.strip()
            owner = root / "owner"
            cloned = git(root, "clone", "--single-branch", "--branch", "main", str(remote), str(owner))
            self.assertEqual(cloned.returncode, 0, cloned.stderr)
            missing = "origin/" + branch
            absent = git(owner, "rev-parse", "--verify", missing, check=False)
            self.assertNotEqual(absent.returncode, 0)
            fetched = git(owner, "fetch", "origin", branch, check=False)
            self.assertEqual(fetched.returncode, 0, fetched.stderr)
            self.assertIn("FETCH_HEAD", fetched.stderr)
            fetch_head = git(owner, "rev-parse", "--verify", "FETCH_HEAD").stdout.strip()
            self.assertEqual(fetch_head, tip)
            still_absent = git(owner, "rev-parse", "--verify", missing, check=False)
            self.assertNotEqual(still_absent.returncode, 0)
            old = git(owner, "checkout", "-B", branch, missing, check=False)
            self.assertNotEqual(old.returncode, 0)
            self.assertIn("is not a commit", old.stderr)
            self.assertEqual(git(owner, "cat-file", "-e", pin + "^{commit}").returncode, 0)
            ancestor = git(owner, "merge-base", "--is-ancestor", pin, "FETCH_HEAD", check=False)
            self.assertEqual(ancestor.returncode, 0, ancestor.stderr)
            detached = git(owner, "checkout", "-f", "--detach", pin, check=False)
            self.assertEqual(detached.returncode, 0, detached.stderr)
            head = git(owner, "rev-parse", "--verify", "HEAD").stdout.strip()
            self.assertEqual(head, pin)
            self.assertNotEqual(git(owner, "rev-parse", "--verify", missing, check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
