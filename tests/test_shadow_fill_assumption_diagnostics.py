import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location("sfa_c106",ROOT/"scripts/shadow_forward_acceptance.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class FillAssumptionDiagnosticsTest(unittest.TestCase):
 def test_v01_limit_assumptions_are_explicit_and_uncalibrated(self):
  a=m.FILL_MODEL_ASSUMPTIONS["shadow-fill-model-0.1"]
  self.assertTrue(a["limit_trade_through_full_requested_qty"])
  self.assertFalse(a["limit_queue_position_modeled"])
  self.assertFalse(a["limit_visible_liquidity_modeled"])
  self.assertEqual(a["calibration_status"],"UNCALIBRATED_ASSUMPTION")
