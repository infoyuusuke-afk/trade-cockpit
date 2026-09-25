"""Structural safety contract for the V8 Controller/Gateway/Stop scripts
(downloads/AI_COCKPIT_CONTROLLER_V8.ps1, AI_COCKPIT_GATEWAY_V8.ps1,
STOP_AI_COCKPIT_V8.ps1, RUN_AI_COCKPIT_V8.ps1).

These are PowerShell scripts that manage real Windows processes (Excel,
MarketSpeed II RSS watcher/collector/heartbeat) on the user's own machine
during live market hours, so they cannot be executed against real
processes as part of this test suite. Instead this file checks, by
reading the source, for the exact anti-patterns identified in the draft
PR #262 audit (2026-09-25) and the properties the 2026-09-25 P0 direction
required - the same technique already used for
tests/test_watchdog_powershell_lifecycle_contract.py.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "downloads"
MS2_LIVE = ROOT / "ms2_live"


def read(name: str) -> str:
    return (DOWNLOADS / name).read_text(encoding="utf-8")


def extract_function(text: str, func_name: str) -> str:
    """Extract a top-level `function <func_name> { ... }` block by finding
    the line the function starts on and the line the *next* top-level
    `function `/`$repo = ` starts on - robust against nested braces that
    trip up a naive `.*?\\n}` regex."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"function {func_name}"))
    end = next(
        i for i in range(start + 1, len(lines))
        if lines[i].startswith("function ") or lines[i].startswith("$repo = ")
    )
    return "\n".join(lines[start:end])


