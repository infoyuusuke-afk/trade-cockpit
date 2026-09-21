import unittest
from scripts.analyze_open_entry_ev import compare_entry_delays,summarize_entry_policies,fixed_regime_labels,attach_regime,summarize_by_regime

class OpenEntryEVTests(unittest.TestCase):
 def rows(self):
  out=[]
  for i in range(25):
   sec=i*15; mm=sec//60; ss=sec%60
   px=100+i
   out.append({"ts":f"2026-09-18 09:{mm:02d}:{ss:02d}","open":px,"high":px+1,"low":px-1,"close":px,"volume":10})
  return out

 def test_entry_policies_use_first_observed_print_as_anchor(self):
  r=compare_entry_delays(self.rows(),"LONG",0)
  by={x["entry_policy"]:x for x in r}
  self.assertEqual(by["OPEN"]["entry_ts"],"2026-09-18 09:00:00")
  self.assertEqual(by["WAIT_15S"]["entry_ts"],"2026-09-18 09:00:15")
  self.assertEqual(by["WAIT_30S"]["entry_ts"],"2026-09-18 09:00:30")
  self.assertEqual(by["WAIT_60S"]["entry_ts"],"2026-09-18 09:01:00")
  self.assertEqual(by["OR5_WAIT"]["entry_ts"],"2026-09-18 09:05:00")
  for x in r:
   self.assertEqual(x["decision_ts"],x["information_cutoff_ts"])
   self.assertEqual(x["decision_ts"],x["entry_ts"])

 def test_cost_is_subtracted_once(self):
  r=compare_entry_delays(self.rows(),"LONG",0.1)
  for x in r:
   self.assertAlmostEqual(x["net_pnl_pct"],x["gross_pnl_pct"]-0.1)
   self.assertEqual(x["pnl_pct"],x["net_pnl_pct"])

 def test_mfe_mae_and_waiting_opportunity_cost(self):
  r=compare_entry_delays(self.rows(),"LONG",0)
  by={x["entry_policy"]:x for x in r}
  self.assertGreater(by["OPEN"]["mfe_pct"],0)
  self.assertLess(by["OPEN"]["mae_pct"],0)
  self.assertEqual(by["OPEN"]["missed_move_pct_vs_open"],0)
  self.assertGreater(by["WAIT_60S"]["missed_move_pct_vs_open"],0)

 def test_short_direction_is_symmetric(self):
  long=compare_entry_delays(self.rows(),"LONG",0)[0]
  short=compare_entry_delays(self.rows(),"SHORT",0)[0]
  self.assertAlmostEqual(long["gross_pnl_pct"],-short["gross_pnl_pct"])

 def test_summary_is_research_only_and_has_risk_metrics(self):
  all_results=[]
  for side in ("LONG","SHORT"):
   all_results += compare_entry_delays(self.rows(),side,0.1)
  s=summarize_entry_policies(all_results)
  self.assertEqual({x["entry_policy"] for x in s},{"OPEN","WAIT_15S","WAIT_30S","WAIT_60S","OR5_WAIT"})
  for x in s:
   self.assertEqual(x["sample_size"],2)
   self.assertTrue(x["research_only"])
   self.assertIn("profit_factor",x)
   self.assertIn("avg_mfe_pct",x)
   self.assertIn("avg_mae_pct",x)
   self.assertIn("avg_missed_move_pct_vs_open",x)

 def test_fixed_regimes_are_deterministic(self):
  x=fixed_regime_labels({"gap_pct":2.0,"intraday_range_pct":2.5,"open_state":"DELAYED_OPEN_UNCLASSIFIED"})
  self.assertEqual(x["gap_regime"],"GU_GT_1")
  self.assertEqual(x["vol_regime"],"HIGH_GE_2")
  self.assertEqual(x["open_regime"],"DELAYED_OPEN_UNCLASSIFIED")

 def test_regime_summary_keeps_entry_policies_separate(self):
  r=compare_entry_delays(self.rows(),"LONG",0.1)
  r=attach_regime(r,{"gap_pct":-2.0,"intraday_range_pct":1.5,"open_state":"NORMAL_OPEN"})
  s=summarize_by_regime(r,"gap_regime")
  self.assertIn("GD_LT_-1",s)
  self.assertEqual(len(s["GD_LT_-1"]),5)

if __name__=="__main__": unittest.main()
