import unittest
from scripts.generate_research_report import evidence_label,render
class ReportTests(unittest.TestCase):
 def test_small_sample_is_reference_only(self): self.assertEqual(evidence_label({"sample_size":29,"risk_gate":"PASS"}),"REFERENCE_ONLY")
 def test_pass_needs_minimum_sample(self): self.assertEqual(evidence_label({"sample_size":30,"risk_gate":"PASS"}),"INITIAL_EVIDENCE")
 def test_report_warns_score_not_probability(self):
  x=render({"groups":[]});self.assertIn("EV score is not a probability",x);self.assertIn("walk-forward/OOS",x)
if __name__=="__main__":unittest.main()
