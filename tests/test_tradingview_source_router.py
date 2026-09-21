import unittest
from scripts.tradingview_source_router import route_tradingview_data
def payload(c=100,tf="15S"):
 return {"meta":{"symbol":"TSE:285A","timeframe":tf,"retrieved_at":"2026-09-21T10:00:00+09:00","timezone":"Asia/Tokyo"},
 "bars":[{"timestamp":"2026-09-18T09:00:00+09:00","open":100,"high":101,"low":99,"close":c,"volume":10}]}
def replay(c=100):
 return [{"symbol":"285A","market_date":"2026-09-18","timestamp":"2026-09-18T09:00:00+09:00",
 "open":100,"high":101,"low":99,"close":c,"volume":10,"source":"TRADINGVIEW_15S"}]
class SourceRouterTests(unittest.TestCase):
 def test_mcp_is_primary_when_valid(self):
  x=route_tradingview_data(mcp_payload=payload())
  self.assertEqual(x["selected_source"],"TRADINGVIEW_MCP")
 def test_replay_fallback_when_mcp_timeframe_unavailable(self):
  x=route_tradingview_data(mcp_payload=payload(tf="5"),replay_rows=replay())
  self.assertEqual(x["status"],"READY_FALLBACK")
  self.assertEqual(x["selected_source"],"TRADINGVIEW_REPLAY")
 def test_mismatch_blocks(self):
  x=route_tradingview_data(mcp_payload=payload(101),replay_rows=replay(100))
  self.assertEqual(x["status"],"BLOCKED_SOURCE_MISMATCH");self.assertEqual(x["rows"],[])
 def test_matching_sources_choose_mcp_with_audit(self):
  x=route_tradingview_data(mcp_payload=payload(),replay_rows=replay())
  self.assertEqual(x["crosscheck"]["status"],"PASS")
  self.assertEqual(x["selected_source"],"TRADINGVIEW_MCP")
if __name__=="__main__":unittest.main()
