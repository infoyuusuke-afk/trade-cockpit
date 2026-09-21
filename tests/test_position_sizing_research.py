import unittest
from scripts.position_sizing_research import simulate_staged_long,compare_fixed_vs_staged

class PositionSizingResearchTests(unittest.TestCase):
 def rows(self):
  return [
   {"open":100,"high":101,"low":98,"close":99},
   {"open":96,"high":98,"low":94,"close":95},
   {"open":92,"high":97,"low":90,"close":96},
   {"open":105,"high":108,"low":103,"close":107},
  ]

 def test_staged_average_is_weighted(self):
  x=simulate_staged_long(self.rows(),[
   {"index":0,"weight":.25},{"index":1,"weight":.25},{"index":2,"weight":.50}])
  self.assertAlmostEqual(x["avg_entry"],95.0)
  self.assertTrue(x["research_only"])

 def test_compare_does_not_emit_action(self):
  x=compare_fixed_vs_staged(self.rows(),[0,1,2])
  self.assertIn("FIXED",x); self.assertIn("STAGED_25_25_50",x)
  self.assertNotIn("action",x)

 def test_weights_must_sum_to_one(self):
  with self.assertRaises(ValueError):
   simulate_staged_long(self.rows(),[{"index":0,"weight":.5}])

if __name__=="__main__": unittest.main()
