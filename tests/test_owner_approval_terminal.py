import unittest
from scripts.owner_approval_queue import build_queue,decide
class OwnerApprovalTerminalTest(unittest.TestCase):
 def item(self): return {"approval_id":"a1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T15:00:00+09:00","summary":"x"}
 def test_decision_is_terminal(self):
  x=build_queue([self.item()])[0]; y=decide(x,"APPROVE")
  with self.assertRaises(ValueError): decide(y,"REJECT")
 def test_reject_is_terminal(self):
  x=decide(build_queue([self.item()])[0],"REJECT")
  with self.assertRaises(ValueError): decide(x,"APPROVE")
 def test_duplicate_ids_rejected(self): self.assertRaises(ValueError,build_queue,[self.item(),self.item()])
 def test_naive_created_at_rejected(self):
  x=self.item();x["created_at"]="2026-09-21T15:00:00";self.assertRaises(ValueError,build_queue,[x])
 def test_mutated_terminal_input_rejected(self):
  x=build_queue([self.item()])[0];x["extra"]=1;self.assertRaises(ValueError,decide,x,"APPROVE")
