import csv,tempfile,unittest
from pathlib import Path
from scripts.run_research_pipeline import split_sessions,validate_tse_session,run

class MultiDaySessionTests(unittest.TestCase):
 def test_split_sessions_sorts_and_resets_by_date(self):
  rows=[{"ts":"2026-09-18 09:00:00"},{"ts":"2026-09-17 09:00:15"},{"ts":"2026-09-17 09:00:00"}]
  s=split_sessions(rows)
  self.assertEqual([x[0] for x in s],["2026-09-17","2026-09-18"])
  self.assertEqual([r["ts"] for r in s[0][1]],["2026-09-17 09:00:00","2026-09-17 09:00:15"])

 def test_duplicate_timestamp_fails_closed(self):
  rows=[{"ts":"2026-09-17 09:00:00"},{"ts":"2026-09-17 09:00:00"}]
  with self.assertRaises(ValueError): split_sessions(rows)

 def test_bad_timestamp_fails_closed(self):
  with self.assertRaises(ValueError): split_sessions([{"ts":"bad"}])

 def test_tse_opening_grid_accepts_exact_15s(self):
  rows=[{"ts":f"2026-09-17 09:{(i*15)//60:02d}:{(i*15)%60:02d}"} for i in range(60)]
  self.assertTrue(validate_tse_session(rows))

 def test_delayed_first_print_is_preserved(self):
  rows=[{"ts":f"2026-09-17 09:{(5*60+i*15)//60:02d}:{(5*60+i*15)%60:02d}"} for i in range(60)]
  self.assertTrue(validate_tse_session(rows))

 def test_broken_opening_grid_fails_closed(self):
  rows=[{"ts":f"2026-09-17 09:{(i*15)//60:02d}:{(i*15)%60:02d}"} for i in range(60)]
  rows[10]={"ts":"2026-09-17 09:02:31"}
  with self.assertRaises(ValueError): validate_tse_session(rows)

 def test_each_day_exits_same_day_and_pnl_contract(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"multi.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]); w.writeheader()
    for day in ("2026-09-17","2026-09-18"):
     for i in range(70):
      sec=i*15; hh=9+sec//3600; mm=(sec%3600)//60; ss=sec%60
      close=102 if i==60 else 100
      w.writerow({"time":f"{day} {hh:02d}:{mm:02d}:{ss:02d}","open":100,"high":101,"low":99,"close":close,"volume":10})
   trade,ev,s=run(p,Path(d)/"out",0.1)
   self.assertEqual(s["session_count"],2); self.assertEqual(s["usable_session_count"],2)
   rows=list(csv.DictReader(trade.open())); self.assertTrue(rows)
   for r in rows:
    self.assertEqual(r["entry_ts"][:10],r["exit_ts"][:10])
    self.assertNotEqual(r["gross_pnl_pct"],"")
    self.assertNotEqual(r["net_pnl_pct"],"")
    self.assertAlmostEqual(float(r["pnl_pct"]),float(r["net_pnl_pct"]),places=6)\n    self.assertEqual(r["open_state"],"NORMAL_OPEN")\n    self.assertEqual(int(r["open_delay_sec"]),0)

 def test_delayed_open_gap_uses_prior_close(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"gap.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["time","open","high","low","close","volume"]); w.writeheader()
    for day,start_min,px in (("2026-09-17",0,100),("2026-09-18",5,105)):
     for i in range(70):
      sec=start_min*60+i*15; hh=9+sec//3600; mm=(sec%3600)//60; ss=sec%60
      close=px+2 if i==60 else px
      w.writerow({"time":f"{day} {hh:02d}:{mm:02d}:{ss:02d}","open":px,"high":px+1,"low":px-1,"close":close,"volume":10})
   trade,ev,s=run(p,Path(d)/"out",0)
   rows=list(csv.DictReader(trade.open()))
   day2=[r for r in rows if r["session_date"]=="2026-09-18"]
   self.assertTrue(day2)
   self.assertTrue(all(r["open_state"]=="DELAYED_OPEN_UNCLASSIFIED" for r in day2))
   self.assertTrue(all(int(r["open_delay_sec"])==300 for r in day2))
   self.assertTrue(all(r["gap_pct"]!="" for r in day2))

if __name__=="__main__": unittest.main()
