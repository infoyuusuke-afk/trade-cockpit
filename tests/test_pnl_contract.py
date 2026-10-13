import unittest
from scripts.calibrate_ev import stats
from scripts.export_ev_trades import rows

class PnlContractTests(unittest.TestCase):
 def test_export_contract_applies_cost_once(self):
  record={
   "strategy_key":"X","strategy_id":"X","triggered":True,
   "execution_type":"PAPER_OBSERVED",
   "fill_evidence":{"entry_fill_id":"in-1","exit_fill_id":"out-1",
                    "entry_source":"OBSERVED","exit_source":"OBSERVED"},
   "entry_fill_price":100.0,"exit_fill_price":101.0,
   "entry_ts":"2026-10-13T09:01:00+09:00",
   "exit_ts":"2026-10-13T09:10:00+09:00",
   "cost_pct":0.1,"cost_model_status":"VERIFIED",
   "side":"LONG","ticker":"285A.T"
  }
  r=rows([record])[0]
  self.assertAlmostEqual(r["gross_pnl_pct"],1.0)
  self.assertAlmostEqual(r["cost_pct"],0.1)
  self.assertAlmostEqual(r["net_pnl_pct"],0.9)
  self.assertAlmostEqual(r["pnl_pct"],0.9)
 def test_close_mark_without_fill_evidence_must_never_be_exported(self):
  self.assertEqual(rows([{"strategy_key":"X","triggered":True,"entry":100,
                         "close":101,"side":"LONG","cost_pct":0.1}]),[])
 def test_stats_receives_net_value(self):
  self.assertEqual(stats([0.9])["avg_pl_pct"],0.9)
if __name__=="__main__":unittest.main()
