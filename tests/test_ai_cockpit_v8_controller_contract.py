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


if __name__ == "__main__":
    unittest.main()