class ControllerSafetyContract(unittest.TestCase):
    def setUp(self):
        self.controller = read("AI_COCKPIT_CONTROLLER_V8.ps1")

    def test_never_kills_excel_by_broad_window_heuristic(self):
        # The exact bug found in the PR #262 draft: killing any EXCEL.EXE
        # with MainWindowHandle -eq 0 (or a title match) during routine
        # startup cleanup, regardless of whether this controller started
        # it. Must not appear anywhere in the controller.
        self.assertNotRegex(
            self.controller,
            r"Get-Process\s+EXCEL[^\n]*\n[^\n]*MainWindowHandle\s*-eq\s*0[^\n]*\n[^\n]*Stop-Process",
        )
        # Excel is only ever stopped through the tracked $state.excel_pid.
        stop_excel_lines = [
            line for line in self.controller.splitlines() if "Stop-Process" in line and "excel" in line.lower()
        ]
        for line in stop_excel_lines:
            self.assertIn("state.excel_pid", line)

    def test_startup_cleanup_stops_only_own_previous_pids(self):
        self.assertIn("Stop-OwnedFromPreviousState", self.controller)
        func_match = re.search(
            r"function Stop-OwnedFromPreviousState \{(.*?)\n\}", self.controller, re.S
        )
        self.assertIsNotNone(func_match)
        body = func_match.group(1)
        self.assertIn("Read-State", body)
        self.assertNotIn("Get-CimInstance Win32_Process", body)
        self.assertNotIn("Where-Object", body)  # no broad process-table filtering

    def test_no_wait_exceeds_45_seconds(self):
        waits = re.findall(r"Wait-PortBounded\s+\d+\s+(\d+)", self.controller)
        waits += re.findall(r"AddSeconds\((\d+)\)", self.controller)
        self.assertTrue(waits, "expected at least one bounded wait")
        for w in waits:
            self.assertLessEqual(int(w), 45, f"wait of {w}s exceeds the 45s ceiling")

    def test_collector_failure_does_not_exit_controller(self):
        # The supervision loop must handle a dead/never-ready Collector by
        # restarting it, never by throwing/exiting the whole controller.
        loop_match = re.search(
            r"while \(\$true\) \{(.*?)\n\} catch \{", self.controller, re.S
        )
        self.assertIsNotNone(loop_match)
        loop_body = loop_match.group(1)
        self.assertIn("collector_status", loop_body)
        collector_section = loop_body.split("# 2)")[1].split("# 3)")[0]
        self.assertNotIn("throw", collector_section)
        self.assertIn("Start-Worker", collector_section)

    def test_error_path_keeps_window_open_and_shows_log_location(self):
        catch_match = re.search(r"\} catch \{(.*)\Z", self.controller, re.S)
        self.assertIsNotNone(catch_match)
        body = catch_match.group(1)
        self.assertIn("Read-Host", body)
        self.assertIn("LogDir", body)
        self.assertIn("StateFile", body)

    def test_all_child_workers_redirect_stdout_and_stderr(self):
        self.assertIn("RedirectStandardOutput", self.controller)
        self.assertIn("RedirectStandardError", self.controller)

    def test_no_hardcoded_personal_desktop_path(self):
        # The exact PR #262 problem: a personal absolute path baked in as
        # a script default, committed to the public repo.
        for script_name in (
            "AI_COCKPIT_CONTROLLER_V8.ps1",
            "AI_COCKPIT_GATEWAY_V8.ps1",
            "RUN_AI_COCKPIT_V8.ps1",
            "STOP_AI_COCKPIT_V8.ps1",
        ):
            text = read(script_name)
            self.assertNotIn(r"C:\Users\yusuk", text, script_name)

    def test_port_map_is_fixed_and_distinct(self):
        self.assertIn("$PORT_COLLECTOR = 28580", self.controller)
        self.assertIn("$PORT_GATEWAY = 28581", self.controller)
        self.assertIn("$PORT_WATCHER = 28582", self.controller)

    def test_foreign_session_preflight_runs_before_anything_is_started(self):
        self.assertIn("Test-ForeignSession", self.controller)
        preflight_idx = self.controller.index("Test-ForeignSession $ownedNow")
        gateway_start_idx = self.controller.index('Start-Worker -Name "gateway"')
        self.assertLess(preflight_idx, gateway_start_idx)
        # A hit must stop startup (throw), not just warn.
        block = self.controller[preflight_idx:gateway_start_idx]
        self.assertIn("throw", block)
        self.assertIn("FOREIGN SESSION DETECTED", block)

    def test_foreign_session_never_auto_kills_the_other_process(self):
        func_match = re.search(
            r"function Test-ForeignSession.*?\n\}", self.controller, re.S
        )
        self.assertIsNotNone(func_match)
        self.assertNotIn("Stop-Process", func_match.group(0))

    def test_watcher_and_heartbeat_are_supervised_in_the_loop(self):
        loop_match = re.search(
            r"while \(\$true\) \{(.*?)\n\} catch \{", self.controller, re.S
        )
        self.assertIsNotNone(loop_match)
        loop_body = loop_match.group(1)
        self.assertIn("state.watcher_pid", loop_body)
        self.assertIn("state.heartbeat_pid", loop_body)
        self.assertIn('$state.watcher_status = "DOWN"', loop_body)
        self.assertIn('$state.heartbeat_status = "DOWN"', loop_body)
        # Neither death path may throw/exit - restart only.
        watcher_section = loop_body.split("# 2)")[1].split("# 3)")[0]
        heartbeat_section = loop_body.split("# 3)")[1].split("# 4)")[0]
        self.assertNotIn("throw", watcher_section)
        self.assertNotIn("throw", heartbeat_section)
        self.assertIn("Start-Worker", watcher_section)
        self.assertIn("Start-Worker", heartbeat_section)

    def test_excel_workbook_identity_is_verified_via_com_fullname(self):
        self.assertIn("GetActiveObject", self.controller)
        self.assertIn(".FullName -ine $WorkbookPath", self.controller)
        self.assertIn("workbook_identity_verified", self.controller)

    def test_single_canonical_workbook_path_only(self):
        # The exact PR #262-adjacent risk this addresses: V6/V7 opened
        # $Root\Excel\<name>.xlsx while Watcher/Collector operate on
        # $RuntimeDir\<name>.xlsx - two different files with the same
        # name. The controller must only ever reference the RuntimeDir copy.
        self.assertNotIn(r"Root ""Excel", self.controller.replace("\\", "").replace("'", '"'))
        self.assertEqual(self.controller.count("$WorkbookPath ="), 1)
        self.assertIn('Join-Path $RuntimeDir "Kioxia_MS2_RSS_Live_Signals.xlsx"', self.controller)

    def test_branch_is_verified_before_startup_when_expected(self):
        self.assertIn("ExpectedBranch", self.controller)
        verify_idx = self.controller.index("if (-not [string]::IsNullOrWhiteSpace($ExpectedBranch))")
        gateway_start_idx = self.controller.index('Start-Worker -Name "gateway"')
        self.assertLess(verify_idx, gateway_start_idx)
        block = self.controller[verify_idx:gateway_start_idx]
        self.assertIn("throw", block)

    def test_never_assumes_repo_update_means_runtime_update(self):
        # 2026-09-25 blocker fix: the controller must independently verify
        # RuntimeDir's actual files against V8_RUNTIME.json before
        # starting Watcher/Heartbeat/Collector from there - never assume a
        # successful repo checkout implies RuntimeDir was also updated.
        self.assertIn("V8_RUNTIME.json", self.controller)
        manifest_idx = self.controller.index('Join-Path $Root "V8_RUNTIME.json"')
        watcher_start_idx = self.controller.index('Start-Worker -Name "watcher"')
        self.assertLess(manifest_idx, watcher_start_idx)
        block = self.controller[manifest_idx:watcher_start_idx]
        self.assertIn("No V8_RUNTIME.json found", block)
        self.assertIn("Get-FileHash", block)
        self.assertIn("does not match the deployed manifest", block)
        for name in (
            "Kioxia_RSS_Live_Watcher.ps1",
            "Kioxia_Safety_Heartbeat.ps1",
            "MS2_RSS_100_Collector.ps1",
        ):
            self.assertIn(name, block)


