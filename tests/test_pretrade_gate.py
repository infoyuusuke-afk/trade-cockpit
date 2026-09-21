import unittest
from scripts.pretrade_gate import pretrade_gate,required_checks

class PretradeGateTests(unittest.TestCase):
 def test_semiconductor_requires_us_and_korea_checks(self):
  req=required_checks(["SEMICON"])
  self.assertIn("US_SEMICON",req); self.assertIn("KOREA_SEMICON",req)

 def test_missing_check_forces_wait_even_if_long_proposed(self):
  x=pretrade_gate({"proposed_action":"LONG","data_fresh":True},
   ["DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME","US_SEMICON"],
   ["SEMICON"])
  self.assertEqual(x["decision"],"WAIT")
  self.assertIn("KOREA_SEMICON",x["missing_checks"])

 def test_complete_gate_preserves_proposed_action(self):
  done=["DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME",
        "US_SEMICON","KOREA_SEMICON"]
  x=pretrade_gate({"proposed_action":"LONG","data_fresh":True},done,["SEMICON"])
  self.assertTrue(x["gate_pass"])
  self.assertEqual(x["decision"],"LONG")
  self.assertFalse(x["auto_execute"])

 def test_stale_data_forces_wait(self):
  done=["DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME"]
  x=pretrade_gate({"proposed_action":"SHORT","data_fresh":False},done,[])
  self.assertEqual(x["decision"],"WAIT")

if __name__=="__main__": unittest.main()
