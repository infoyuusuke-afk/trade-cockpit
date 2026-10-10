"""U0-G contracts for bounded diagnostics and sanitized preflight."""

from __future__ import annotations

import pathlib
import re
import unittest

from tests.test_v10_identity_diagnostics import function_body


ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTROLLER_PATH = "downloads/AI_COCKPIT_CONTROLLER_V10.ps1"
PREFLIGHT_PATH = "downloads/AI_COCKPIT_PREFLIGHT_V10.ps1"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class V10BoundedDiagnosticsContract(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = read(CONTROLLER_PATH)
        self.preflight = read(PREFLIGHT_PATH)

    def test_timeout_budget_is_finite_and_below_nominal_loop_interval(self) -> None:
        match = re.search(
            r"\$IDENTITY_DIAGNOSTICS_TIMEOUT_MS\s*=\s*(\d+)", self.controller
        )
        self.assertIsNotNone(match)
        self.assertGreater(int(match.group(1)), 0)
        self.assertLess(int(match.group(1)), 2000)

    def test_timeout_returns_unknown_and_stops_only_owned_worker(self) -> None:
        body = function_body(CONTROLLER_PATH, "Invoke-BoundedIdentityDiagnostics")
        self.assertIn("$worker.WaitForExit($remainingMs)", body)
        self.assertIn('New-UnknownIdentityDiagnostics "DIAGNOSTIC_TIMEOUT"', body)
        self.assertIn("Stop-Process -Id $worker.Id", body)
        self.assertNotRegex(body, r"Stop-Process\s+-Name|Get-Process\s+.*Stop-Process")

    def test_worker_is_short_lived_and_runs_before_production_initialization(self) -> None:
        worker_gate = self.controller.index("if ($IdentityDiagnosticsWorker)")
        state_initialization = self.controller.index(
            '$StateFile = Join-Path $Root "V10_CONTROLLER_STATE.json"'
        )
        self.assertLess(worker_gate, state_initialization)
        self.assertIn("exit 0", self.controller[worker_gate:state_initialization])
        body = function_body(CONTROLLER_PATH, "Invoke-BoundedIdentityDiagnostics")
        self.assertIn("Start-Process", body)
        self.assertNotIn("Start-Job", body)

    def test_supervision_uses_bounded_wrapper_without_control_branching(self) -> None:
        loop_start = self.controller.index(
            "while ($true)",
            self.controller.index("# ---------------------------------------------------- supervision loop"),
        )
        loop = self.controller[loop_start:]
        self.assertIn("Invoke-BoundedIdentityDiagnostics", loop)
        self.assertNotIn("Update-IdentityDiagnostics $state", loop)
        assignment = re.search(
            r'\$state\["identity_diagnostics"\]\s*=\s*'
            r"Invoke-BoundedIdentityDiagnostics",
            loop,
        )
        self.assertIsNotNone(assignment)
        nearby = loop[assignment.start() : assignment.start() + 700]
        self.assertNotRegex(
            nearby,
            r"Stop-Process|Start-Worker|restart|real_submit_allowed",
        )

    def test_benchmark_covers_normal_abnormal_exception_and_timeout(self) -> None:
        start = self.controller.index(
            "function Invoke-BoundedIdentityDiagnosticsBenchmark"
        )
        end = self.controller.index("function Test-OwnedPidIdentity", start)
        body = self.controller[start:end]
        for token in (
            "bounded_normal",
            "bounded_missing_processes_and_ports",
            "bounded_malformed_manifest",
            "forced_timeout",
            "timeout_returns_unknown",
            "surviving_worker_count",
            "5000",
        ):
            self.assertIn(token, body)

    def test_preflight_uses_raw_sha256_and_five_port_allowlist(self) -> None:
        body = function_body(PREFLIGHT_PATH, "New-SanitizedPreflight")
        self.assertIn("Get-FileHash", body)
        self.assertIn("-Algorithm SHA256", body)
        self.assertIn("28580..28584", body)
        for path in (
            "downloads/RUN_AI_COCKPIT_V10.ps1",
            "downloads/AI_COCKPIT_CONTROLLER_V10.ps1",
            "downloads/AI_COCKPIT_GATEWAY_V10.ps1",
        ):
            self.assertIn(path, body)

    def test_preflight_unknown_and_fail_are_not_promoted_to_verified(self) -> None:
        body = function_body(PREFLIGHT_PATH, "New-SanitizedPreflight")
        for reason in (
            "DEPLOYED_SHA_UNVERIFIED",
            "ARTIFACT_IDENTITY_",
            "CONTROLLER_IDENTITY_FAIL",
            "CONTROLLER_IDENTITY_UNKNOWN",
            "PORT_IDENTITY_FAIL",
            "PORT_IDENTITY_UNKNOWN",
            "UI_BASELINE_UNVERIFIED",
        ):
            self.assertIn(reason, body)
        self.assertRegex(
            body,
            r'\$overall\s*=\s*if\s*\(\$hasFail\)\s*\{\s*"FAIL"\s*\}'
            r'\s*elseif\s*\(\$reasons\.Count\s+-gt\s+0\)\s*\{\s*"UNKNOWN"',
        )

    def test_preflight_output_omits_private_identity_fields(self) -> None:
        body = function_body(PREFLIGHT_PATH, "New-SanitizedPreflight")
        returned = body[body.index("return [ordered]@{") :]
        for forbidden in (
            "CommandLine",
            "runtime_dir",
            "repo_root",
            "workbook_path",
            "username",
            "USERPROFILE",
        ):
            self.assertNotIn(forbidden, returned)
        self.assertNotRegex(returned, r"\bcommand_line\s*=")
        for required in (
            "schema_version",
            "deployment",
            "artifacts",
            "controller_identity",
            "ports",
            "ui",
            "privacy",
        ):
            self.assertIn(required, returned)


if __name__ == "__main__":
    unittest.main()
