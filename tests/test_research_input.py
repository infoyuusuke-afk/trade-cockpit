import unittest
from scripts.research_input import validate_research_input
class ResearchInputTests(unittest.TestCase):
 def core(self):
  return {"symbol":"285A","market_date":"2026-09-18","timestamp":"2026-09-18T09:00:00+09:00","open":100,"high":101,"low":99,"close":100,"volume":10}
 def test_core_only_is_valid(self):
  x=validate_research_input(self.core());self.assertTrue(x["valid"]);self.assertEqual(x["available_layers"],["CORE"])
 def test_context_is_optional(self):
  r=self.core();r["top100_rank"]=3
  self.assertIn("CONTEXT",validate_research_input(r)["available_layers"])
 def test_microstructure_requires_ms2(self):
  r=self.core();r["quote_state"]="NORMAL";r["observed_at"]=r["timestamp"];r["microstructure_source"]="OTHER"
  self.assertFalse(validate_research_input(r)["valid"])
 def test_ms2_microstructure_is_accepted(self):
  r=self.core();r["quote_state"]="SPECIAL_BUY";r["observed_at"]=r["timestamp"];r["microstructure_source"]="MS2"
  x=validate_research_input(r);self.assertTrue(x["valid"]);self.assertTrue(x["microstructure_evidence"])
if __name__=="__main__":unittest.main()
