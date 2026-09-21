import unittest
from datetime import tzinfo
from scripts.event_bus import build_event, validate_event

class NullOffsetTZ(tzinfo):
    def utcoffset(self, dt): return None
    def dst(self, dt): return None

class EventBusBoundaryHardeningTest(unittest.TestCase):
    def base(self):
        return build_event(timestamp="2026-09-21T15:00:00+09:00",domain="SYSTEM",event_type="TEST",source="TEST",payload={})
    def test_valid_event_remains_valid(self):
        self.assertTrue(validate_event(self.base()))
    def test_unknown_top_level_field_fails_closed(self):
        e=self.base(); e["order_id"]="private-or-unknown"
        self.assertFalse(validate_event(e))
    def test_missing_optional_contract_key_fails_closed(self):
        e=self.base(); del e["symbol"]
        self.assertFalse(validate_event(e))
    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError): build_event(timestamp="2026-09-21T15:00:00",domain="SYSTEM",event_type="TEST",source="TEST",payload={})

# ci-trigger: replacement PR on latest main

