"""Read-only STOP identity regression contract; no process termination."""
import re
import unittest
from pathlib import Path

STOP = (Path(__file__).resolve().parents[1] / "downloads" / "STOP_AI_COCKPIT_V10.ps1")

class StopWorkerIdentityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = STOP.read_text(encoding="utf-8-sig")
        cls.block = cls.source.split("function Test-OwnedPidIdentity(", 1)[1].split(
            "function Test-BrainCommandLine(", 1)[0]

    def test_controller_and_workers_share_identity_checks(self):
        s = self.block
        for required in ("$wmi.CreationDate", "$proc.StartTime", "$proc.SessionId",
                         "$selfSession", "$proc.Handle", "$wmi.ProcessId"):
            with self.subTest(required=required):
                self.assertIn(required, s)
        self.assertNotIn('if ($Field -eq "controller_pid") {\n            return', s)

    def test_script_name_token_boundary_and_known_interpreters(self):
        s = self.block
        self.assertIn("[regex]::Escape($name)", s)
        self.assertIn("(?<![A-Za-z0-9_.-])", s)
        self.assertIn("pythonw", s)
        self.assertIn("RUN_AI_COCKPIT_V10.ps1", s)

    def test_py_launcher_supported_without_truncated_regex(self):
        self.assertIn(
            "'^(powershell|pwsh|python|pythonw|py)\\.exe$'", self.block
        )

    def test_stop_script_contains_one_body_and_no_appended_payload(self):
        src = self.source
        self.assertEqual(src.count("function Test-OwnedPidIdentity("), 1)
        self.assertEqual(src.count("function Test-StopWorkerScriptArgument("), 1)
        self.assertEqual(src.count("function Test-BrainCommandLine("), 1)
        self.assertEqual(src.count("function Test-ExactBrainHandle("), 1)
        self.assertTrue(
            src.rstrip().endswith(
                'Write-Host "AI Cockpit V10 managed processes and verified managed Excel stopped." -ForegroundColor Green'
            ), "STOP source must end after its success status, without an appended duplicate"
        )

    def test_actual_script_argument_required_for_ownership(self):
        self.assertIn("Test-StopWorkerScriptArgument $cmd $Field $names", self.block)
        helper = self.source.split("function Test-StopWorkerScriptArgument(", 1)[1].split(
            "function Test-OwnedPidIdentity(", 1)[0]
        self.assertIn("CommandLineToArgvW", helper)
        self.assertIn("-(Command|EncodedCommand|CommandWithArgs)", helper)
        self.assertIn('"sbv2_pid"', helper)
        self.assertIn("IsPathRooted", helper)

    def test_stopped_script_path_must_match_tracked_repo_or_runtime(self):
        helper = self.source.split("function Test-StopWorkerScriptArgument(", 1)[1].split(
            "function Test-OwnedPidIdentity(", 1)[0]
        self.assertIn("[IO.Path]::GetFullPath($scriptPath)", helper)
        self.assertIn("[IO.Path]::GetFullPath((Join-Path $expectedDir $name))", helper)
        self.assertIn('Join-Path $RepoPath "downloads"', helper)
        self.assertIn('Join-Path $RepoPath "scripts"', helper)
        self.assertIn('$RuntimePath; break', helper)
        self.assertIn("[StringComparison]::OrdinalIgnoreCase", helper)
        self.assertIn("([string]$state.repo_root) ([string]$state.runtime_dir)", self.block)

    def test_sbv2_requires_absolute_owned_server_and_interpreter(self):
        helper = self.source.split("function Test-StopWorkerScriptArgument(", 1)[1].split(
            "function Test-OwnedPidIdentity(", 1)[0]
        self.assertIn('C:\\sbv2\\Style-Bert-VITS2', helper)
        self.assertIn('Join-Path $sbvRoot "server_fastapi.py"', helper)
        self.assertIn('("venv\\Scripts\\" + $expectedExe)', helper)
        self.assertIn('[IO.Path]::IsPathRooted($argv[0])', helper)
        self.assertIn('$actualInterpreter', helper)

    def test_controller_never_auto_kills_unmanaged_legacy_voice(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("function Assert-NoUnmanagedLegacyVoiceWorkers", controller)
        self.assertIn("Assert-NoUnmanagedLegacyVoiceWorkers", controller)
        self.assertNotIn("function Stop-LegacyVoiceWorkers", controller)
        guard = controller.split("function Assert-NoUnmanagedLegacyVoiceWorkers", 1)[1].split(
            "function Tail-Log", 1)[0]
        self.assertNotIn("Stop-Process", guard)
        self.assertIn("UNMANAGED_LEGACY_VOICE_PROCESS", guard)
        self.assertIn("LEGACY_VOICE_INVENTORY_UNAVAILABLE", guard)
        self.assertIn("Get-CimInstance Win32_Process -ErrorAction Stop", guard)
        self.assertIn('Join-Path $sbvRoot "server_fastapi.py"', controller)
        self.assertIn("Start-Process -FilePath $exe -ArgumentList $serverArg", controller)

    def test_controller_reuses_exact_stop_identity_contract(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        stop_core = self.source.split("# Parse the actual interpreter script argument.", 1)[1].split(
            "function Test-BrainCommandLine(", 1)[0].strip()
        controller_core = controller.split("# Parse the actual interpreter script argument.", 1)[1].split(
            "# Stop only PIDs recorded", 1)[0].strip()
        self.assertEqual(controller_core, stop_core,
                         "Controller and standalone STOP must share equivalent argv/path/PID checks")

    def test_controller_refuses_unverified_previous_state_without_auto_kill(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        prior = controller.split("function Stop-OwnedFromPreviousState {", 1)[1].split(
            "# A workbook title change", 1)[0]
        self.assertIn("PREVIOUS_V10_STATE_REQUIRES_SAFE_STOP", prior)
        self.assertIn("PREVIOUS_V10_STATE_CORRUPT", prior)
        self.assertNotIn("Stop-Process", prior)
        self.assertNotIn("Stop-OwnedJobBridge", prior)
        self.assertNotIn("Kill()", prior)

    def test_controller_child_and_gateway_cleanup_use_verified_handles(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        bridge = controller.split("function Stop-OwnedJobBridge(", 1)[1].split(
            "# Preflight: a port already", 1)[0]
        self.assertIn("$childProc.Kill()", bridge)
        self.assertIn("$childProc.WaitForExit(5000)", bridge)
        self.assertIn("Test-OwnedPidIdentity $parentField $ExpectedParentId", bridge)
        self.assertNotIn("Stop-Process -Id $owner", bridge)
        cleanup = controller.split("function Stop-ManagedWorkersOnWorkbookClose(", 1)[1].split(
            "function Start-Worker(", 1)[0]
        self.assertIn("$worker.Kill()", cleanup)
        self.assertIn("$worker.WaitForExit(5000)", cleanup)
        self.assertNotIn("Stop-Process -Id $workerPid", cleanup)
        self.assertIn("$gp.Kill()", controller)
        self.assertIn("$bgp.Kill()", controller)
        self.assertNotIn("Stop-Process -Id ([int]$state.gateway_pid)", controller)
        self.assertNotIn("Stop-Process -Id ([int]$state.brain_gateway_pid)", controller)

    def test_controller_excel_termination_uses_verified_held_handle(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        excel = controller.split("function Stop-VerifiedOwnedExcel(", 1)[1].split(
            "function Wait-OwnedHelperProcess", 1)[0]
        self.assertIn("Test-LaunchedExcelOwnership $ExcelPid $WorkbookPath $ControllerPid", excel)
        self.assertIn("Test-OtherExcelInSession $ExcelPid", excel)
        self.assertIn("$handle = $proc.Handle", excel)
        self.assertIn("([datetime]$cim.CreationDate).ToUniversalTime()", excel)
        self.assertIn("$proc.Kill()", excel)
        self.assertIn("$proc.WaitForExit(5000)", excel)
        self.assertNotIn("Stop-Process -Id $ExcelPid", excel)

    def test_refusal_precedes_controller_stop(self):
        src = self.source
        preflight = src.index("SAFE_STOP_PREFLIGHT=BLOCKED_FOREIGN_WORKER_PID")
        controller_stop = src.index("$controllerProc.Kill()")
        self.assertLess(preflight, controller_stop)
        controller = src[src.index('# Stop the supervising RUN/Controller host FIRST.'):
                         src.index('# Controller may have restarted BRAIN')]
        self.assertIn('$controllerHandle = $controllerProc.Handle', controller)
        self.assertIn('$controllerProc.WaitForExit(5000)', controller)
        self.assertNotIn('Stop-Process -Id $controllerPid', controller)

if __name__ == "__main__":
    unittest.main()
