"""Synthetic fail-closed acceptance for V10 UI upgrade compatibility."""
from datetime import date
from pathlib import Path
import unittest
from scripts.v10_ui_asset_gate import audit, inspect

BASE = (Path(__file__).resolve().parents[1] / "index.html").read_bytes()

class Compatibility(unittest.TestCase):
    def test_local_v10_contract_present(self):
        dt, controls, digest = inspect(BASE)
        self.assertEqual(dt, date(2026,9,25))
        self.assertIn("brain-runtime", controls)
        self.assertIn("trade_control.js", controls)

    def test_new_date_without_controls_stays_blocked(self):
        candidate = b"<html><header>2026-10-16</header><main>New!</main></html>"
        result = audit(BASE, candidate, date(2026,10,16))
        self.assertEqual(result["status"], "BLOCKED_UI_ASSET_INCOMPATIBLE")
        self.assertIn("brain-runtime", result["missing_from_candidate"])
        self.assertIn("trade_control.js", result["missing_from_candidate"])
        self.assertFalse(result["real_submit_allowed"])
        self.assertFalse(result["runtime_applied"])

    def test_compatible_newer_source_is_preflight_only(self):
        newer = BASE.replace(b"2026-09-25 10:41:50",b"2026-10-15 10:41:50",1)
        result = audit(BASE, newer, date(2026,10,16))
        self.assertEqual(result["status"], "PREFLIGHT_ONLY_PASS")
        self.assertFalse(result["runtime_applied"])

    def test_identical_or_future_candidate_blocked(self):
        for candidate in (BASE,BASE.replace(b"2026-09-25 10:41:50",b"2026-10-31 10:41:50",1)):
            self.assertEqual(audit(BASE,candidate,date(2026,10,16))["status"],"BLOCKED_UI_ASSET_INCOMPATIBLE")

    def test_unknown_date_refused(self):
        with self.assertRaises(ValueError):
            inspect(b"<html><header>No date</header></html>")

if __name__ == "__main__":
    unittest.main()
