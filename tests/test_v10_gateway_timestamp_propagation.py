import unittest
from pathlib import Path
class GatewaySourceTimestamp(unittest.TestCase):
    def test_exposes_raw_collector_publication_metadata_only(self):
        s=(Path(__file__).resolve().parents[1]/"downloads/AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("collector_observed_at_offset = $null",s)
        self.assertIn("$runtime.collector_observed_at_offset = [string]$healthLive.observed_at_offset",s)
        self.assertIn("$runtime.collector_timestamp_timezone = [string]$healthLive.timestamp_timezone",s)
        self.assertIn("real_submit_allowed        = $false",s)
if __name__=="__main__":unittest.main()
