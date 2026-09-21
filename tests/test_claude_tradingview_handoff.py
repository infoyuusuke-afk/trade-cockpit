import json,tempfile,unittest
from pathlib import Path
from scripts.run_claude_tradingview_handoff import run_handoff
class ClaudeTradingViewHandoffTests(unittest.TestCase):
 def payload(self,tf="15S"):
  bars=[]
  for i in range(70):
   sec=i*15;hh=9+sec//3600;mm=(sec%3600)//60;ss=sec%60;px=102 if i>=60 else 100
   bars.append({"timestamp":f"2026-09-18T{hh:02d}:{mm:02d}:{ss:02d}+09:00","open":px,"high":px+1,"low":px-1,"close":px,"volume":10})
  return {"meta":{"symbol":"TSE:285A","timeframe":tf,"retrieved_at":"2026-09-21T10:00:00+09:00","timezone":"Asia/Tokyo"},"bars":bars}
 def test_valid_handoff_runs_research_and_writes_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"claude.json";p.write_text(json.dumps(self.payload()),encoding="utf-8");out=Path(d)/"out"
   rp,trade,ev,manifest,summary=run_handoff(p,out);r=json.loads(rp.read_text())
   self.assertEqual(r["route_status"],"READY_UNCROSSCHECKED");self.assertFalse(r["promotion_eligible"])
   self.assertTrue(r["research_only"]);self.assertFalse(r["auto_execute"])
   self.assertTrue(trade.exists());self.assertTrue(ev.exists());self.assertTrue(manifest.exists());self.assertEqual(summary["bar_count"],70)
 def test_wrong_timeframe_fails_closed_but_keeps_receipt(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"claude.json";p.write_text(json.dumps(self.payload("5")),encoding="utf-8");out=Path(d)/"out"
   with self.assertRaisesRegex(ValueError,"CLAUDE_HANDOFF_NOT_READY"):run_handoff(p,out)
   r=json.loads((out/"claude_handoff_receipt.json").read_text());self.assertEqual(r["route_status"],"NO_USABLE_SOURCE");self.assertFalse(r["promotion_eligible"])
if __name__=="__main__":unittest.main()
