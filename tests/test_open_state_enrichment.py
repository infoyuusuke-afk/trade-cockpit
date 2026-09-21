import unittest
from scripts.open_state_enrichment import enrich_open_state

class OpenStateEnrichmentTests(unittest.TestCase):
 def test_ohlcv_delay_cannot_claim_special_buy(self):
  x=enrich_open_state("DELAYED_OPEN_UNCLASSIFIED",{})
  self.assertEqual(x["open_state"],"DELAYED_OPEN_UNCLASSIFIED")
  self.assertEqual(x["evidence_level"],"INSUFFICIENT")

 def test_ms2_observation_can_classify_special_buy(self):
  e={"source":"MS2","observed_at":"2026-09-18T09:00:05","quote_state":"SPECIAL_BUY"}
  x=enrich_open_state("DELAYED_OPEN_UNCLASSIFIED",e)
  self.assertEqual(x["open_state"],"SPECIAL_BUY")
  self.assertEqual(x["evidence_level"],"MS2_OBSERVED")

 def test_non_ms2_source_cannot_upgrade(self):
  e={"source":"TRADINGVIEW","observed_at":"2026-09-18T09:00:05","quote_state":"SPECIAL_SELL"}
  x=enrich_open_state("DELAYED_OPEN_UNCLASSIFIED",e)
  self.assertEqual(x["open_state"],"DELAYED_OPEN_UNCLASSIFIED")

if __name__=="__main__": unittest.main()
