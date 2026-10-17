"""P0-417: current V10 Shadow safety contract replacing a cross-version V9 claim.

Historical test test_ai_shadow_supervisor.ContractSourceTests.
test_controller_and_gateway_keep_real_submit_locked requires V9 files that
no longer exist in V10. This NEW contract independently checks V10 sources,
without modifying or suppressing the original 126th unmatched historic ID.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "controller": ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V10.ps1",
    "gateway": ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1",
    "shadow": ROOT / "scripts" / "ai_shadow_supervisor.py",
    "ui": ROOT / "trade_control.js",
}


class CurrentV10ShadowSafetyContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {key: p.read_text(encoding="utf-8-sig")
                       for key, p in FILES.items()}

    def test_controller_shadow_start_uses_quote_safe_live_readonly_arguments(self):
        c = self.sources["controller"]
        for proof in (
            "function Start-ShadowSupervisor",
            '"--live", (\'"\' + (Join-Path $RuntimeDir "live_ms2.json") + \'"\')',
            "shadow_supervisor_pid",
            "Write-ShadowStoppedStatus",
            'real_submit_allowed = $false',
            "-WindowStyle Hidden",
            "-RedirectStandardOutput $stdout",
            "-RedirectStandardError $stderr",
        ):
            self.assertIn(proof, c, proof)
        start = c.split("function Start-ShadowSupervisor", 1)[1].split(
            "# Independent read-only MS2 BRAIN observer", 1
        )[0]
        self.assertNotIn("RssOrder", start)

    def test_gateway_never_publishes_actual_orders_or_connected_positions(self):
        g = self.sources["gateway"]
        start = g.index("$execution = [ordered]@{")
        region = g[start:g.index("$shadowPub = Get-ShadowEnginePublication", start)]
        for proof in (
            "real_submit_allowed        = $false",
            "real_order_route            = 'DISABLED'",
            "broker_positions_connected  = $false",
            "shadow_positions_connected  = $false",
            "shadow_position_status      = 'NOT_PUBLISHED'",
            "auto_trading_real           = 'OFF_LOCKED'",
        ):
            self.assertIn(proof, region, proof)
        self.assertIn("function Get-ShadowEnginePublication", g)
        self.assertIn("SHADOW_IDENTITY_OR_HEARTBEAT_UNVERIFIED", g)
        self.assertIn("$execution.shadow_engine_state = 'PAUSED_FAIL_CLOSED'", g)

    def test_ui_treats_unverified_shadow_and_broker_as_disconnected(self):
        u = self.sources["ui"]
        for proof in (
            'exec?.real_submit_allowed===true',
            'exec?.broker_positions_connected===true',
            'exec?.shadow_positions_connected===true',
            '"PAUSED_FAIL_CLOSED"',
            "exec?.shadow_engine_state||\"STOPPED\"",
            "REAL ORDER LOCKED",
            "未接続",
        ):
            self.assertIn(proof, u)
        self.assertIn("allowed.includes(raw)?raw:\"PAUSED_FAIL_CLOSED\"", u)

    def test_supervisor_always_retains_fail_closed_no_broker_path(self):
        s = self.sources["shadow"]
        for forbidden in (
            "submit_shadow_order",
            "RssOrder",
            'real_submit_allowed"] = True',
            "real_submit_allowed = True",
        ):
            self.assertNotIn(forbidden, s)
        self.assertIn('STATES = ("RUNNING", "PAUSED_FAIL_CLOSED", "RECOVERING", "STOPPED")', s)
        self.assertIn('"real_submit_allowed": False', s)
        self.assertIn('parser.add_argument("--live", required=True)', s)

    def test_original_v9_contract_is_not_removed_or_renamed(self):
        old = (ROOT / "tests" / "test_ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertIn("def test_controller_and_gateway_keep_real_submit_locked(self):", old)
        self.assertIn('ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1"', old)
        self.assertIn('ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V9.ps1"', old)
        new = (ROOT / "scripts" / "ci_historic_id_coverage.py").read_text(encoding="utf-8")
        self.assertIn("P0_417_COVERAGE_UNMAPPED=", new)


if __name__ == "__main__":
    unittest.main()
