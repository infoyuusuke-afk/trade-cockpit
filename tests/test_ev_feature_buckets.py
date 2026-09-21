import csv,tempfile,unittest
from pathlib import Path
from scripts.analyze_ev_features import bucket,analyze
class EVFeatureBucketTests(unittest.TestCase):
 def test_fixed_boundaries(self):
  self.assertEqual(bucket("volume_ratio_20",0.9),"<1x")
  self.assertEqual(bucket("volume_ratio_20",1),"1-2x")
  self.assertEqual(bucket("volume_ratio_20",2),">=2x")
 def test_missing_is_not_inferred(self): self.assertIsNone(bucket("gap_pct",""))
 def test_stats_are_separated_by_strategy_and_bucket(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["strategy_key","pnl_pct","cost_pct","volume_ratio_20"]);w.writeheader()
    w.writerow({"strategy_key":"A","pnl_pct":"1","cost_pct":"0","volume_ratio_20":"0.5"})
    w.writerow({"strategy_key":"A","pnl_pct":"2","cost_pct":"0","volume_ratio_20":"2.5"})
   x=analyze(p)
   self.assertEqual(len([r for r in x if r["feature"]=="volume_ratio_20"]),2)
if __name__=="__main__":unittest.main()
