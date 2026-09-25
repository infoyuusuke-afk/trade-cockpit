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

    def test_controller_receives_the_verified_branch(self):
        self.assertIn("-ExpectedBranch $Branch", self.runner)


if __name__ == "__main__":
    unittest.main()
