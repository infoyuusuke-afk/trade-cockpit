import unittest
from scripts.strategy_validation_lab import validate_run,aggregate_partitions
class T(unittest.TestCase):
 def row(self):return {"strategy_id":"DOW_STRUCTURE","trades":100,"train_expectancy":.4,"test_expectancy":.25,"gross_expectancy":.3,"cost_per_trade":.05,"mae_mean":1.2,"mfe_mean":2.1,"regime":"UPTREND","symbol_class":"LARGE_CAP"}
 def test_pass(self):self.assertEqual(validate_run(self.row())["status"],"PASS")
 def test_cost_kills_edge(self):
  x=self.row();x["cost_per_trade"]=.4;self.assertIn("COST_ADJUSTED_NON_POSITIVE",validate_run(x)["reasons"])
 def test_oos_decay_fails(self):
  x=self.row();x["test_expectancy"]=.1;self.assertIn("OOS_DECAY",validate_run(x)["reasons"])
 def test_partitioned(self):
  x=self.row();self.assertIn(("DOW_STRUCTURE","UPTREND","LARGE_CAP"),aggregate_partitions([x]))
 def test_no_live_permission(self):self.assertFalse(validate_run(self.row())["real_submit_allowed"])
if __name__=="__main__":unittest.main()
