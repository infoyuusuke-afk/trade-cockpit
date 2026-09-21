import unittest
from scripts.execution_validation_ladder import execution_stage_gate

class ExecutionValidationLadderTests(unittest.TestCase):
 def test_candidate_advances_only_to_shadow(self):
  x=execution_stage_gate("RESEARCH",{"promotion_status":"CANDIDATE"})
  self.assertEqual(x["next_stage"],"SHADOW")
  self.assertFalse(x["auto_execute"])

 def test_cheap_but_illiquid_does_not_reach_real_money(self):
  e={"paper_samples":50,"paper_avg_net_pnl_pct":0.2,
     "median_spread_bps":10,"median_daily_turnover_jpy":100_000_000}
  x=execution_stage_gate("PAPER",e)
  self.assertEqual(x["next_stage"],"PAPER")
  self.assertIn("LIQUIDITY_TOO_LOW",x["reasons"])

 def test_liquid_paper_candidate_requires_owner_approval_for_min_lot(self):
  e={"paper_samples":50,"paper_avg_net_pnl_pct":0.2,
     "median_spread_bps":8,"median_daily_turnover_jpy":1_000_000_000}
  x=execution_stage_gate("PAPER",e)
  self.assertEqual(x["next_stage"],"MIN_LOT_LIVE")
  self.assertTrue(x["owner_approval_required"])
  self.assertFalse(x["auto_execute"])

 def test_bad_live_execution_blocks_scaling(self):
  e={"live_samples":50,"live_avg_net_pnl_pct":0.2,"fill_rate":0.85,"avg_slippage_bps":20}
  x=execution_stage_gate("MIN_LOT_LIVE",e)
  self.assertEqual(x["next_stage"],"MIN_LOT_LIVE")
  self.assertIn("FILL_RATE_TOO_LOW",x["reasons"])
  self.assertIn("SLIPPAGE_TOO_HIGH",x["reasons"])

if __name__=="__main__": unittest.main()
