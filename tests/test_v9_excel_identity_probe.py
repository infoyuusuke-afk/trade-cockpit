"""Issue #288: V9 workbook identity probe must not hang the Controller.

Cloud tests check structure, the hard-timeout contract, and Excel safety.
They do not launch MarketSpeed II or a real workbook.
"""
import os
import pathlib
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
        self.assertNotIn("[Runtime.InteropServices.Marshal]::BindToMoniker", self.controller)
        self.assertNotIn("BindToMoniker", self.startup)
        self.assertIn("[Runtime.InteropServices.Marshal]::BindToMoniker", self.helper)
        self.assertIn("EXCEL_IDENTITY_PROBE_V9.ps1", self.controller)
        self.assertIn("Invoke-ExcelIdentityProbe", self.startup)
        self.assertIn("Start-Process -FilePath $shell", self.controller)
        self.assertIn("Wait-OwnedHelperProcess", self.controller)

    def test_helper_timeout_is_hard_and_bounded(self):
        self.assertIn("$ExcelIdentityProbeTimeoutSeconds = 35", self.controller)
        self.assertIn("if ($TimeoutSeconds -lt 30 -or $TimeoutSeconds -gt 40)", self.controller)
        waiter = self.controller.split("function Wait-OwnedHelperProcess", 1)[1].split("function Invoke-ExcelIdentityProbe {", 1)[0]
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
        self.assertIn('Write-Status "Starting Watcher..."', self.controller[self.controller.index("if (-not $probe.ok)"):])

    def test_unrelated_excel_is_never_killed(self):
        for text in (self.controller, self.helper):
            lowered = text.lower()
            self.assertNotIn("taskkill", lowered)
            self.assertNotIn("stop-process -name excel", lowered)
            self.assertNotIn("get-process excel | stop-process", lowered)
            self.assertNotRegex(text, r"Get-Process\s+EXCEL[^\n;]*Stop-Process")
        self.assertNotIn("Stop-Process", self.helper)
        self.assertNotIn("Stop-Process", self.startup)
        self.assertIn("Stop-VerifiedOwnedExcel", self.startup)

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
        self.assertLess(stop.index("Test-LaunchedExcelOwnership"), stop.index("Stop-Process -Id $ExcelPid"))
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
