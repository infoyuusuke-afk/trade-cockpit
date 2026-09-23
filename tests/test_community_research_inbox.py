import unittest
from scripts.community_research_inbox import ingest_lead,promote_verified
class TestCommunityInbox(unittest.TestCase):
 def base(self): return {"source_type":"GLOBAL_REPLY","received_at":"2026-09-24T12:00:00Z","claim":"Example market observation","language":"en"}
 def test_quarantines_claim(self):
  x=ingest_lead(self.base());self.assertEqual(x["status"],"UNVERIFIED_RESEARCH_LEAD");self.assertFalse(x["may_affect_signal"])
 def test_needs_independent_evidence(self):
  with self.assertRaises(ValueError): promote_verified(ingest_lead(self.base()),[])
 def test_private_data_rejected(self):
  x=self.base();x["contains_private_data"]=True
  with self.assertRaises(ValueError): ingest_lead(x)
if __name__=="__main__": unittest.main()
