import unittest
from scripts.regime_shift_ev import compare_regime_shift_ev,stratify_shift_ev

class RegimeShiftEVTests(unittest.TestCase):
 def test_shift_and_stable_are_not_pooled(self):
  rows=[
   {"net_pnl":1,"regime_shift_candidate":False},
   {"net_pnl":-2,"regime_shift_candidate":True}]
  x=compare_regime_shift_ev(rows)
  self.assertEqual(x["stable"]["avg_net_pnl"],1)
  self.assertEqual(x["shift_candidate"]["avg_net_pnl"],-2)
  self.assertFalse(x["causal_claim"])

 def test_small_n_remains_reference_only(self):
  x=compare_regime_shift_ev([{"net_pnl":1,"regime_shift_candidate":True}])
  self.assertEqual(x["shift_candidate"]["evidence_status"],"REFERENCE_ONLY")

 def test_setup_time_cluster_are_separate(self):
  rows=[
   {"net_pnl":1,"regime_shift_candidate":False,"setup":"OR15","time_bucket":"10:00","empirical_cluster":"R1"},
   {"net_pnl":2,"regime_shift_candidate":False,"setup":"VWAP","time_bucket":"10:00","empirical_cluster":"R1"}]
  self.assertEqual(len(stratify_shift_ev(rows)),2)

if __name__=="__main__": unittest.main()
