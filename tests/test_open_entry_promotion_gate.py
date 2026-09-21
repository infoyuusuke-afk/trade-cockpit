import unittest
from scripts.open_entry_promotion_gate import entry_policy_gate

class OpenEntryPromotionGateTests(unittest.TestCase):
 def good(self):
  return {"entry_policy":"WAIT_15S","sample_size":50,"profit_factor":1.3,
          "avg_net_pnl_pct":0.2,"max_drawdown_pct":-5}

 def test_in_sample_alone_never_promotes(self):
  x=entry_policy_gate(self.good())
  self.assertEqual(x["status"],"RESEARCH")
  self.assertFalse(x["live_eligible"])
  self.assertIn("OOS_NOT_VALIDATED",x["reasons"])
  self.assertIn("WALK_FORWARD_NOT_VALIDATED",x["reasons"])

 def test_all_evidence_only_reaches_candidate(self):
  oos={"sample_size":20,"profit_factor":1.2,"avg_net_pnl_pct":0.1}
  wf={"oos_fold_count":3,"positive_edge_fold_rate":0.67}
  x=entry_policy_gate(self.good(),oos,wf)
  self.assertEqual(x["status"],"CANDIDATE")
  self.assertEqual(x["reasons"],[])
  self.assertFalse(x["live_eligible"])

 def test_large_drawdown_blocks(self):
  s=self.good(); s["max_drawdown_pct"]=-12
  oos={"sample_size":20,"profit_factor":1.2,"avg_net_pnl_pct":0.1}
  wf={"oos_fold_count":3,"positive_edge_fold_rate":0.67}
  x=entry_policy_gate(s,oos,wf)
  self.assertEqual(x["status"],"RESEARCH")
  self.assertIn("DD_TOO_LARGE",x["reasons"])

if __name__=="__main__": unittest.main()
