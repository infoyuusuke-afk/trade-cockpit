import importlib.util,unittest
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).parents[1];spec=importlib.util.spec_from_file_location("fmc",ROOT/"scripts/fill_model_calibration.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def rec(**kw):
 r={"model_version":"shadow-fill-model-0.1","observed_at":datetime(2026,9,21,tzinfo=timezone.utc),"order_type":"LIMIT","side":"BUY","requested_qty":100,"predicted_fill_qty":100,"observed_fill_qty":40,"predicted_fill_price":1500.0,"observed_fill_price":1501.0};r.update(kw);return r
class CalibrationContractTest(unittest.TestCase):
 def test_small_sample_remains_unknown(self):
  o=m.evaluate([rec()]);self.assertEqual(o["status"],"INSUFFICIENT_SAMPLE");self.assertFalse(o["parameter_update_allowed"]);self.assertFalse(o["real_submit_allowed"])
 def test_metrics_are_descriptive(self):
  o=m.evaluate([rec()]);self.assertEqual(o["fill_qty_mae"],60);self.assertEqual(o["fill_rate_bias"],0);self.assertEqual(o["fill_price_mae_yen"],1)
 def test_naive_time_invalid(self):
  o=m.evaluate([rec(observed_at=datetime(2026,9,21))]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)
 def test_overfill_invalid(self):
  o=m.evaluate([rec(observed_fill_qty=101)]);self.assertEqual(o["sample_size"],0)
 def test_threshold_only_enables_review_not_parameter_update(self):
  o=m.evaluate([rec() for _ in range(m.MIN_SAMPLE)]);self.assertEqual(o["status"],"CALIBRATION_REVIEW_ELIGIBLE");self.assertFalse(o["parameter_update_allowed"]);self.assertFalse(o["real_submit_allowed"])

class StratifiedCalibrationTest(unittest.TestCase):
 def test_market_and_limit_do_not_share_stratum_threshold(self):
  rows=[rec(order_type="LIMIT") for _ in range(25)]+[rec(order_type="MARKET") for _ in range(25)]
  o=m.evaluate(rows);self.assertEqual(o["status"],"CALIBRATION_REVIEW_ELIGIBLE");self.assertEqual(o["strata"]["shadow-fill-model-0.1|LIMIT|BUY"]["status"],"INSUFFICIENT_SAMPLE");self.assertEqual(o["strata"]["shadow-fill-model-0.1|MARKET|BUY"]["status"],"INSUFFICIENT_SAMPLE")
 def test_buy_and_sell_are_separate(self):
  o=m.evaluate([rec(side="BUY"),rec(side="SELL")]);self.assertEqual(len(o["strata"]),2)
