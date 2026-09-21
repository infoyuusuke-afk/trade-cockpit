import unittest
from scripts.tradingview_source_router import route_tradingview_data
def payload(c=100,tf="15S",ts="2026-09-18T09:00:00+09:00"):
 return {"meta":{"symbol":"TSE:285A","timeframe":tf,"retrieved_at":"2026-09-21T10:00:00+09:00","timezone":"Asia/Tokyo"},"bars":[{"timestamp":ts,"open":100,"high":101,"low":99,"close":c,"volume":10}]}
def replay(c=100,ts="2026-09-18T09:00:00+09:00",source="TRADINGVIEW_REPLAY",tf="15S"):
 return [{"symbol":"TSE:285A","market_date":"2026-09-18","timestamp":ts,"open":100,"high":101,"low":99,"close":c,"volume":10,"source":source,"source_timeframe":tf,"source_timezone":"Asia/Tokyo"}]
class SourceRouterTests(unittest.TestCase):
 def test_mcp_alone_is_uncrosschecked_nonpromotable(self):
  x=route_tradingview_data(mcp_payload=payload());self.assertEqual(x["status"],"READY_UNCROSSCHECKED");self.assertFalse(x["promotion_eligible"])
 def test_replay_fallback_is_validated_and_nonpromotable(self):
  x=route_tradingview_data(mcp_payload=payload(tf="5"),replay_rows=replay());self.assertEqual(x["status"],"READY_FALLBACK_UNCROSSCHECKED");self.assertFalse(x["promotion_eligible"])
 def test_bad_replay_provenance_is_rejected(self):
  x=route_tradingview_data(replay_rows=replay(source="TRADINGVIEW_15S"));self.assertEqual(x["status"],"NO_USABLE_SOURCE");self.assertEqual(x["replay_error"],"REPLAY_PROVENANCE_MISSING")
 def test_nonfinite_replay_is_rejected(self):
  for field,value in (("open","nan"),("high","inf"),("low","-inf"),("close","nan"),("volume","nan")):
   rows=replay();rows[0][field]=value
   x=route_tradingview_data(replay_rows=rows)
   self.assertEqual(x["status"],"NO_USABLE_SOURCE")
   self.assertEqual(x["replay_error"],"REPLAY_NONFINITE_OHLCV")
 def test_bad_replay_timeframe_is_rejected(self):
  x=route_tradingview_data(replay_rows=replay(tf="5"));self.assertEqual(x["status"],"NO_USABLE_SOURCE");self.assertEqual(x["replay_error"],"REPLAY_TIMEFRAME_MISMATCH")
 def test_mismatch_blocks(self):
  x=route_tradingview_data(mcp_payload=payload(101),replay_rows=replay(100));self.assertEqual(x["status"],"BLOCKED_SOURCE_MISMATCH");self.assertEqual(x["rows"],[])
 def test_no_overlap_is_review_not_pass(self):
  x=route_tradingview_data(mcp_payload=payload(),replay_rows=replay(ts="2026-09-18T09:00:15+09:00"));self.assertEqual(x["status"],"REVIEW_NO_SOURCE_OVERLAP");self.assertFalse(x["promotion_eligible"])
 def test_matching_sources_choose_mcp_and_are_promotable(self):
  x=route_tradingview_data(mcp_payload=payload(),replay_rows=replay());self.assertEqual(x["crosscheck"]["status"],"PASS");self.assertEqual(x["selected_source"],"TRADINGVIEW_MCP");self.assertTrue(x["promotion_eligible"])
if __name__=="__main__":unittest.main()
