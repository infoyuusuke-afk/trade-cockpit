"""V10 user-facing provenance must not turn static/unknown values into LIVE."""
from pathlib import Path
import unittest
HTML=(Path(__file__).resolve().parents[1]/"index.html").read_text(encoding="utf-8")
class V10LiveFreshness(unittest.TestCase):
    def test_notice_and_default_block(self):
        self.assertIn('id="v10-source-provenance"', HTML)
        self.assertIn('data-market-trust="BLOCKED"', HTML)
        self.assertIn('source_authenticated===true', HTML)
        self.assertIn('d.live_values_available===true', HTML)
        self.assertIn('d.data_conflict===false', HTML)
        self.assertIn('d.real_submit_allowed===false', HTML)
    def test_freshness_unknown_and_future_blocked(self):
        self.assertIn("Number.isFinite(t)", HTML)
        self.assertIn("age<0||age>60000", HTML)
        self.assertIn('d._transport_fail_closed!==true', HTML)
        self.assertIn('e.detail||{}',HTML)
        self.assertIn('dataset.marketTrust="OBSERVATION_ONLY"',HTML)
        self.assertNotIn('dataset.marketTrust="ORDER_ALLOWED"',HTML)
    def test_old_snapshot_is_not_modified(self):
        self.assertIn("2026-09-25 10:41:50 JST",HTML)
        self.assertEqual(HTML.count('id="v10-source-provenance"'),1)
if __name__=="__main__": unittest.main()
