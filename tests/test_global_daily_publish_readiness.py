import unittest
from scripts.global_daily_publish_readiness import build_packet,approve_packet
class TestReadiness(unittest.TestCase):
 def base(self): return {"locale":"en","date_jst":"2026-09-24","owner_traded":False,"external_publish_allowed":False}
 def test_no_trade_can_be_review_ready(self):
  x=build_packet(self.base(),[]);self.assertEqual(x["status"],"READY_FOR_OWNER_REVIEW");self.assertFalse(x["publish_allowed"])
 def test_quality_blocks(self):
  x=build_packet(self.base(),["CLAIM_WITHOUT_EVIDENCE"]);self.assertEqual(x["status"],"BLOCKED")
 def test_approval_still_has_no_publisher(self):
  x=approve_packet(build_packet(self.base(),[]));self.assertFalse(x["publish_allowed"]);self.assertIsNone(x["publication_action"])
if __name__=="__main__": unittest.main()
