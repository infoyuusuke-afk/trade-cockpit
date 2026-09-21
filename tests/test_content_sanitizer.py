import unittest
from scripts.event_bus import build_event
from scripts.content_sanitizer import sanitize_event
from scripts.entertainment_pipeline import story_candidates
class ContentSanitizerTest(unittest.TestCase):
 def ev(self,payload=None):
  return build_event(timestamp="2026-09-21T15:00:00+09:00",domain="SYSTEM",event_type="SYSTEM_INCIDENT",source="TEST",payload=payload or {"summary":"watchdog stopped"})
 def test_minimal_projection(self):
  s=sanitize_event(self.ev());self.assertEqual(s["content_visibility"],"SANITIZED_INTERNAL");self.assertFalse(s["external_publish_allowed"]);self.assertNotIn("payload",s)
 def test_sensitive_nested_key_rejected(self):
  self.assertRaises(ValueError,sanitize_event,self.ev({"summary":"x","meta":{"account":"secret"}}))
 def test_raw_event_cannot_enter_entertainment(self): self.assertRaises(ValueError,story_candidates,[self.ev()])
 def test_sanitized_event_can_enter(self): self.assertEqual(len(story_candidates([sanitize_event(self.ev())])),1)
