"""Static compatibility and no-trade constraints; runtime tested on Windows PS 5.1."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
class GatewayPublisherSafety(unittest.TestCase):
    def test_local_watcher_file_read_without_market_authentication(self):
        s=(ROOT/"downloads/AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("'kioxia_watcher_live.json'",s)
        self.assertIn("Get-V10WatcherPublication $RepoRoot",s)
        self.assertIn("$runtime.watcher_publication_state = $watcherProof.publication_state",s)
        self.assertIn("brain_publication_state      = 'UNKNOWN_NOT_PUBLISHED'",s)
        self.assertIn("real_submit_allowed        = $false",s)
        self.assertIn("'RECENT_PUBLICATION_ONLY'",s)
        self.assertNotIn("source_authenticated = $true",s)
    def test_source_watcher_is_timestamp_owner(self):
        s=(ROOT/"ms2_live/Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('observed_at_offset = $now.ToString("yyyy-MM-ddTHH:mm:sszzz")',s)
        self.assertIn('timestamp_timezone = "Asia/Tokyo"',s)
        self.assertIn('Write-AtomicUtf8 $watcherJsonPath $watcherJsonText',s)
    def test_ui_keeps_old_provenance_guard(self):
        html=(ROOT/"index.html").read_text(encoding="utf-8-sig")
        self.assertEqual(html.count('id="v10-publication-panel"'),1)
        self.assertEqual(html.count('src="v10_publication_status.js?v=p0-20261017"'),1)
        self.assertIn('id="v10-source-provenance"',html)
        self.assertIn('d.source_authenticated===true',html)
        self.assertIn('2026-09-25 10:41:50 JST',html)
if __name__=="__main__":
    unittest.main()
