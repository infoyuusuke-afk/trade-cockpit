import unittest
from scripts.ai_council import council_snapshot
class CouncilInputHardeningTest(unittest.TestCase):
 def msg(self): return {"agent":"RISK","topic":"health","stance":"REVIEW","proposal":None,"evidence":[],"confidence":0.8,"risk":"stale","timestamp":"2026-09-21T15:00:00+09:00"}
 def test_valid(self): self.assertEqual(council_snapshot([self.msg()])["status"],"REVIEW")
 def test_unknown_field(self): m=self.msg();m["extra"]=1;self.assertRaises(ValueError,council_snapshot,[m])
 def test_missing_agent(self): m=self.msg();m["agent"]="";self.assertRaises(ValueError,council_snapshot,[m])
 def test_naive_timestamp(self): m=self.msg();m["timestamp"]="2026-09-21T15:00:00";self.assertRaises(ValueError,council_snapshot,[m])
 def test_unstructured_evidence(self): m=self.msg();m["evidence"]="trust me";self.assertRaises(ValueError,council_snapshot,[m])
 def test_real_submit_never_enabled(self): self.assertFalse(council_snapshot([self.msg()])["real_submit_allowed"])

# ci-trigger: approved replacement on latest main
# ci-trigger-2
