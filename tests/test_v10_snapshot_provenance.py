"""P0 V10 static UI provenance contract; no executable/browser/market processes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
INDEX = ROOT / "index.html"

class V10SnapshotProvenance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gateway = GATEWAY.read_text(encoding="ascii")
        cls.html = INDEX.read_text(encoding="utf-8")

    def test_gateway_parses_under_windows_5_1_legacy_codepage(self):
        self.assertTrue(self.gateway.isascii())

    def test_older_ui_has_provenance_notice(self):
        self.assertIn("2026-09-25 10:41:50 JST", self.html)
        for key in ("HISTORICAL", "SAME_DAY_STATIC", "DATE_UNVERIFIED",
                    "Add-StaticSnapshotNotice $html (Get-Date)",
                    "v10-static-snapshot-warning", "SnapshotGuardSelfTest"):
            self.assertIn(key, self.gateway)

    def test_keeps_live_source_checks_and_local_checkout_unchanged(self):
        self.assertIn("Join-Path $RepoRoot $relative", self.gateway)
        self.assertIn("Get-Content -LiteralPath $resolvedFull -Raw -Encoding UTF8", self.gateway)
        self.assertIn("LIVE_JSON_MAX_AGE_SECONDS = 60", self.gateway)
        self.assertIn("real_submit_allowed", self.gateway)
        self.assertEqual(self.gateway.count("Add-StaticSnapshotNotice $html (Get-Date)"), 1)
        for forbidden in ("Set-ExecutionPolicy", "Start-Process -Verb RunAs",
                          "Invoke-WebRequest", "Remove-Item "):
            self.assertNotIn(forbidden, self.gateway)

if __name__ == "__main__":
    unittest.main()
