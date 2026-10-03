"""Issue #288: V9 workbook identity probe must not hang the Controller.

Cloud tests check structure, the hard-timeout contract, and Excel safety.
They do not launch MarketSpeed II or a real workbook.
"""
import os
import pathlib
import re
import shutil
import signal
import subprocess
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1"
HELPER = ROOT / "downloads" / "EXCEL_IDENTITY_PROBE_V9.ps1"
# The helper sleeps 120s. Ubuntu pwsh 7.6 startup varied from 5.3s
# (Actions run 36958072645) to still-running at 12s (run 36958771535)
# on the same controller. This cap covers that spread plus the script's
# own 20s kill-path bound, and still fails if the 120s hang is not killed.
# It does not change the production 35s probe timeout. Windows PowerShell
# 5.1 acceptance stays in v9-ui-voice-acceptance.yml.
_LINUX_SELFTEST_HARNESS_SECONDS = 45


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _stop_process_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _startup_section(text: str) -> str:
    start = text.index("Opening MS2 RSS workbook")
    end = text.index('Write-Status "Starting Watcher..."')
    return text[start:end]


class ExcelIdentityProbeContract(unittest.TestCase):
    def setUp(self):
        self.controller = CONTROLLER.read_text(encoding="utf-8")
        self.helper = HELPER.read_text(encoding="utf-8")
        self.startup = _startup_section(self.controller)

    def test_controller_startup_has_no_synchronous_bind_to_moniker(self):
        self.assertNotIn("BindToMoniker", self.controller)
        self.assertNotIn("BindToMoniker", self.helper)
        self.assertIn("IRunningObjectTable", self.helper)
        self.assertIn("GetObject", self.helper)
        self.assertIn("ROT_MONIKER_NOT_REGISTERED", self.helper)
        self.assertIn("EXCEL_BUSY", self.helper)
        self.assertIn("0x800AC472", self.helper)
        self.assertIn("FULL_NAME_IDENTITY_UNREADABLE", self.helper)
        self.assertIn("unmatched:", self.helper)
        self.assertLess(self.helper.index("PID_MISMATCH"), self.helper.index("FULL_NAME_DIFFERENT_FILE"))
        self.assertLess(
            self.helper.index("[string]::Equals($fullName, $WorkbookPath, $OrdinalIgnoreCaseComparison)"),
            self.helper.index("[ExcelFileIdentity]::Key($WorkbookPath)"),
        )
        self.assertIn("command_line_match", self.helper)
        self.assertIn("parent_match", self.helper)
        self.assertIn("EXCEL_PROCESS_EXITED", self.helper)
        self.assertIn("EXCEL_SERIOUS_ERROR_PROMPT", self.helper)
        self.assertIn('$value.IndexOf($SeriousErrorJa, $OrdinalComparison)', self.helper)
        self.assertIn("Watching launched Excel before COM identity", self.helper)
        self.assertIn("exit 4", self.helper)
        self.assertIn("exit 5", self.helper)
        self.assertNotIn("SendKeys", self.helper)
        self.assertNotIn("BM_CLICK", self.helper)
        loop = self.helper.split("while ((Get-Date) -lt $deadline)", 1)[1]
        self.assertLess(loop.index("Test-WorkbookOpenBlocker"), loop.index("Waiting for workbook ROT registration..."))
        diagnostics = self.controller.split("function Get-CanonicalWorkbookOpenDiagnostics", 1)[1].split("function Complete-ExcelProbeResult", 1)[0]
        self.assertIn("DocumentRecovery", diagnostics)
        self.assertIn("DisabledItems", diagnostics)
        self.assertIn("disabled_item_name_match = $false", diagnostics)
        self.assertIn('disabled_count_meaning = "count_only"', diagnostics)
        self.assertIn("has_vba_project", diagnostics)
        self.assertIn("external_link_count", diagnostics)
        self.assertIn("marketspeed_addin_present", diagnostics)
        self.assertNotIn("Remove-Item", diagnostics)
        self.assertNotIn("Set-ItemProperty", diagnostics)
        self.assertNotRegex(self.controller, r"\sas\s+\[")
        self.assertNotRegex(self.helper, r"\sas\s+\[")
        self.assertNotIn("??", self.controller)
        self.assertNotIn("?.", self.controller)
        self.assertIn("if ($prop.Value -is [string])", self.controller)
        self.assertIn("excel_process_exit", self.controller)
        self.assertIn("workbook_open", self.controller)
        self.assertIn("excel_exit_code", self.controller)
        self.assertIn('if ($Probe.code -eq "EXCEL_IDENTITY_MISMATCH") { return $Probe }', self.controller)
        self.assertIn("ProcessStartInfo", self.startup)
        self.assertIn("UseShellExecute = $false", self.startup)
        self.assertIn("Add-ExcelIdentityIncident", self.startup)
        self.assertIn("EXCEL_IDENTITY_PROBE_V9.ps1", self.controller)
        self.assertIn("Invoke-ExcelIdentityProbe", self.startup)
        self.assertIn("Start-Process -FilePath $shell", self.controller)
        self.assertIn("Wait-OwnedHelperProcess", self.controller)

    def test_ps51_ordinal_comparisons_do_not_depend_on_ansi_decoding(self):
        serious = (0x91CD, 0x5927, 0x306A, 0x30A8, 0x30E9, 0x30FC)
        reopen = (
            0x3053, 0x306E, 0x30C9, 0x30AD, 0x30E5, 0x30E1, 0x30F3, 0x30C8,
            0x3092, 0x958B, 0x304D, 0x307E, 0x3059, 0x304B,
        )
        self.assertEqual("".join(chr(c) for c in serious), "重大なエラー")
        self.assertEqual("".join(chr(c) for c in reopen), "このドキュメントを開きますか")
        self.assertIn(", ".join(f"[char]0x{c:04X}" for c in serious), self.helper)
        self.assertIn(", ".join(f"[char]0x{c:04X}" for c in reopen), self.helper)
        self.assertNotIn("重大なエラー", self.helper)
        self.assertNotIn("このドキュメントを開きますか", self.helper)
        self.assertIn("$OrdinalComparison = [StringComparison]::Ordinal", self.helper)
        self.assertIn("$OrdinalIgnoreCaseComparison = [StringComparison]::OrdinalIgnoreCase", self.helper)
        self.assertIn('$value.IndexOf("serious problem", $OrdinalIgnoreCaseComparison)', self.helper)
        self.assertIn('$value.IndexOf("serious error", $OrdinalIgnoreCaseComparison)', self.helper)
        self.assertIn("$last.command_line.IndexOf($WorkbookPath, $OrdinalIgnoreCaseComparison)", self.helper)
        self.assertIn("[char]0x697D, [char]0x5929", self.controller)
        self.assertNotIn("楽天", self.controller)
        self.assertTrue(self.helper.isascii())
        self.assertTrue(self.controller.isascii())
        for label, text in (("controller", self.controller), ("helper", self.helper)):
            for match in re.finditer(r"\[StringComparison\]::\w+", text):
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                line = text[line_start:line_end if line_end >= 0 else None]
                self.assertIn("=", line, f"{label} still passes StringComparison into a call: {line}")
            self.assertNotRegex(text, r"\?\?")
            self.assertNotRegex(text, r"\?\.")
            self.assertNotRegex(text, r"\sas\s+\[")

    def test_helper_timeout_is_hard_and_bounded(self):
        self.assertIn("$ExcelIdentityProbeTimeoutSeconds = 35", self.controller)
        self.assertIn("if ($TimeoutSeconds -lt 30 -or $TimeoutSeconds -gt 40)", self.controller)
        waiter = self.controller.split("function Wait-OwnedHelperProcess", 1)[1].split("function Get-OperationsIncidentPath", 1)[0]
        self.assertIn("WaitForExit", waiter)
        self.assertIn("$Process.Kill()", waiter)
        self.assertIn("WaitForExit(5000)", waiter)
        self.assertNotIn("EXCEL", waiter)
        self.assertNotIn("Stop-Process", waiter)
        self.assertIn("$IdentityProbeSelfTest", self.controller)
        self_test_at = self.controller.index("if ($IdentityProbeSelfTest)")
        main_try = self.controller.index("try {", self_test_at)
        self.assertLess(self_test_at, main_try)

    def test_timeout_and_failure_fail_closed_with_explicit_codes(self):
        self.assertIn("EXCEL_IDENTITY_PROBE_TIMEOUT", self.controller)
        for code in ("EXCEL_IDENTITY_MISMATCH", "EXCEL_IDENTITY_PROBE_FAILED"):
            self.assertIn(code, self.controller)
            self.assertIn(code, self.helper)
        self.assertIn("AI Cockpit startup failed closed", self.startup)
        self.assertIn("Unrelated Excel processes were not touched", self.startup)
        self.assertIn("$state.workbook_identity_verified = $false", self.startup)
        self.assertIn("Excel identity probe failed closed:", self.startup)
        self.assertIn("Excel workbook open failed closed:", self.startup)
        self.assertIn("Startup does not reopen Excel.", self.startup)
        self.assertEqual(self.startup.count("New-Object System.Diagnostics.ProcessStartInfo"), 1)
        self.assertIn('Write-Status "Starting Watcher..."', self.controller[self.controller.index("if (-not $probe.ok)"):])

    def test_foreign_excel_presence_keeps_isolated_canonical_launch(self):
        self.assertIn('$Build = "V9-CONTROLLER-20261002-EXCEL-FOREIGN-SURVIVE-01"', self.controller)
        self.assertNotIn('throw "Excel safety interlock: foreign Excel process detected."', self.controller)
        self.assertNotIn("Close unrelated Excel workbooks first", self.controller)
        self.assertNotIn("FOREIGN EXCEL DETECTED - FAIL-CLOSED SAFETY STOP.", self.controller)
        self.assertIn("EXCEL SAFETY INTERLOCK", self.controller)
        self.assertIn("Foreign Excel is present. It will not be closed, killed, or operated.", self.controller)
        self.assertIn("separate isolated Excel /x for the canonical workbook only.", self.controller)
        self.assertIn("return '/x \"' + $WorkbookPath + '\"'", self.controller)
        self.assertIn("$excelStart.Arguments = Get-IsolatedExcelArguments $WorkbookPath", self.controller)
        self.assertIn("Refusing to take ownership. Foreign Excel was not touched.", self.controller)
        self.assertIn("CANONICAL WORKBOOK CONFLICT - FAIL-CLOSED SAFETY STOP.", self.controller)
        self.assertIn("BLOCKED_FOREIGN_EXCEL", self.controller)
        self.assertIn("real_submit_allowed = $false", self.controller)
        interlock = self.controller.split("$foreignExcelAtStartup = @(Get-ForeignExcelProcesses)", 1)[1].split("Starting unified voice backend", 1)[0]
        self.assertNotIn("throw ", interlock)
        self.assertIn("EXCEL SAFETY INTERLOCK", interlock)
        self.assertIn("Get-ForeignExcelProcesses", self.controller)
        launch = self.controller.split("Opening MS2 RSS workbook", 1)[1].split("EXCEL.EXE was not found.", 1)[0]
        self.assertIn("Get-CanonicalWorkbookConflicts $WorkbookPath $WorkbookName @()", launch)
        self.assertIn("$state.excel_pid = 0", launch)
        self.assertNotIn("$state.excel_pid = [int]$existingExcel", launch)
        loop = self.controller.split("while ($true)", 1)[1].split("Has the user closed the workbook?", 1)[0]
        self.assertIn("Get-CanonicalWorkbookConflicts $WorkbookPath $WorkbookName $allowedExcelPids", loop)
        self.assertNotIn("Get-ForeignExcelProcesses $allowedExcelPids", loop)
        self.assertLess(loop.index("leaving foreign Excel untouched:"), loop.index("Stop-VerifiedOwnedExcel"))
        conflict = self.controller.split("function Get-CanonicalWorkbookConflicts", 1)[1].split("function Get-IsolatedExcelArguments", 1)[0]
        self.assertIn("$ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase", conflict)
        after_hoist = conflict.split("$ordinalIgnoreCase = [StringComparison]::OrdinalIgnoreCase", 1)[1]
        self.assertNotIn("[StringComparison]::", after_hoist)
        self.assertNotRegex(conflict, r"\sas\s+\[")
        self.assertNotIn("??", conflict)
        self.assertNotIn("?.", conflict)

    def test_foreign_work_excel_survives_orphan_launch_and_identity_cleanup(self):
        launch = self.startup
        self.assertNotIn("Stop-VerifiedLeftoverCockpitExcel", self.controller)
        self.assertNotIn("Test-LeftoverCockpitExcel", self.controller)
        self.assertNotIn("Stop-VerifiedOwnedExcel", launch)
        self.assertNotIn("Stop-Process", launch)
        self.assertIn("pre-existing canonical Excel PID ", launch)
        self.assertIn("was not stopped and was not adopted.", launch)
        self.assertIn("Refusing to take ownership. Foreign Excel was not touched.", launch)
        self.assertIn("launched Excel was not stopped after identity or workbook-open failure.", launch)
        self.assertNotIn("verified owned Excel stopped after identity failure.", launch)
        self.assertIn("EXCEL_WORKBOOK_OPEN_BLOCKED", self.controller)
        self.assertIn("HWND_PROCESS_NOT_READY", self.controller)
        owned = self.controller.split("function Stop-VerifiedOwnedExcel", 1)[1].split("function Wait-OwnedHelperProcess", 1)[0]
        self.assertLess(owned.index("Test-LaunchedExcelOwnership"), owned.index("Test-OtherExcelInSession"))
        self.assertLess(owned.index("Test-OtherExcelInSession"), owned.index("Stop-Process -Id $ExcelPid"))
        hidden = self.controller.split("terminating verified hidden AI Cockpit Excel PID", 1)[0]
        self.assertLess(hidden.rindex("Test-OtherExcelInSession"), hidden.rindex("-not $otherExcelPresent"))
        self.assertIn("Get-Process EXCEL -ErrorAction SilentlyContinue", self.controller.split("function Test-OtherExcelInSession", 1)[1].split("function Get-ForeignExcelProcesses", 1)[0])
        prompt = self.helper.split("function Get-SeriousErrorPrompt", 1)[1].split("function Stop-ProbeForProcessExit", 1)[0]
        self.assertIn("Get-Process EXCEL -ErrorAction SilentlyContinue", prompt)
        self.assertIn("[ExcelProcessWindows]::VisibleTexts($procId)", prompt)
        blocked = self.helper.split('$last.last_error = "HWND_PROCESS_NOT_READY"', 1)[1].split("else {", 1)[0]
        self.assertIn("EXCEL_WORKBOOK_OPEN_BLOCKED", blocked)
        self.assertIn('$disposition = "fail"', blocked)
        busy = self.helper.split("if ($hresult -eq 0x800AC472)", 1)[1].split("elseif ($hresult -eq 0x80010001", 1)[0]
        self.assertIn("Test-WorkbookOpenBlocker", busy)
        self.assertIn("EXCEL_WORKBOOK_OPEN_BLOCKED", busy)
        self.assertIn('$disposition = "fail"', busy)
        mismatch = self.helper.split('$last.last_error = "PID_MISMATCH"', 1)[1].split("else {", 1)[0]
        self.assertIn('$disposition = "fail"', mismatch)
        self.assertIn("It was not adopted.", mismatch)
        self.assertNotIn("Stop-Process", self.helper)
        self.assertNotIn("SendKeys", launch + self.helper)
        self.assertNotIn("BM_CLICK", launch + self.helper)
        self.assertIn("real_submit_allowed = $false", self.controller)
        self.assertTrue(self.controller.isascii())
        self.assertTrue(self.helper.isascii())

    def test_unrelated_excel_is_never_killed(self):
        for text in (self.controller, self.helper):
            lowered = text.lower()
            self.assertNotIn("taskkill", lowered)
            self.assertNotIn("stop-process -name excel", lowered)
            self.assertNotIn("get-process excel | stop-process", lowered)
            self.assertNotRegex(text, r"Get-Process\s+EXCEL[^\n;]*Stop-Process")
        self.assertNotIn("Stop-Process", self.helper)
        self.assertNotIn("Stop-Process", self.startup)
        self.assertNotIn("Stop-VerifiedOwnedExcel", self.startup)

    def test_canonical_workbook_pid_parent_and_session_contract_remains(self):
        ownership = self.controller.split("function Test-LaunchedExcelOwnership", 1)[1].split("function Stop-VerifiedOwnedExcel", 1)[0]
        for needle in (
            "CommandLine",
            "ParentProcessId",
            "$ControllerPid",
            "SessionId",
            "$WorkbookPath",
        ):
            self.assertIn(needle, ownership)
        stop = self.controller.split("function Stop-VerifiedOwnedExcel", 1)[1].split("function Wait-OwnedHelperProcess", 1)[0]
        self.assertLess(stop.index("Test-LaunchedExcelOwnership"), stop.index("Test-OtherExcelInSession"))
        self.assertLess(stop.index("Test-OtherExcelInSession"), stop.index("Stop-Process -Id $ExcelPid"))
        for needle in (
            "FullName",
            "hwnd",
            "excel_pid",
            "Test-LaunchedExcelOwnership",
            "$WorkbookPath",
        ):
            self.assertIn(needle, self.helper + self.controller)
        self.assertIn("$fullName -ine $WorkbookPath", self.controller)
        self.assertIn("$reportedPid -ne $ExpectedExcelPid", self.controller)
        for port in ("28580", "28581", "28582", "28583"):
            self.assertIn(port, self.controller)

    def test_progress_logs_distinguish_waiting_from_a_hang(self):
        combined = self.controller + self.helper
        for needle in (
            "Excel identity probe started",
            "Excel identity probe attempt ",
            "Waiting for workbook ROT registration...",
            "Workbook moniker found",
            "Excel HWND verified",
            "Excel PID verified",
            "Excel identity verified",
            "EXCEL_IDENTITY_PROBE_TIMEOUT after ",
        ):
            self.assertIn(needle, combined)

    def test_hung_helper_returns_within_the_hard_timeout_when_powershell_exists(self):
        self.assertGreater(_LINUX_SELFTEST_HARNESS_SECONDS, 20)
        self.assertLess(_LINUX_SELFTEST_HARNESS_SECONDS, 120)
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is not installed in this environment; Windows CI runs -IdentityProbeSelfTest")
        env = os.environ.copy()
        env["POWERSHELL_TELEMETRY_OPTOUT"] = "1"
        env["POWERSHELL_UPDATECHECK"] = "Off"
        started = time.monotonic()
        proc = subprocess.Popen(
            [shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(CONTROLLER), "-IdentityProbeSelfTest"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=(os.name != "nt"),
            env=env,
        )
        try:
            try:
                stdout, stderr = proc.communicate(timeout=_LINUX_SELFTEST_HARNESS_SECONDS)
            except subprocess.TimeoutExpired as exc:
                _stop_process_group(proc)
                stdout = _as_text(exc.stdout)
                stderr = _as_text(exc.stderr)
                try:
                    extra_out, extra_err = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired as leftover:
                    extra_out = leftover.stdout
                    extra_err = leftover.stderr
                stdout += _as_text(extra_out)
                stderr += _as_text(extra_err)
                elapsed = time.monotonic() - started
                self.fail(
                    "identity probe self-test still running after "
                    f"{elapsed:.2f}s (cap {_LINUX_SELFTEST_HARNESS_SECONDS}s). "
                    "The 120s hang was not interrupted.\n"
                    f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
        finally:
            _stop_process_group(proc)
        elapsed = time.monotonic() - started
        output = (stdout or "") + (stderr or "")
        self.assertEqual(proc.returncode, 0, output)
        self.assertIn("IDENTITY PROBE SELFTEST PASS", output)
        self.assertIn("EXCEL_IDENTITY_PROBE_TIMEOUT after ", output)
        self.assertIn("Unrelated Excel processes were not touched", output)
        self.assertLess(elapsed, _LINUX_SELFTEST_HARNESS_SECONDS, output)


if __name__ == "__main__":
    unittest.main()
