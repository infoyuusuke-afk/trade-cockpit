import unittest
from scripts.analyze_open_entry_ev import compare_entry_delays

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

if __name__=="__main__": unittest.main()
