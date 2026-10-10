"""Safety contract for the additive V10 identity diagnostics.

The production scripts manage Windows processes on the Owner PC and cannot
be executed in Linux CI.  These tests therefore lock the no-control-change
boundary, the additive schemas, the privacy boundary, and the fixture
self-test that is executable with Windows PowerShell.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "downloads"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def digest(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def function_body(path: str, name: str) -> str:
    text = read(path)
    start = text.index(f"function {name}")
    brace = text.index("{", start)
    depth = 0
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unterminated PowerShell function: {name}")


FORBIDDEN_FILE_HASHES = {
    "downloads/STOP_AI_COCKPIT_V10.ps1": "66f6d2acd14416207502d6b896b346323c7b7a5ac3c5c9ebe6f875dd16b3c283",
    "index.html": "c66c6fdfb4f681306fec5c99d1088ca8de82ae7adf2164d36e526867229bd052",
    "scripts/update.py": "afadacde0b9d3e6a4e7491518ca61268007b362c0b748424a46e262c9918b222",
    "scripts/weekly_tabs.py": "dcbd9d731c2e2e390e199c047295e944d4c4b204dcf6d494bf417443da4a9de7",
    "ms2_live/MS2_RSS_100_Collector.ps1": "2b7b72730dcb5827010a873148cbade596223c082022357067ac96d6e0dc4f6a",
    "ms2_live/Kioxia_RSS_Live_Watcher.ps1": "6373575b6542fcc965242c17f64e0258b51a1dc554cfc62f46a09f6c98bceb74",
    "card_system.css": "0928ed8cc2da06aa56ffa4465cd642c6d157391c367bf3b484fcd4297388e42f",
    "card_system.js": "3cf03965b3bc8fdde835b0c908f191fbf51a37f29c65fdccd10f0fa6296c7442",
    "card_table_adapter.css": "551b15c032be5c1c085c1f7f1d9945dcaf7ef41b0cbe85d44917206a244db843",
    "card_table_adapter.js": "f66c87b5f6dfcee8902f0341966831e7a005b3d22b91a59af68d5f253dacc31e",
    "earnings-calendar.js": "2214e01ef9af21284385f876a646644cf28b1539e22a48e016478496e49f3d68",
    "focus.css": "9cc0ef7bda3feb9e70101e3586079a48e1c8639e5bfd1d622bc42dde3ccab017",
    "next-theme-radar.css": "e743229e57c4ad0dfc91f0d5d8cd91438059fec8197ad14228b91d919df92bce",
    "next-theme-radar.js": "ba89f55efab3718d9440807d8e8735a3b7997e3fa46a675d6ea7f5efec7ab14a",
    "opportunity_radar.js": "48033dc6fe7a51c2d9826837f07b004374b0499949f77513256c735741ff9677",
    "theme.css": "7c0e0b9fec69787f55e363e966a2f2816c480f13dd5c305e01468ccd00e3ee20",
    "trade_control.js": "ba3095dacbcf55b3fdaf4fad4855a858a3733174b9fdd6cd74461c1803d0ebab",
    "voice_client.js": "1ec67e07d21b982a5a6f1d4ef4b0d13c4e4ac8f1effb8cda14273a6ddaa046b7",
}


CONTROL_FUNCTION_HASHES = {
    ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Stop-OwnedJobBridge"):
        "30761f925b22c7b95db3ae4099bc302bfa82d92b08ae6883007ab683b12ed698",
    ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Test-ForeignSession"):
        "f92608dd1d0f423bcbc78465f84692dc1b2ea17f4320520f67274a619d6bd960",
    ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Stop-OwnedFromPreviousState"):
        "fbb12a40c2316b0dfed14241f0e8dfac90b57a8db480d013ba3c79e704ec2759",
    ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Stop-ManagedWorkersOnWorkbookClose"):
        "93e6415b2dca39ce48985e9a55d93bb6377f610962313b4adeb33fde112e0083",
    ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Start-Worker"):
        "8a7f11b0806108a6ecee4da9d6a7a23d3716278aea8f642fd95be603491e28b9",
    ("downloads/AI_COCKPIT_GATEWAY_V10.ps1", "Send-Response"):
        "e63f05a5270867c3a0193adfc834a908eea414dd3cf142bf9e5c3ac1eae75706",
    ("downloads/AI_COCKPIT_GATEWAY_V10.ps1", "Get-LivePriceRejection"):
        "2d155e584f7c3b4df1ad1e3d1bd1426cf325f20ce6b29c847e8cadbdfaa4c767",
}


class V10IdentityDiagnosticsContract(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = read("downloads/RUN_AI_COCKPIT_V10.ps1")
        self.controller = read("downloads/AI_COCKPIT_CONTROLLER_V10.ps1")
        self.gateway = read("downloads/AI_COCKPIT_GATEWAY_V10.ps1")

    def test_forbidden_files_are_byte_identical_to_fixed_base(self) -> None:
        for path, expected in FORBIDDEN_FILE_HASHES.items():
            self.assertEqual(digest(path), expected, path)

    def test_control_functions_are_unchanged(self) -> None:
        for (path, name), expected in CONTROL_FUNCTION_HASHES.items():
            actual = hashlib.sha256(function_body(path, name).encode()).hexdigest()
            self.assertEqual(actual, expected, f"{path}:{name}")

    def test_manifest_is_additive_and_keeps_legacy_fields(self) -> None:
        for field in ("repo_sha", "repo_branch", "runtime_dir", "files", "deployed_at"):
            self.assertRegex(self.runner, rf"\b{field}\s*=")
        self.assertIn('schema_version = "v10-deployment-identity-1"', self.runner)
        self.assertIn("identity_diagnostics = $identityDiagnostics", self.runner)
        self.assertIn("source_raw_sha256", self.runner)
        self.assertIn("deployed_raw_sha256", self.runner)
        self.assertIn("git_blob_sha1", self.runner)

    def test_controller_diagnostics_are_read_only(self) -> None:
        self.assertIn("function Update-IdentityDiagnostics", self.controller)
        body = function_body(
            "downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Update-IdentityDiagnostics"
        )
        for forbidden in (
            "Stop-Process",
            "Start-Process",
            "Start-Worker",
            "throw ",
            "real_submit_allowed",
        ):
            self.assertNotIn(forbidden, body)
        self.assertIn("identity_diagnostics", body)
        self.assertIn("UNKNOWN", body)

    def test_process_and_port_identity_contract_is_present(self) -> None:
        for token in (
            "Get-ProcessIdentityObservation",
            "Compare-ProcessIdentity",
            "Get-PortOwnerSet",
            "Compare-PortIdentity",
            "ParentProcessId",
            "CreationDate",
            "SessionId",
            "script_raw_sha256",
            "PID_REUSED",
            "SESSION_MISMATCH",
            "PARENT_MISMATCH",
            "FOREIGN_OWNER",
        ):
            self.assertIn(token, self.controller)
        for port in range(28580, 28585):
            self.assertIn(str(port), self.controller)

    def test_windows_fixture_self_test_covers_required_failures(self) -> None:
        self.assertIn("[switch]$IdentityDiagnosticsSelfTest", self.controller)
        body = function_body(
            "downloads/AI_COCKPIT_CONTROLLER_V10.ps1",
            "Invoke-IdentityDiagnosticsSelfTest",
        )
        for reason in (
            "PID_REUSED",
            "SESSION_MISMATCH",
            "PARENT_MISMATCH",
            "SCRIPT_PATH_MISMATCH",
            "SCRIPT_HASH_MISMATCH",
            "FOREIGN_OWNER",
            "VERIFIED_BRIDGE_CHILD",
        ):
            self.assertIn(reason, body)
        self.assertNotRegex(body, r"Get-CimInstance|Get-NetTCPConnection|Get-Process")

    def test_gateway_adds_only_a_separate_local_diagnostic_route(self) -> None:
        self.assertIn("if ($path -eq '/_v10/identity')", self.gateway)
        self.assertIn("Send-LocalDiagnosticResponse", self.gateway)
        sender = function_body(
            "downloads/AI_COCKPIT_GATEWAY_V10.ps1",
            "Send-LocalDiagnosticResponse",
        )
        self.assertNotIn("Access-Control-Allow-Origin: *", sender)
        self.assertIn("Cache-Control: no-store", sender)

    def test_sanitized_output_has_an_explicit_allowlist(self) -> None:
        body = function_body(
            "downloads/AI_COCKPIT_GATEWAY_V10.ps1",
            "Get-SanitizedIdentityDiagnostics",
        )
        for allowed in (
            "schema_version",
            "overall",
            "reason_codes",
            "processes",
            "ports",
            "ui",
        ):
            self.assertIn(allowed, body)
        for forbidden in (
            "CommandLine",
            "command_line",
            "repo_root",
            "runtime_dir",
            "workbook",
            "username",
            "USERPROFILE",
        ):
            self.assertNotIn(forbidden, body)

    def test_ui_path_resolver_rejects_unsafe_sources(self) -> None:
        body = function_body(
            "downloads/AI_COCKPIT_GATEWAY_V10.ps1", "Get-SafeUiAssetPath"
        )
        for token in ("IsPathRooted", r"\\", "..", "ReparsePoint", "StartsWith"):
            self.assertIn(token, body)
        self.assertIn("UI_ASSET_ALLOWLIST", self.gateway)

    def test_existing_gateway_routes_remain_present(self) -> None:
        for route in ("/health", "/live_ms2.json"):
            self.assertIn(f"$path -eq '{route}'", self.gateway)
        self.assertIn("real_submit_allowed        = $false", self.gateway)

    def test_new_code_avoids_known_windows_powershell_51_enum_parse_trap(self) -> None:
        for path, name in (
            ("downloads/AI_COCKPIT_CONTROLLER_V10.ps1", "Get-ProcessIdentityObservation"),
            ("downloads/AI_COCKPIT_GATEWAY_V10.ps1", "Get-SafeUiAssetPath"),
        ):
            text = function_body(path, name)
            self.assertNotRegex(
                text,
                r"\.(?:IndexOf|StartsWith)\([^\n]*,\s*\[StringComparison\]::",
            )

    def test_no_obvious_private_values_or_order_permission_in_diagnostics(self) -> None:
        combined = self.runner + self.controller + self.gateway
        self.assertNotRegex(combined, re.compile(r"C:\\Users\\[^\\\s]+", re.I))
        diagnostics = (
            function_body(
                "downloads/AI_COCKPIT_CONTROLLER_V10.ps1",
                "Update-IdentityDiagnostics",
            )
            + function_body(
                "downloads/AI_COCKPIT_GATEWAY_V10.ps1",
                "Get-SanitizedIdentityDiagnostics",
            )
        )
        self.assertNotIn("real_submit_allowed", diagnostics)


if __name__ == "__main__":
    unittest.main()
