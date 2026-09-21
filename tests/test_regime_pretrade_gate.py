import unittest
from scripts.regime_pretrade_gate import derive_gate_tags,regime_aware_pretrade_gate

class RegimePretradeGateTests(unittest.TestCase):
 def test_semicon_cluster_adds_semicon_checks(self):
  self.assertIn("SEMICON",derive_gate_tags([], "SEMICON_HIGH_VOL", []))

 def test_index_sensitive_tag_adds_futures_check(self):
  done=["DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME"]
  x=regime_aware_pretrade_gate(
   {"proposed_action":"LONG","data_fresh":True},done,
   {"regime_tags":["INDEX_SENSITIVE"],"empirical_cluster":"R1"})
  self.assertEqual(x["decision"],"WAIT")
  self.assertIn("INDEX_FUTURES",x["missing_checks"])

 def test_declared_category_only_adds_safety_check(self):
  tags=derive_gate_tags([],"R1",["半導体"])
  self.assertIn("SEMICON",tags)

 def test_complete_semicon_context_can_pass(self):
  done=["DATA_FRESH","MARKET_REGIME","CATALYST","TIME_REGIME",
        "US_SEMICON","KOREA_SEMICON"]
  x=regime_aware_pretrade_gate(
   {"proposed_action":"SHORT","data_fresh":True},done,
   {"empirical_cluster":"SEMICON","regime_shift_candidate":True})
  self.assertTrue(x["gate_pass"])
  self.assertEqual(x["decision"],"SHORT")
  self.assertTrue(x["regime_shift_candidate"])

if __name__=="__main__": unittest.main()
