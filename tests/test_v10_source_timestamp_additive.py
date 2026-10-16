"""Guard additive source timestamp metadata and existing safety fields."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class AdditiveTimestamp(unittest.TestCase):
    def test_watcher(self):
        s=(ROOT/"ms2_live/Kioxia_RSS_Live_Watcher.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('observed_at_offset = $now.ToString("yyyy-MM-ddTHH:mm:sszzz")',s)
        self.assertIn('timestamp_timezone = "Asia/Tokyo"',s)
        self.assertIn('updated_at = $now.ToString("yyyy-MM-dd HH:mm:ss")',s)
    def test_collector(self):
        s=(ROOT/"ms2_live/MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('observed_at_offset=$now.ToString("yyyy-MM-ddTHH:mm:sszzz")',s)
        self.assertIn('timestamp_timezone="Asia/Tokyo"',s)
        self.assertIn('real_submit_allowed=$false',s)
        self.assertIn('Write-AtomicUtf8 $jsonPath $jsonText',s)
if __name__=="__main__":unittest.main()
