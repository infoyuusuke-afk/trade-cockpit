import csv,tempfile,unittest
from pathlib import Path
from scripts.run_tradingview_replay import load_replay_csv,run_replay

class ReplayRunnerTests(unittest.TestCase):
 def make_csv(self,p):
  with p.open("w",newline="") as f:
   w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]);w.writeheader()
   for i in range(70):
    sec=i*15; close=102 if i>=60 else 100
    w.writerow({"time":f"2026-09-18 09:{sec//60:02d}:{sec%60:02d}","open":close,"high":close+1,"low":close-1,"close":close,"volume":10})
 def test_replay_csv_runs_end_to_end(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"tv.csv";self.make_csv(p)
   rows=load_replay_csv(p);self.assertEqual(len(rows),70);self.assertEqual(rows[0]["source"],"TRADINGVIEW_REPLAY")
   trade,ev,manifest,summary=run_replay(p,Path(d)/"out")
   self.assertTrue(trade.exists());self.assertTrue(ev.exists());self.assertTrue(manifest.exists());self.assertEqual(summary["bar_count"],70)
 def test_one_minute_csv_cannot_be_labeled_15s(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"one_min.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]);w.writeheader()
    for i in range(3): w.writerow({"time":f"2026-09-18 09:0{i}:00","open":100,"high":101,"low":99,"close":100,"volume":10})
   with self.assertRaisesRegex(ValueError,"NO_15S_CADENCE_EVIDENCE"): load_replay_csv(p)
 def test_missing_volume_fails_closed(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"bad.csv";p.write_text("time,open,high,low,close\n2026-09-18 09:00:00,1,1,1,1\n")
   with self.assertRaisesRegex(ValueError,"MISSING_REPLAY_COLUMN:volume"): load_replay_csv(p)
if __name__=="__main__":unittest.main()
