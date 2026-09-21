import csv,json,tempfile,unittest
from pathlib import Path
from scripts.build_tradingview_master import build_master

class TradingViewMasterTests(unittest.TestCase):
 def write(self,p,rows):
  with p.open("w",newline="",encoding="utf-8") as f:
   w=csv.writer(f);w.writerow(["time","open","high","low","close","volume"])
   w.writerows(rows)
 def test_builds_deduplicated_master_and_audit(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);a=d/"a.csv";b=d/"b.csv"
   self.write(a,[["2026-09-18 09:00:00",100,101,99,100,10],
                 ["2026-09-18 09:00:15",100,101,99,100,10]])
   self.write(b,[["2026-09-18 09:00:15",100,101,99,100,10],
                 ["2026-09-18 09:00:30",100,101,99,100,10]])
   master,audit,report=build_master([a,b],"285A",d/"out")
   self.assertTrue(master.exists());self.assertTrue(audit.exists())
   self.assertEqual(report["master_rows"],3)
   self.assertEqual(report["duplicate_overlap_rows"],1)
   self.assertFalse(report["master_usable_for_live"])
   self.assertEqual(json.loads(audit.read_text())["symbol"],"285A")
 def test_overlap_mismatch_stops_master_creation(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);a=d/"a.csv";b=d/"b.csv"
   self.write(a,[["2026-09-18 09:00:00",100,101,99,100,10]])
   self.write(b,[["2026-09-18 09:00:00",100,102,99,100,10]])
   with self.assertRaises(ValueError):build_master([a,b],"285A",d/"out")
if __name__=="__main__":unittest.main()
