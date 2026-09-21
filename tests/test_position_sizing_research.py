import unittest
from scripts.position_sizing_research import simulate_staged_long,compare_fixed_vs_staged,validate_add_signal,gated_staged_long,evaluate_long_exit_policies

class PositionSizingResearchTests(unittest.TestCase):
 def rows(self):
  return [
   {"open":100,"high":101,"low":98,"close":99},
   {"open":96,"high":98,"low":94,"close":95},
   {"open":92,"high":97,"low":90,"close":96},
   {"open":105,"high":108,"low":103,"close":107},
  ]

 def test_staged_average_is_weighted(self):
  x=simulate_staged_long(self.rows(),[
   {"index":0,"weight":.25},{"index":1,"weight":.25},{"index":2,"weight":.50}])
  self.assertAlmostEqual(x["avg_entry"],95.0)
  self.assertTrue(x["research_only"])

 def test_compare_does_not_emit_action(self):
  x=compare_fixed_vs_staged(self.rows(),[0,1,2])
  self.assertIn("FIXED",x); self.assertIn("STAGED_25_25_50",x)
  self.assertNotIn("action",x)

 def test_weights_must_sum_to_one(self):
  with self.assertRaises(ValueError):
   simulate_staged_long(self.rows(),[{"index":0,"weight":.5}])

 def test_fake_absorption_without_ms2_fails_closed(self):
  with self.assertRaises(ValueError):
   validate_add_signal({"level":"VWAP","level_reaction_confirmed":True,
    "sell_absorption_confirmed":True,"absorption_source":"TRADINGVIEW"})

 def test_level_reaction_can_remain_price_only_research(self):
  x=validate_add_signal({"level":"OR15_LOW","level_reaction_confirmed":True})
  self.assertTrue(x["eligible"])
  self.assertEqual(x["evidence_tier"],"PRICE_LEVEL_ONLY")

 def test_missing_level_reaction_blocks_staged_add(self):
  sig=[{"index":0,"level":"VWAP","level_reaction_confirmed":True},
       {"index":1,"level":"OR5_LOW","level_reaction_confirmed":False},
       {"index":2,"level":"OR15_LOW","level_reaction_confirmed":True}]
  x=gated_staged_long(self.rows(),sig)
  self.assertFalse(x["executed"])
  self.assertEqual(x["reason"],"ADD_GATE_BLOCKED")

 def test_exit_policies_are_reported_not_ranked(self):
  rows=self.rows()
  vwap=[100,99,98,100]
  x=evaluate_long_exit_policies(rows,95,2,1,vwap,0.1)
  names={r["exit_policy"] for r in x}
  self.assertIn("ONE_TICK",names)
  self.assertIn("VWAP_REVERSION",names)
  self.assertIn("EOD",names)
  self.assertTrue(all("rank" not in r and "winner" not in r for r in x))

 def test_exit_cost_is_subtracted_once(self):
  x=evaluate_long_exit_policies(self.rows(),95,2,1,None,0.1)
  for r in x:
   self.assertAlmostEqual(r["net_pnl_pct"],r["gross_pnl_pct"]-0.1)

if __name__=="__main__": unittest.main()
