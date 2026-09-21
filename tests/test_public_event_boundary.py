import copy
import unittest

from scripts.entertainment_pipeline import story_candidates
from scripts.event_bus import build_event
from scripts.public_event_sanitizer import sanitize_event


class PublicEventBoundaryTests(unittest.TestCase):
    def event(self, payload):
        return build_event(
            timestamp="2026-09-21T21:00:00+09:00",
            domain="SYSTEM",
            event_type="DEVELOPMENT_MILESTONE",
            source="test",
            payload=payload,
        )

    def test_safe_summary_projects_without_mutating_source(self):
        source=self.event({"summary":"Shadow検証の安全ゲートを更新"})
        before=copy.deepcopy(source)
        public=sanitize_event(source)
        self.assertEqual(source,before)
        self.assertEqual(set(public),{"event_id","timestamp","event_type","summary"})
        candidate=story_candidates([public])[0]
        self.assertFalse(candidate["external_publish_allowed"])
        self.assertTrue(candidate["owner_approval_required"])

    def test_sensitive_key_rejected_recursively(self):
        source=self.event({"summary":"x","meta":{"position_id":"secret"}})
        with self.assertRaises(ValueError):
            sanitize_event(source)

    def test_non_allowlisted_payload_rejected(self):
        source=self.event({"summary":"x","context":"internal detail"})
        with self.assertRaises(ValueError):
            sanitize_event(source)

    def test_raw_event_cannot_enter_entertainment_pipeline(self):
        source=self.event({"summary":"safe text"})
        with self.assertRaises(ValueError):
            story_candidates([source])

    def test_missing_summary_fails_closed(self):
        source=self.event({})
        with self.assertRaises(ValueError):
            sanitize_event(source)
