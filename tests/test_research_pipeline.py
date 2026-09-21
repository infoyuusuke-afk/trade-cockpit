import csv,tempfile,unittest
from pathlib import Path
from scripts.run_research_pipeline import validate_input,run
from scripts.research_pipeline import evaluate_research_trade

class ResearchPipelineTests(unittest.TestCase):
 def write(self,p,n=70):
  with p.open("w",newline="") as f:
   w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]);w.writeheader()
   for i in range(n):
    c=102 if i==60 else 100
    sec=i*15; mm=sec//60; ss=sec%60
    w.writerow({"time":f"2026-09-18 09:{mm:02d}:{ss:02d}","open":100,"high":101,"low":99,"close":c,"volume":20 if i==60 else 10})
 def test_rejects_missing_columns(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv";p.write_text("time,open\n0,100\n")
   with self.assertRaises(ValueError):validate_input(p)
 def test_one_command_outputs_trade_and_ev_files(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv";self.write(p);trade,ev,s=run(p,Path(d)/"out",0)
   self.assertTrue(trade.exists());self.assertTrue(ev.exists());self.assertEqual(s["bar_count"],70)
 def test_integrated_gate_blocks_incomplete_context(self):
  s={"trade_id":"T1","decision_ts":"2026-09-18T10:00:00+09:00","proposed_action":"LONG","data_fresh":True}
  h=[{"x":0,"empirical_cluster":"A"} for _ in range(5)]
  x=evaluate_research_trade(s,["DATA_FRESH"],{"empirical_cluster":"A"},h,{"x":0,"empirical_cluster":"A"},["x"])
  self.assertEqual(x["pipeline_status"],"BLOCKED_PRETRADE")
 def test_integrated_pipeline_attributes_later_break(self):
  s={"trade_id":"T2","decision_ts":"2026-09-18T10:00:00+09:00","proposed_action":"LONG","data_fresh":True,"net_pnl":-1}
  h=[{"x":0,"empirical_cluster":"A"} for _ in range(5)]
  done=["DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME"]
  e=[{"reason":"TIME_REGIME_SHIFT","observed_at":"2026-09-18T10:01:00+09:00"}]
  x=evaluate_research_trade(s,done,{"empirical_cluster":"A"},h,{"x":0,"empirical_cluster":"A"},["x"],e)
  self.assertEqual(x["pipeline_status"],"RESEARCH_SIGNAL_ACCEPTED")
  self.assertEqual(x["preventability"]["classification"],"POST_DECISION_SHOCK")
  self.assertFalse(x["auto_execute"])
if __name__=="__main__":unittest.main()
