import csv,tempfile,unittest
from pathlib import Path
from scripts.run_research_pipeline import split_sessions,run
class MultiDaySessionTests(unittest.TestCase):
 def test_split_sessions_resets_by_date(self):
  rows=[{"ts":"2026-09-17 09:00:00"},{"ts":"2026-09-17 09:00:15"},{"ts":"2026-09-18 09:00:00"}]
  s=split_sessions(rows);self.assertEqual([len(x[1]) for x in s],[2,1])
 def test_each_day_exits_same_day_and_or_resets(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"multi.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]);w.writeheader()
    for day in ("2026-09-17","2026-09-18"):
     for i in range(70):
      hh=9+(i*15)//3600; mm=((i*15)%3600)//60; ss=(i*15)%60
      close=102 if i==60 else 100
      w.writerow({"time":f"{day} {hh:02d}:{mm:02d}:{ss:02d}","open":100,"high":101,"low":99,"close":close,"volume":10})
   trade,ev,s=run(p,Path(d)/"out",0)
   self.assertEqual(s["session_count"],2);self.assertEqual(s["usable_session_count"],2)
   rows=list(csv.DictReader(trade.open()))
   self.assertTrue(rows)
   for r in rows:self.assertEqual(r["entry_ts"][:10],r["exit_ts"][:10])
if __name__=="__main__":unittest.main()
