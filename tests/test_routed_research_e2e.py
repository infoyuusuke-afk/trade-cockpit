import json,tempfile,unittest
from pathlib import Path
from scripts.tradingview_source_router import route_tradingview_data
from scripts.routed_research_backtest import run_routed_backtest

class RoutedResearchE2ETests(unittest.TestCase):
 def payload(self):
  bars=[]
  # 70 continuous 15s bars; OR15 is first 60 bars, then breakout.
  for i in range(70):
   sec=i*15; hh=9+(sec//3600); mm=(sec%3600)//60; ss=sec%60
   ts=f"2026-09-18T{hh:02d}:{mm:02d}:{ss:02d}+09:00"
   close=102 if i>=60 else 100
   bars.append({"timestamp":ts,"open":close,"high":close+1,"low":close-1,
                "close":close,"volume":10})
  return {"meta":{"symbol":"TSE:285A","timeframe":"15S",
          "retrieved_at":"2026-09-21T10:00:00+09:00","timezone":"Asia/Tokyo"},
          "bars":bars}

 def test_mcp_to_ev_and_manifest(self):
  route=route_tradingview_data(mcp_payload=self.payload())
  self.assertEqual(route["selected_source"],"TRADINGVIEW_MCP")
  with tempfile.TemporaryDirectory() as d:
   trade,ev,manifest,summary=run_routed_backtest(route,Path(d))
   self.assertTrue(trade.exists());self.assertTrue(ev.exists());self.assertTrue(manifest.exists())
   m=json.loads(manifest.read_text())
   self.assertEqual(m["selected_source"],"TRADINGVIEW_MCP")
   self.assertEqual(m["input_rows"],70)
   self.assertEqual(summary["bar_count"],70)

if __name__=="__main__":unittest.main()
