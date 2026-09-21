import unittest
from scripts import owner_approval_queue as q
class OwnerApprovalAuditTest(unittest.TestCase):
 def item(self): return {"approval_id":"a1","approval_type":"MAIN_MERGE","created_at":"2026-09-21T15:00:00+09:00","summary":"x"}
 def test_terminal(self):
  x=q.build_queue([self.item()])[0]; y=q.decide(x,"APPROVE",decided_at="2026-09-21T15:01:00+09:00",decided_by="OWNER")
  self.assertRaises(ValueError,q.decide,y,"REJECT",decided_at="2026-09-21T15:02:00+09:00",decided_by="OWNER")
 def test_audit(self):
  x=q.decide(q.build_queue([self.item()])[0],"REJECT",decided_at="2026-09-21T15:01:00+09:00",decided_by="OWNER")
  self.assertEqual((x["decision"],x["decided_by"]),("REJECT","OWNER"));self.assertFalse(x["auto_approve"])
 def test_duplicate_ids_rejected(self): self.assertRaises(ValueError,q.build_queue,[self.item(),self.item()])
 def test_naive_created_rejected(self):
  x=self.item();x["created_at"]="2026-09-21T15:00:00";self.assertRaises(ValueError,q.build_queue,[x])
