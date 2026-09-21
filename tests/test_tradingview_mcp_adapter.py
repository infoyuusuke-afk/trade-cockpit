import unittest
from scripts.tradingview_mcp_adapter import adapt_mcp_payload,require_timeframe

class TradingViewMCPAdapterTests(unittest.TestCase):
 def payload(self,tf="15S"):
  return {"meta":{"symbol":"TSE:285A","timeframe":tf,
          "retrieved_at":"2026-09-21T10:00:00+09:00","timezone":"Asia/Tokyo"},
          "bars":[{"timestamp":"2026-09-18T09:00:00+09:00",
          "open":100,"high":101,"low":99,"close":100.5,"volume":1000}]}
 def test_mcp_payload_becomes_core(self):
  x=adapt_mcp_payload(self.payload())[0]
  self.assertEqual(x["source"],"TRADINGVIEW_MCP")
  self.assertFalse(x["synthetic_timeframe"])
 def test_timeframe_mismatch_fails_instead_of_resampling(self):
  rows=adapt_mcp_payload(self.payload("5"))
  with self.assertRaises(ValueError):require_timeframe(rows,"15S")
 def test_missing_retrieval_time_fails(self):
  p=self.payload();del p["meta"]["retrieved_at"]
  with self.assertRaises(ValueError):adapt_mcp_payload(p)
 def test_nonfinite_ohlcv_fails(self):
  for field,value in (("open","nan"),("high","inf"),("low","-inf"),("close","nan"),("volume","nan")):
   p=self.payload();p["bars"][0][field]=value
   with self.assertRaisesRegex(ValueError,"NONFINITE_OHLCV"):adapt_mcp_payload(p)
 def test_invalid_ohlc_fails(self):
  p=self.payload();p["bars"][0]["high"]=98
  with self.assertRaises(ValueError):adapt_mcp_payload(p)
if __name__=="__main__":unittest.main()
