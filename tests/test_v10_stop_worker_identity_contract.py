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

    def test_controller_never_auto_kills_unmanaged_legacy_runtime(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        marker = "function Assert-NoUnmanagedLegacyRuntimeProcesses"
        self.assertIn(marker, controller)
        self.assertIn("Assert-NoUnmanagedLegacyRuntimeProcesses", controller)
        self.assertNotIn("function Stop-LegacyVoiceWorkers", controller)
        guard = controller.split(marker, 1)[1].split("function Tail-Log", 1)[0]
        self.assertNotIn("Stop-Process", guard)
        self.assertNotIn(".Kill()", guard)
        self.assertIn("UNMANAGED_LEGACY_RUNTIME_PROCESS", guard)
        self.assertIn("UNMANAGED_RUNTIME_INVENTORY_UNAVAILABLE", guard)
        self.assertIn("UNMANAGED_RUNTIME_COMMANDLINE_UNAVAILABLE", guard)
        self.assertNotIn("IsNullOrWhiteSpace($commandLine)) { continue }", guard)
        self.assertIn("Get-CimInstance Win32_Process -ErrorAction Stop", guard)
        for script in ("RUN_AI_COCKPIT_V[6789]", "AI_COCKPIT_CONTROLLER_V[6789]",
                       "SPEAK_TODAY_STRATEGY", "SPEAK_LIVE_EMOTION",
                       "Kioxia_RSS_Live_Watcher", "MS2_RSS_100_Collector"):
            self.assertIn(script, guard)
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
        self.assertIn("Test-ManagedExcelWorkbooksExclusive $ExcelPid $WorkbookPath", excel)
        self.assertGreaterEqual(excel.count("Test-ManagedExcelWorkbooksExclusive $ExcelPid $WorkbookPath"), 2,
                                "Must recheck COM workbook ownership immediately before process kill")
        self.assertNotIn("Stop-Process -Id $ExcelPid", excel)

    def test_controller_excel_kill_refuses_same_pid_foreign_workbooks(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        helper = controller.split("function Test-ManagedExcelWorkbooksExclusive(", 1)[1].split(
            "function Stop-VerifiedOwnedExcel(", 1)[0]
        self.assertIn('GetActiveObject("Excel.Application")', helper)
        self.assertIn("GetWindowThreadProcessId", helper)
        self.assertIn("if ([int]$foundPid -ne $ExcelPid) { return $false }", helper)
        self.assertIn("if ($workbooks.Count -eq 0) { return $true }", helper)
        self.assertIn("Test-OnlyCanonicalExcelWorkbookOpen $app $WorkbookPath", helper)
        expected = self.source.split("function Test-OnlyCanonicalExcelWorkbookOpen(", 1)[1].split(
            "# Do not force-kill", 1)[0].strip()
        actual = controller.split("function Test-OnlyCanonicalExcelWorkbookOpen(", 1)[1].split(
            "# A Controller-owned Excel PID", 1)[0].strip()
        self.assertEqual(actual, expected, "STOP and Controller workbook-exclusivity rules must match")

    def test_controller_workbook_close_never_kills_raw_numeric_excel_pid(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        branch = controller.split('Write-Status "Workbook close detected', 1)[1].split(
            "# Final tracked-PID verification", 1)[0]
        self.assertNotIn("Stop-Process", branch)
        self.assertIn("Stop-VerifiedOwnedExcel ([int]$state.excel_pid) $WorkbookPath $PID", branch)
        self.assertIn("Save-State $state", branch)
        self.assertIn("[Environment]::Exit(2)", branch)
        self.assertIn("if ($xp2.MainWindowHandle -ne 0", branch)

    def test_hidden_excel_orphan_pid_reuse_must_be_refused(self):
        """Release-blocking regression: no numeric PID termination for Excel."""
        src = self.source
        orphan = src.split("function Stop-VerifiedHiddenManagedExcelOrphan(", 1)[1].split(
            "function Close-VerifiedManagedExcelNoSave(", 1)[0]
        self.assertNotIn("Stop-Process -Id $ExcelPid", orphan)
        self.assertIn("$xp.Kill()", orphan)
        self.assertIn("$xp.WaitForExit(5000)", orphan)
        self.assertIn("$xp.StartTime.ToUniversalTime()", orphan)
        self.assertIn("([datetime]$info.CreationDate).ToUniversalTime()", orphan)
        self.assertIn("$info.ParentProcessId", orphan)
        self.assertIn("$ExpectedStartUtc", orphan)
        self.assertIn("$ExpectedControllerPid", orphan)

    def test_excel_quit_refuses_another_workbook_in_same_pid(self):
        src = self.source
        guard = src.split("function Test-OnlyCanonicalExcelWorkbookOpen(", 1)[1].split(
            "function Test-NoExcelWorkbooksForPid(", 1)[0]
        self.assertIn("$books.Count -ne 1", guard)
        self.assertIn("[IO.Path]::GetFullPath($openPath)", guard)
        self.assertIn("[IO.Path]::GetFullPath($WorkbookPath)", guard)
        close = src.split("function Close-VerifiedManagedExcelNoSave(", 1)[1].split(
            "# P0-25:", 1)[0]
        self.assertIn("Test-OnlyCanonicalExcelWorkbookOpen $app $WorkbookPath", close)
        self.assertLess(close.index("Test-OnlyCanonicalExcelWorkbookOpen $app $WorkbookPath"),
                        close.index("$targetBook.Close($false)"))
        self.assertLess(close.index("$targetBook.Close($false)"),
                        close.index("if (@($app.Workbooks).Count -ne 0) { return $false }"))
        self.assertLess(close.index("if (@($app.Workbooks).Count -ne 0) { return $false }"),
                        close.index("$app.Quit()"))
        self.assertNotIn("$app.DisplayAlerts = $false", close)

    def test_hidden_excel_orphan_needs_zero_workbook_com_evidence(self):
        src = self.source
        verify = src.split("function Test-NoExcelWorkbooksForPid(", 1)[1].split(
            "function Stop-VerifiedHiddenManagedExcelOrphan(", 1)[0]
        self.assertIn('GetActiveObject("Excel.Application")', verify)
        self.assertIn("GetWindowThreadProcessId", verify)
        self.assertIn("return (@($application.Workbooks).Count -eq 0)", verify)
        orphan = src.split("function Stop-VerifiedHiddenManagedExcelOrphan(", 1)[1].split(
            "function Close-VerifiedManagedExcelNoSave(", 1)[0]
        self.assertIn("Test-NoExcelWorkbooksForPid $ExcelPid", orphan)
        self.assertLess(orphan.index("Test-NoExcelWorkbooksForPid $ExcelPid"),
                        orphan.index("$xp.Kill()"))

    def test_workbook_close_retains_state_until_worker_and_listener_checks_pass(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        audit = controller.split("function Test-V10WorkbookCloseTeardownComplete(", 1)[1].split(
            "function Remove-V10VerifiedShutdownState(", 1)[0]
        self.assertIn("Get-CimInstance Win32_Process", audit)
        self.assertIn("Get-NetTCPConnection -State Listen -ErrorAction Stop", audit)
        self.assertIn("28584", audit)
        for field in ("watcher_pid", "collector_pid", "brain_gateway_pid",
                      "voice_bridge_pid", "sbv2_pid", "shadow_supervisor_pid",
                      "brain_observer_pid"):
            self.assertIn(field, audit)
        deletion = controller.split("function Remove-V10VerifiedShutdownState(", 1)[1].split(
            "function Start-Worker(", 1)[0]
        self.assertIn("ConvertFrom-Json -ErrorAction Stop", deletion)
        self.assertIn("[string]$disk.started_at -cne [string]$SessionState.started_at", deletion)
        self.assertIn("Test-V10WorkbookCloseTeardownComplete $SessionState", deletion)
        self.assertIn("Remove-Item -LiteralPath $StateFile -Force -ErrorAction Stop", deletion)
        self.assertIn("-not (Test-Path -LiteralPath $StateFile)", deletion)
        close = controller.split('Write-Status "Workbook close detected', 1)[1].split(
            "# Voice backend is presentation-only", 1)[0]
        self.assertIn("if (-not (Test-V10WorkbookCloseTeardownComplete $state))", close)
        self.assertIn("if (-not (Remove-V10VerifiedShutdownState $state))", close)
        self.assertIn("SAFE_STOP_VERIFY=WORKER_OR_PORT_REMAINS", close)
        self.assertIn("SAFE_STOP_VERIFY=STATE_REMOVAL_UNVERIFIED", close)
        self.assertNotIn("Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue", close)
        self.assertLess(close.index("Test-V10WorkbookCloseTeardownComplete $state"),
                        close.index("Remove-V10VerifiedShutdownState $state"))
        self.assertLess(close.index("Remove-V10VerifiedShutdownState $state"),
                        close.index("[Environment]::Exit(0)"))

    def test_excel_preflight_refuses_partial_teardown_before_controller_kill(self):
        src = self.source
        self.assertEqual(src.count("function Test-StopExcelPreflight("), 1)
        start = src.index("function Test-StopExcelPreflight(")
        end = src.index("# P0-25:", start)
        block = src[start:end]
        for marker in (
            "[string]$info.Name -ine \"EXCEL.EXE\"",
            "[int]$info.ParentProcessId -ne $controllerPid",
            "$proc.StartTime.ToUniversalTime()",
            "($started -",
            "$cmd.IndexOf($canonicalLaunch, [StringComparison]::OrdinalIgnoreCase)",
            "GetActiveObject(\"Excel.Application\")",
            "GetWindowThreadProcessId",
            "$otherExcel.Count -ne 0",
            "Test-OnlyCanonicalExcelWorkbookOpen $app $workbookPath",
        ):
            self.assertIn(marker, block)
        call = src.index("if (-not (Test-StopExcelPreflight $state))")
        controller_stop = src.index("$controllerProc.Kill()")
        bridge_stop = src.index("Stop-OwnedJobBridge 28580")
        self.assertLess(call, controller_stop)
        self.assertLess(call, bridge_stop)
        self.assertIn("SAFE_STOP_PREFLIGHT=BLOCKED_EXCEL_IDENTITY_OR_WORKBOOKS", src)
        self.assertNotIn("Stop-Process -Id $ExcelPid", block)

    def test_cim_pid_liveness_is_three_state_and_fail_closed(self):
        src = self.source
        evidence = src.split("function Get-V10TrackedPidEvidence(", 1)[1].split(
            "function Test-V10RecordedPidInventory(", 1)[0]
        self.assertIn("Get-CimInstance Win32_Process", evidence)
        self.assertIn("-ErrorAction Stop", evidence)
        self.assertIn('return "ABSENT"', evidence)
        self.assertIn('return "ALIVE"', evidence)
        self.assertIn('return "UNKNOWN"', evidence)
        self.assertIn("([datetime]$cim.CreationDate).ToUniversalTime()", evidence)
        self.assertIn("$process.Handle", evidence)
        inventory = src.split("function Test-V10RecordedPidInventory(", 1)[1].split(
            "function Stop-OwnedJobBridge(", 1)[0]
        self.assertIn("excel_pid", inventory)
        self.assertIn("brain_observer_pid", inventory)
        self.assertIn('Get-V10TrackedPidEvidence $id', inventory)
        preflight = src.index("if (-not (Test-V10RecordedPidInventory $state))")
        controller_kill = src.index("$controllerProc.Kill()")
        self.assertLess(preflight, controller_kill)
        after_controller = src.index("SAFE_STOP_VERIFY=LATEST_PID_OR_EXCEL_UNVERIFIED")
        bridge = src.index("Stop-OwnedJobBridge 28580")
        self.assertLess(controller_kill, after_controller)
        self.assertLess(after_controller, bridge)
        final = src.split("SAFE_STOP_VERIFY=LISTEN_PORTS_REMAIN", 1)[1]
        self.assertIn("Get-V10TrackedPidEvidence $tracked", final)
        self.assertIn('if ($evidence -ne "ABSENT")', final)
        self.assertIn("SAFE_STOP_VERIFY=STATE_CHANGED_BEFORE_DELETE", final)
        self.assertIn("excel_pid", final)

    def test_recovery_inspection_exits_before_any_destructive_stop(self):
        src = self.source
        self.assertIn("[switch]$InspectOnly", src)
        self.assertEqual(src.count("function Invoke-V10StopReadOnlyInspection("), 1)
        inspection = src.split("function Invoke-V10StopReadOnlyInspection(", 1)[1].split(
            "function Test-V10RecoveryStateInvariants(", 1)[0]
        for fragment in (
            "Get-V10TrackedPidEvidence $pidValue",
            "Test-StopExcelPreflight $RecordedState",
            "Test-ExactBrainHandle $opened $RecordedState",
            "Get-NetTCPConnection -State Listen -ErrorAction Stop",
            "AUTOMATIC_STATE_DELETION_ALLOWED=0",
            "STATE_MUTATED=0",
            "PROCESS_TERMINATED=0",
            "EXCEL_CLOSED=0",
            "RECOVERY_CLASS=STALE_STATE_REVIEW_REQUIRED",
            "RECOVERY_CLASS=REQUIRES_INDEPENDENT_REVIEW",
        ):
            self.assertIn(fragment, inspection)
        for destructive in (
            "Stop-Process", ".Kill()", "Remove-Item", "Save-State",
            "Move-Item", "Start-Process", "$targetBook.Close(", "$app.Quit()",
        ):
            self.assertNotIn(destructive, inspection)
        inspect_call = src.index("if ($InspectOnly) {\n    try {\n        $snapshotSha")
        self.assertLess(inspect_call, src.index("$controllerProc.Kill()"))
        self.assertLess(inspect_call, src.index("Stop-OwnedJobBridge 28580"))
        self.assertLess(inspect_call, src.index("Remove-Item -LiteralPath $StateFile -Force"))

    def test_recovery_archive_rejects_unverified_stale_state_and_preserves_evidence(self):
        src = self.source
        self.assertIn("[switch]$ArchiveVerifiedStaleState", src)
        self.assertIn("if ($InspectOnly -and $ArchiveVerifiedStaleState)", src)
        proof = src.split("function Test-V10RecoveryStateInvariants(", 1)[1].split(
            "function Invoke-V10VerifiedStaleArchive(", 1)[0]
        self.assertIn('Get-V10TrackedPidEvidence $id) -ne "ABSENT"', proof)
        self.assertIn('if ($field -in @("controller_pid","brain_observer_pid")', proof)
        self.assertIn("Get-NetTCPConnection -State Listen -ErrorAction Stop", proof)
        for port in ("28580", "28581", "28582", "28583", "28584"):
            self.assertIn(port, proof)
        self.assertIn("Kioxia_MS2_RSS_Live_Signals.xlsx", proof)
        archive = src.split("function Invoke-V10VerifiedStaleArchive(", 1)[1].split(
            "# P0-25: The legacy state", 1)[0]
        for guard in (
            "ExpectedSessionId -cne",
            "ExpectedStateSha256 -notmatch",
            "Get-V10RecoverySha256 $before",
            "Test-V10RecoveryStateInvariants $verified",
            "Get-V10RecoverySha256 ([IO.File]::ReadAllBytes($StateFile))",
            "[IO.File]::Move($StateFile,$target)",
            "Get-V10RecoverySha256 ([IO.File]::ReadAllBytes($target))",
            "RECOVERY_ARCHIVE=VERIFIED_ARCHIVED",
        ):
            self.assertIn(guard, archive)
        self.assertGreaterEqual(archive.count("Test-V10RecoveryStateInvariants $verified"), 2)
        for destructive in ("Stop-Process", ".Kill()", "$app.Quit()", "$targetBook.Close(",
                            "Remove-Item -LiteralPath $StateFile"):
            self.assertNotIn(destructive, archive)
        archive_dispatch = src.index("if ($ArchiveVerifiedStaleState) {\n    exit (Invoke-V10VerifiedStaleArchive $state)")
        controller_kill = src.index("$controllerProc.Kill()")
        self.assertLess(archive_dispatch, controller_kill)

    def test_archive_rechecks_untracked_v10_processes_before_rename(self):
        src = self.source
        scan = src.split("function Test-NoUntrackedV10Process", 1)[1].split(
            "function Test-V10RecoveryStateInvariants", 1)[0]
        self.assertIn("Get-CimInstance Win32_Process -ErrorAction Stop", scan)
        for name in ("AI_COCKPIT_CONTROLLER_V10", "Kioxia_RSS_Live_Watcher",
                     "ai_brain_observer", "ai_shadow_supervisor"):
            self.assertIn(name, scan)
        self.assertNotIn(".Kill()", scan)
        self.assertNotIn("Stop-Process", scan)
        invariant = src.split("function Test-V10RecoveryStateInvariants", 1)[1].split(
            "function Invoke-V10VerifiedStaleArchive", 1)[0]
        self.assertIn("Test-NoUntrackedV10Process", invariant)
        archive = src.split("function Invoke-V10VerifiedStaleArchive", 1)[1].split(
            "# P0-25: The legacy state", 1)[0]
        self.assertIn("PRE_RENAME_PROCESS_OR_PORT_CHANGED", archive)
        self.assertGreaterEqual(archive.count("Test-V10RecoveryStateInvariants $verified"), 3)
        self.assertLess(archive.index("PRE_RENAME_PROCESS_OR_PORT_CHANGED"),
                        archive.index("[IO.File]::Move($StateFile,$target)"))

    def test_controller_and_stop_share_exclusive_lifecycle_mutex(self):
        controller = (STOP.parent / "AI_COCKPIT_CONTROLLER_V10.ps1").read_text(encoding="utf-8-sig")
        start_marker = "function Get-V10RecoveryMutexName([string]$StateRoot) {"
        self.assertEqual(controller.count(start_marker), 1)
        self.assertEqual(self.source.count(start_marker), 1)
        a = controller.split(start_marker, 1)[1].split("$V10LifecycleMutex =", 1)[0].strip()
        b = self.source.split(start_marker, 1)[1].split("function Invoke-V10VerifiedStaleArchive", 1)[0].strip()
        self.assertEqual(a, b, "STOP and Controller must compute same root-scoped mutex name")
        self.assertIn("$V10LifecycleMutex.WaitOne(0)", controller)
        self.assertLess(controller.index("$V10LifecycleMutex.WaitOne(0)"),
                        controller.index("Stop-OwnedFromPreviousState\n    Start-Sleep"))
        archive = self.source.split("function Invoke-V10VerifiedStaleArchive(", 1)[1].split(
            "if ($ArchiveVerifiedStaleState) {\n    exit", 1)[0]
        self.assertIn("$mutex.WaitOne(0)", archive)
        self.assertIn('throw "V10_LIFECYCLE_LOCK_BUSY"', archive)
        self.assertIn("$mutex.ReleaseMutex()", archive)
        self.assertIn("$mutex.Dispose()", archive)
        self.assertLess(archive.index("$mutex.WaitOne(0)"),
                        archive.index("Test-V10RecoveryStateInvariants $verified"))
        self.assertLess(archive.index("[IO.File]::Move($StateFile,$target)"),
                        archive.index("$mutex.ReleaseMutex()"))

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
