import unittest
from scripts.calibrate_ev import stats
from scripts.export_ev_trades import rows
class PnlContractTests(unittest.TestCase):
 def test_export_contract_applies_cost_once(self):
  r=rows([{"strategy_key":"X","triggered":True,"entry":100,"close":101,"side":"LONG","cost_pct":0.1}])[0]
  self.assertAlmostEqual(r["gross_pnl_pct"],1.0)
  self.assertAlmostEqual(r["cost_pct"],0.1)
  self.assertAlmostEqual(r["net_pnl_pct"],0.9)
  self.assertAlmostEqual(r["pnl_pct"],0.9)
 def test_stats_receives_net_value(self):
  self.assertEqual(stats([0.9])["avg_pl_pct"],0.9)
if __name__=="__main__":unittest.main()
