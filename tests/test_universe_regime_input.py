import unittest
from scripts.universe_regime_input import combine_universes,detect_regime_mismatch

class UniverseRegimeInputTests(unittest.TestCase):
 def test_top100_and_tab_are_combined_with_provenance(self):
  rows=[
   {"as_of":"2026-09-21","symbol":"285A","name":"Kioxia","source":"DAYTRADE_TOP100","source_rank":3},
   {"as_of":"2026-09-21","symbol":"285A","name":"Kioxia","source":"COCKPIT_TAB",
    "cockpit_tab":"HIGH_VOL","declared_category":"SEMICON_HIGH_VOL"}]
  x=combine_universes(rows)[0]
  self.assertEqual(x["top100_rank"],3)
  self.assertIn("DAYTRADE_TOP100",x["sources"])
  self.assertIn("HIGH_VOL",x["cockpit_tabs"])

 def test_declared_category_is_not_ground_truth(self):
  row={"symbol":"285A","declared_categories":["SEMICON_HIGH_VOL"]}
  x=detect_regime_mismatch(row,"EVENT_FLOW",{"SEMICON_HIGH_VOL":"NORMAL_HIGH_VOL"})
  self.assertTrue(x["regime_shift_candidate"])
  self.assertEqual(x["empirical_cluster"],"EVENT_FLOW")

 def test_unknown_declared_category_does_not_force_mismatch(self):
  row={"symbol":"X","declared_categories":["UNKNOWN"]}
  x=detect_regime_mismatch(row,"R2",{})
  self.assertFalse(x["regime_shift_candidate"])

if __name__=="__main__": unittest.main()