class WatcherPortContract(unittest.TestCase):
    """Watcher and the Gateway both used to hardcode port 28581 -
    Watcher's own local JSON bridge for kioxia_watcher_live.json silently
    collided with the Gateway serving the whole page on the same port.
    Moved Watcher's bridge to 28582, which is also what the Controller now
    supervises as Watcher's own liveness port."""

    def test_watcher_uses_its_own_port_not_the_gateways(self):
        watcher = (MS2_LIVE / "Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8")
        self.assertIn("Start-LocalJsonBridge $watcherJsonPath 28582", watcher)
        self.assertNotIn("Start-LocalJsonBridge $watcherJsonPath 28581", watcher)

    def test_frontend_fetches_watcher_bridge_on_new_port(self):
        update_py = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:28582/kioxia_watcher_live.json", update_py)
        self.assertNotIn("127.0.0.1:28581/kioxia_watcher_live.json", update_py)

    def test_collector_and_gateway_ports_are_unaffected(self):
        collector = (MS2_LIVE / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8")
        self.assertIn("28580", collector)
        gateway = read("AI_COCKPIT_GATEWAY_V8.ps1")
        self.assertIn("28581", gateway)


class GatewaySafetyContract(unittest.TestCase):
    def setUp(self):
        self.gateway = read("AI_COCKPIT_GATEWAY_V8.ps1")

    def test_serves_local_repo_not_a_remote_proxy(self):
        # The actual root cause of "cards not reflected": the old gateway
        # proxied every page from the public GitHub Pages site. V8 must
        # serve files from disk instead.
        self.assertNotIn("RemoteBase", self.gateway)
        self.assertNotIn("github.io", self.gateway)
        self.assertNotIn("raw.githubusercontent.com", self.gateway)
        self.assertIn("RepoRoot", self.gateway)

    def test_health_reports_build_identity(self):
        health_match = re.search(r"health.*?ConvertTo-Json", self.gateway, re.S)
        self.assertIsNotNone(health_match)
        body = health_match.group(0)
        self.assertIn("ui_branch", body)
        self.assertIn("ui_sha", body)
        self.assertIn("ui_build", body)

    def test_no_store_on_every_response(self):
        self.assertIn("Cache-Control: no-store", self.gateway)
        # Send-Response is the single response path; no-store must be in it.
        send_match = re.search(r"function Send-Response.*?\n\}", self.gateway, re.S)
        self.assertIsNotNone(send_match)
        self.assertIn("no-store", send_match.group(0))

    def test_path_traversal_is_rejected(self):
        self.assertIn(r"\.\.", self.gateway)
        self.assertIn("GetFullPath", self.gateway)
        self.assertIn("StartsWith", self.gateway)

    def test_no_hardcoded_personal_desktop_path(self):
        self.assertNotIn(r"C:\Users\yusuk", self.gateway)

    def test_health_defaults_to_fail_closed_on_unknown_state(self):
        # fail_closed must default true and only flip false when watcher/
        # heartbeat/collector are all explicitly confirmed - never the
        # other way around (never defaults to "assume healthy").
        runtime_match = re.search(r"\$runtime = \[ordered\]@\{(.*?)\n\}", self.gateway, re.S)
        self.assertIsNotNone(runtime_match)
        runtime_block = runtime_match.group(1)
        self.assertIn("fail_closed", runtime_block)
        self.assertRegex(runtime_block, r"fail_closed\s*=\s*\$true")
        compute_match = re.search(r"runtime\.fail_closed = -not \((.*?)\)", self.gateway, re.S)
        self.assertIsNotNone(compute_match)
        condition = compute_match.group(1)
        self.assertIn('watcher_status -eq "LIVE"', condition)
        self.assertIn('heartbeat_status -eq "RUNNING"', condition)
        self.assertIn('collector_status -eq "LIVE"', condition)


class StopScriptSafetyContract(unittest.TestCase):
    def setUp(self):
        self.stop = read("STOP_AI_COCKPIT_V8.ps1")

    def test_stops_only_tracked_state_pids(self):
        self.assertNotIn("Get-CimInstance Win32_Process", self.stop)
        self.assertNotIn("ProcessName -match", self.stop)
        self.assertIn("V8_CONTROLLER_STATE.json", self.stop)

    def test_never_force_closes_excel_directly(self):
        self.assertNotIn("Stop-Process -Id $excelPid", self.stop)


class RunnerContract(unittest.TestCase):
    def setUp(self):
        self.runner = read("RUN_AI_COCKPIT_V8.ps1")

    def test_backs_up_before_overwriting_state(self):
        self.assertIn("backup", self.runner.lower())
        self.assertIn("Move-Item", self.runner)

    def test_updates_then_starts_controller_in_one_script(self):
        update_idx = self.runner.find("git fetch")
        start_idx = self.runner.find("AI_COCKPIT_CONTROLLER_V8.ps1")
        self.assertGreater(update_idx, -1)
        self.assertGreater(start_idx, -1)
        self.assertLess(update_idx, start_idx)

    def test_branch_defaults_to_the_pinned_reviewed_branch_not_implicit_current(self):
        self.assertIn(
            '[string]$Branch = "integration/v7-runtime-and-cards"', self.runner
        )

    def test_git_failures_are_fatal_not_continue_as_is(self):
        self.assertNotIn("continuing with the checkout as-is", self.runner)
        self.assertIn("Invoke-GitFatal", self.runner)
        fatal_match = re.search(r"function Invoke-GitFatal.*?\n\}", self.runner, re.S)
        self.assertIsNotNone(fatal_match)
        self.assertIn("throw", fatal_match.group(0))

    def test_branch_and_sha_are_verified_after_checkout(self):
        self.assertIn("Branch mismatch after checkout", self.runner)
        self.assertIn("SHA mismatch after checkout", self.runner)

    def test_deploys_runtime_files_not_just_repo_checkout(self):
        # 2026-09-25 blocker: repo checkout != RuntimeDir. All three
        # scripts the Controller actually launches from RuntimeDir must be
        # deployed there before Controller starts.
        for name in (
            "Kioxia_RSS_Live_Watcher.ps1",
            "Kioxia_Safety_Heartbeat.ps1",
            "MS2_RSS_100_Collector.ps1",
        ):
            self.assertIn(name, self.runner)
        deploy_idx = self.runner.find("Deploy-RuntimeFiles -RepoRoot")
        controller_start_idx = self.runner.find("Starting Controller V8")
        self.assertGreater(deploy_idx, -1)
        self.assertGreater(controller_start_idx, -1)
        self.assertLess(deploy_idx, controller_start_idx)

    def test_deploy_validates_before_touching_anything_real(self):
        body = extract_function(self.runner, "Deploy-RuntimeFiles")
        self.assertIn("Test-PowerShellSyntaxOk", body)
        self.assertIn("Get-Sha256Hex", body)
        # Validation (phase 1) must happen inside a try whose catch cleans
        # up every staged file, including the one that failed - not just
        # the ones that made it into $staged.
        self.assertIn("$allStagedPaths", body)
        self.assertIn("foreach ($stagedPath in $allStagedPaths)", body)

    def test_deploy_is_all_or_nothing_with_backup(self):
        body = extract_function(self.runner, "Deploy-RuntimeFiles")
        # Backup happens only in phase 2, after every file already passed
        # validation in phase 1 - a single bad file must never produce a
        # partial deploy or an unnecessary backup.
        backup_idx = body.find("_v8_runtime_backups")
        move_idx = body.find("Move-Item -LiteralPath $entry.staged_path")
        catch_idx = body.find("} catch {")
        self.assertGreater(catch_idx, -1)
        self.assertGreater(backup_idx, catch_idx)
        self.assertGreater(move_idx, backup_idx)

    def test_deploy_verifies_deployed_ports_not_just_source(self):
        body = extract_function(self.runner, "Deploy-RuntimeFiles")
        self.assertIn("28582", body)
        self.assertIn("28580", body)
        # Must read back the file that was just written to RuntimeDir, not
        # re-check the source in the repo (as explicit UTF-8, not
        # Get-Content -Raw - see JsonEncodingContract).
        self.assertIn('[IO.File]::ReadAllText((Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1")', body)
        self.assertIn('[IO.File]::ReadAllText((Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1")', body)

    def test_writes_runtime_manifest_with_required_fields(self):
        self.assertIn("V8_RUNTIME.json", self.runner)
        manifest_match = re.search(
            r"\$runtimeManifest = \[ordered\]@\{(.*?)\n\}", self.runner, re.S
        )
        self.assertIsNotNone(manifest_match)
        body = manifest_match.group(1)
        for field in ("repo_sha", "runtime_dir", "files", "deployed_at"):
            self.assertIn(field, body)

    def test_controller_receives_the_verified_branch(self):
        self.assertIn("-ExpectedBranch $Branch", self.runner)


class JsonEncodingContract(unittest.TestCase):
    """2026-09-25: the first real-machine run of RUN_AI_COCKPIT_V8.ps1
    deployed successfully (V8_RUNTIME.json was written) but the Controller
    then failed to start, because `Get-Content -Raw | ConvertFrom-Json`
    does not reliably treat a BOM-less UTF-8 file as UTF-8 under Windows
    PowerShell 5.1 - it can silently fall back to the system ANSI codepage
    (Shift-JIS on this machine), corrupting the Japanese RuntimeDir path
    (デイトレ -> 繝・う繝医Ξ) on read-back, which then failed the
    runtime_dir equality check and stopped the Controller. Reproduced and
    confirmed fixed interactively (not part of this suite, since it needs
    real Windows PowerShell 5.1 behavior): `[IO.File]::ReadAllText(path,
    [Text.Encoding]::UTF8)` round-trips the same Japanese path correctly
    where `Get-Content -Raw | ConvertFrom-Json` corrupted it.

    These tests only confirm every JSON (and the two runtime-deploy text)
    reads in the shipped scripts go through the fixed path - not the
    Windows-specific encoding behavior itself.
    """

    def test_no_script_reads_json_via_bare_get_content_raw(self):
        for script_name in (
            "AI_COCKPIT_CONTROLLER_V8.ps1",
            "AI_COCKPIT_GATEWAY_V8.ps1",
            "STOP_AI_COCKPIT_V8.ps1",
        ):
            text = read(script_name)
            self.assertNotRegex(
                text,
                r"Get-Content[^\n]*-Raw[^\n]*\|\s*ConvertFrom-Json",
                f"{script_name} still reads JSON via the unfixed pattern",
            )

    def test_controller_and_gateway_define_read_json_utf8_helper(self):
        for script_name in ("AI_COCKPIT_CONTROLLER_V8.ps1", "AI_COCKPIT_GATEWAY_V8.ps1"):
            text = read(script_name)
            self.assertIn("function Read-JsonUtf8", text)
            helper = extract_function(text, "Read-JsonUtf8")
            self.assertIn("[IO.File]::ReadAllText", helper)
            self.assertIn("[Text.Encoding]::UTF8", helper)

    def test_controller_state_and_manifest_reads_use_the_helper(self):
        controller = read("AI_COCKPIT_CONTROLLER_V8.ps1")
        read_state = extract_function(controller, "Read-State")
        self.assertIn("Read-JsonUtf8", read_state)
        self.assertNotIn("Get-Content", read_state)
        manifest_read_idx = controller.index("$runtimeManifest = ")
        manifest_read_line = controller[manifest_read_idx:controller.index("\n", manifest_read_idx)]
        self.assertIn("Read-JsonUtf8", manifest_read_line)

    def test_gateway_state_read_uses_the_helper(self):
        gateway = read("AI_COCKPIT_GATEWAY_V8.ps1")
        self.assertIn("$st = Read-JsonUtf8 $controllerStateFile", gateway)

    def test_stop_script_state_read_is_explicit_utf8(self):
        stop = read("STOP_AI_COCKPIT_V8.ps1")
        self.assertIn(
            "[IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json",
            stop,
        )

    def test_runner_deploy_verification_reads_are_explicit_utf8(self):
        runner = read("RUN_AI_COCKPIT_V8.ps1")
        body = extract_function(runner, "Deploy-RuntimeFiles")
        code_lines = [
            line for line in body.splitlines() if not line.strip().startswith("#")
        ]
        self.assertFalse(any("Get-Content" in line for line in code_lines))
        self.assertIn(
            '[IO.File]::ReadAllText((Join-Path $RuntimeDir "Kioxia_RSS_Live_Watcher.ps1"), [Text.Encoding]::UTF8)',
            body,
        )
        self.assertIn(
            '[IO.File]::ReadAllText((Join-Path $RuntimeDir "MS2_RSS_100_Collector.ps1"), [Text.Encoding]::UTF8)',
            body,
        )


class VoiceIntegrationContract(unittest.TestCase):
    """2026-09-25 P0 Voice統合: replaces window.speechSynthesis with
    Style-Bert-VITS2 (SBV2) via a dedicated Voice Bridge process (28583),
    supervised the same way as Watcher/Heartbeat/Collector. Checks the
    explicit requirements: non-blocking SBV2 check, no browser-speech
    fallback anywhere in the new path, voice OFF generates nothing, and
    voice generation runs on its own port so it can never stall
    28580/28581/28582."""

    def setUp(self):
        self.controller = read("AI_COCKPIT_CONTROLLER_V8.ps1")
        self.gateway = read("AI_COCKPIT_GATEWAY_V8.ps1")
        self.stop = read("STOP_AI_COCKPIT_V8.ps1")
        self.voice_bridge = read("AI_COCKPIT_VOICE_BRIDGE_V8.ps1")
        self.update_py = (ROOT / "scripts" / "update.py").read_text(encoding="utf-8")

    def test_voice_bridge_port_is_distinct_from_the_other_three(self):
        self.assertIn("$PORT_VOICE_BRIDGE = 28583", self.controller)
        for other in ("28580", "28581", "28582"):
            self.assertNotEqual("28583", other)

    def test_sbv2_check_is_bounded_and_never_blocks_startup(self):
        func = extract_function(self.controller, "Test-Sbv2Ready")
        self.assertIn("-TimeoutSec 2", func)
        # SBV2 check/launch happens AFTER Collector's own bounded wait
        # completes and AFTER Gateway is already serving the UI - it must
        # never be positioned before Gateway starts, which would make the
        # whole UI wait on it.
        gateway_start_idx = self.controller.index('Start-Worker -Name "gateway"')
        sbv2_check_idx = self.controller.index("Checking SBV2 voice engine status")
        self.assertGreater(sbv2_check_idx, gateway_start_idx)

    def test_sbv2_autostart_is_a_detached_background_process_not_awaited(self):
        # START_SBV2_API.ps1 itself can block for up to ~120s loading the
        # model - the Controller must launch it with Start-Process (fire
        # and forget) and keep going, never Wait-Process / block on it.
        start_idx = self.controller.index("Checking SBV2 voice engine status")
        voice_bridge_start_idx = self.controller.index('Start-Worker -Name "voicebridge"')
        block = self.controller[start_idx:voice_bridge_start_idx]
        self.assertIn("Start-Process", block)
        self.assertIn("START_SBV2_API", block)
        self.assertNotIn("Wait-Process", block)

    def test_voice_bridge_is_supervised_with_bounded_restart(self):
        loop_match = re.search(r"while \(\$true\) \{(.*?)\n\} catch \{", self.controller, re.S)
        self.assertIsNotNone(loop_match)
        loop_body = loop_match.group(1)
        self.assertIn("state.voice_bridge_pid", loop_body)
        vb_section = loop_body.split("# 6)")[1].split("# 7)")[0]
        self.assertNotIn("throw", vb_section)
        self.assertIn("Start-Worker", vb_section)
        self.assertIn("voiceBridgeRestartAttempts", vb_section)

    def test_voice_bridge_death_does_not_affect_other_workers(self):
        # The section that restarts Voice Bridge must not touch
        # watcher/collector/gateway process handling.
        loop_match = re.search(r"while \(\$true\) \{(.*?)\n\} catch \{", self.controller, re.S)
        loop_body = loop_match.group(1)
        vb_section = loop_body.split("# 6)")[1].split("# 7)")[0]
        for other_pid_field in ("state.watcher_pid", "state.collector_pid", "state.gateway_pid"):
            self.assertNotIn(other_pid_field, vb_section)

    def test_sbv2_poll_in_loop_is_throttled_not_every_tick(self):
        loop_match = re.search(r"while \(\$true\) \{(.*?)\n\} catch \{", self.controller, re.S)
        loop_body = loop_match.group(1)
        sbv2_section = loop_body.split("# 7)")[1]
        self.assertIn("lastSbv2Poll", sbv2_section)
        self.assertIn("30", sbv2_section)

    def test_voice_bridge_port_is_in_foreign_session_preflight(self):
        func = extract_function(self.controller, "Test-ForeignSession")
        self.assertIn("PORT_VOICE_BRIDGE", func)

    def test_voice_bridge_pid_is_stopped_on_previous_state_cleanup(self):
        func_match = re.search(r"function Stop-OwnedFromPreviousState \{(.*?)\n\}", self.controller, re.S)
        self.assertIsNotNone(func_match)
        self.assertIn("voice_bridge_pid", func_match.group(1))

    def test_state_has_voice_fields(self):
        for field in ("sbv2_status", "voice_bridge_pid", "voice_bridge_status"):
            self.assertIn(field, self.controller)

    def test_gateway_health_reports_voice_fields(self):
        health_match = re.search(r"health.*?ConvertTo-Json", self.gateway, re.S)
        self.assertIsNotNone(health_match)
        body = health_match.group(0)
        self.assertIn("voice_backend", body)
        self.assertIn("sbv2_status", body)
        self.assertIn("voice_bridge_status", body)

    def test_stop_script_stops_voice_bridge_too(self):
        self.assertIn("voice_bridge_pid", self.stop)

    def test_voice_bridge_never_falls_back_to_other_tts(self):
        # No SAPI/System.Speech/browser-speech references in live (non-
        # comment) code - SBV2 unreachable must mean silence (503), never
        # a substitute voice. Comments are allowed to explain this in
        # words (e.g. "does not fall back to ... speechSynthesis").
        code_lines = [
            line for line in self.voice_bridge.splitlines() if not line.strip().startswith("#")
        ]
        code_text = "\n".join(code_lines)
        for banned in ("System.Speech", "SAPI", "SpeechSynthesizer", "speechSynthesis"):
            self.assertNotIn(banned, code_text)
        self.assertIn("503 Service Unavailable", self.voice_bridge)
        self.assertIn("sbv2_unreachable", self.voice_bridge)

    def test_voice_bridge_reuses_the_same_profile_table(self):
        func = extract_function(self.voice_bridge, "Get-VoiceProfile")
        for level, length in (("HOT", "1.03"), ("DANGER", "1.10"), ("WATCH", "1.13")):
            self.assertIn(level, func)
            self.assertIn(length, func)

    def test_voice_bridge_normalization_order_preserves_vwap_up_down_before_bare_vwap(self):
        func = extract_function(self.voice_bridge, "Convert-ToSpeechText")
        vwap_up_idx = func.index('"VWAP上"')
        vwap_down_idx = func.index('"VWAP下"')
        vwap_bare_idx = func.index('"VWAP"')
        self.assertLess(vwap_up_idx, vwap_bare_idx)
        self.assertLess(vwap_down_idx, vwap_bare_idx)

    def test_frontend_has_no_browser_speech_synthesis_in_live_code(self):
        # SpeechSynthesisUtterance must be gone entirely; the only
        # remaining mention of speechSynthesis, if any, must be inside a
        # comment explaining that the old path was removed - never live code.
        self.assertNotIn("SpeechSynthesisUtterance", self.update_py)
        for line in self.update_py.splitlines():
            stripped = line.strip()
            if "speechSynthesis" in line:
                self.assertTrue(
                    stripped.startswith("//") or stripped.startswith("#"),
                    f"non-comment line still references speechSynthesis: {line}",
                )

    def test_frontend_cockpit_speak_posts_to_voice_bridge(self):
        self.assertIn("VOICE_BRIDGE_URL", self.update_py)
        self.assertIn("127.0.0.1:28583", self.update_py)
        self.assertIn('VOICE_BRIDGE_URL+"/speak"', self.update_py)
        self.assertIn('method:"POST"', self.update_py)

    def test_frontend_voice_off_generates_nothing(self):
        speak_idx = self.update_py.index("window.cockpitSpeak=(msg,level)=>{")
        first_return_idx = self.update_py.index("return;", speak_idx)
        guard_block = self.update_py[speak_idx:first_return_idx]
        self.assertIn("!voiceOn", guard_block)

    def test_frontend_shows_voice_offline_without_reviving_old_voice(self):
        self.assertIn("cockpitVoiceOffline", self.update_py)
        self.assertIn("VOICE OFFLINE", self.update_py)

    def test_frontend_kioxia_and_scalp_alerts_pass_a_level(self):
        self.assertIn('window.cockpitSpeak?.(k.voice_message,k.signal_type', self.update_py)
        self.assertIn('level:"HOT"', self.update_py)
        self.assertIn('level:"DANGER"', self.update_py)


if __name__ == "__main__":
    unittest.main()
