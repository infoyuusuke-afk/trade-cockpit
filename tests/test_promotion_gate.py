import unittest
from scripts.promotion_gate import evaluate
class PromotionGateTests(unittest.TestCase):
 def good(self):
  cal={"groups":{"A":{"sample_size":100,"profit_factor":1.5,"avg_pl_pct":.2,"max_dd_pct":-5}}}
  oos={"oos":{"groups":{"A":{"sample_size":30,"profit_factor":1.3,"avg_pl_pct":.1}}}}
  wf={"stability":{"A":{"oos_folds":5,"positive_edge_fold_rate":.8}}}
  return cal,oos,wf
 def test_good_evidence_is_candidate_not_live(self):
  c,o,w=self.good();r=evaluate("A",c,o,w);self.assertEqual(r["status"],"CANDIDATE");self.assertFalse(r["live_eligible"])
 def test_missing_oos_fails_closed(self):
  c,o,w=self.good();r=evaluate("A",c,{},w);self.assertEqual(r["status"],"RESEARCH");self.assertIn("OOS_EVIDENCE_MISSING",r["reasons"])
 def test_unstable_walk_forward_stays_research(self):
  c,o,w=self.good();w["stability"]["A"]["positive_edge_fold_rate"]=.4;r=evaluate("A",c,o,w);self.assertEqual(r["status"],"RESEARCH")
if __name__=="__main__":unittest.main()
