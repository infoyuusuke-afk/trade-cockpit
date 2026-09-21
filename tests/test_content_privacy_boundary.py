import unittest
from scripts.content_privacy_boundary import sanitize_event_for_content
from scripts.entertainment_pipeline import story_candidates
class ContentPrivacyBoundaryTest(unittest.TestCase):
 def event(self):
  return {"event_id":"e1","event_type":"TRADE_RESULT","timestamp":"2026-09-21T15:00:00+09:00","payload":{"summary":"OR15 worked","symbol":"TSE:285A","order_id":"secret","account_id":"secret","fills":[1],"board":{"bid":1},"unknown_private":"x"}}
 def test_sensitive_and_unknown_payload_removed(self):
  p=sanitize_event_for_content(self.event())["payload"];self.assertEqual(p,{"summary":"OR15 worked","symbol":"TSE:285A"})
 def test_source_not_mutated(self):
  e=self.event();sanitize_event_for_content(e);self.assertIn("order_id",e["payload"])
 def test_story_uses_sanitized_summary_only(self):
  c=story_candidates([self.event()])[0];self.assertEqual(c["title_seed"],"OR15 worked");self.assertFalse(c["external_publish_allowed"]);self.assertTrue(c["owner_approval_required"])
 def test_nested_sensitive_not_forwarded(self):
  e=self.event();e["payload"]["summary"]={"account":"x"};p=sanitize_event_for_content(e)["payload"];self.assertNotIn("summary",p)
