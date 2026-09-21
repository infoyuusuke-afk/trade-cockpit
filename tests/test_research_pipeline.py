import csv,tempfile,unittest
from pathlib import Path
from scripts.run_research_pipeline import validate_input,run
class ResearchPipelineTests(unittest.TestCase):
 def write(self,p,n=70):
  with p.open("w",newline="") as f:
   w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]);w.writeheader()
   for i in range(n):
    c=102 if i==60 else 100
    w.writerow({"time":str(i),"open":100,"high":101,"low":99,"close":c,"volume":20 if i==60 else 10})
 def test_rejects_missing_columns(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv";p.write_text("time,open\n0,100\n")
   with self.assertRaises(ValueError):validate_input(p)
 def test_one_command_outputs_trade_and_ev_files(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv";self.write(p);trade,ev,s=run(p,Path(d)/"out",0)
   self.assertTrue(trade.exists());self.assertTrue(ev.exists());self.assertEqual(s["bar_count"],70)
if __name__=="__main__":unittest.main()
