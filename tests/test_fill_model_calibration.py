import importlib.util,unittest
from datetime import datetime,timezone,timedelta
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

class LiquidityContextStrataTest(unittest.TestCase):
 def test_spread_liquidity_time_context_is_separate(self):
  a=rec(spread_yen=1.0,tick_size=1.0,visible_qty=50)
  b=rec(spread_yen=4.0,tick_size=1.0,visible_qty=400)
  o=m.evaluate([a,b]);self.assertEqual(len(o["context_strata"]),2);self.assertTrue(all(v["status"]=="INSUFFICIENT_SAMPLE" for v in o["context_strata"].values()))
 def test_invalid_optional_context_is_rejected(self):
  o=m.evaluate([rec(spread_yen=-1.0,tick_size=1.0,visible_qty=100)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)

class CalibrationCoverageGateTest(unittest.TestCase):
 def test_total_n_does_not_hide_missing_base_strata(self):
  o=m.evaluate([rec(order_type="LIMIT",side="BUY") for _ in range(200)])
  self.assertEqual(o["status"],"CALIBRATION_REVIEW_ELIGIBLE");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT");self.assertIn("shadow-fill-model-0.1|MARKET|SELL",o["insufficient_base_strata"])
 def test_all_base_strata_need_minimum_sample(self):
  rows=[]
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"): rows += [rec(order_type=ot,side=side) for _ in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows);self.assertTrue(all(o["strata"][f"shadow-fill-model-0.1|{ot}|{side}"]["status"]=="CALIBRATION_REVIEW_ELIGIBLE" for ot in ("MARKET","LIMIT") for side in ("BUY","SELL")));self.assertEqual(o["day_coverage_status"],"DAY_COVERAGE_INSUFFICIENT");self.assertFalse(o["parameter_update_allowed"])

class MultiSessionCoverageTest(unittest.TestCase):
 def test_one_day_cannot_satisfy_coverage(self):
  rows=[]
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"): rows += [rec(order_type=ot,side=side) for _ in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows);self.assertEqual(o["day_coverage_status"],"DAY_COVERAGE_INSUFFICIENT");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT")
 def test_five_days_plus_base_strata_can_satisfy_coverage(self):
  rows=[]
  base=datetime(2026,9,1,tzinfo=timezone.utc)
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"):
    rows += [rec(order_type=ot,side=side,observed_at=base+timedelta(days=i % m.MIN_SESSION_DAYS)) for i in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows);self.assertEqual(o["unique_session_days"],m.MIN_SESSION_DAYS);self.assertEqual(o["coverage_status"],"COVERAGE_SUFFICIENT");self.assertFalse(o["parameter_update_allowed"])
