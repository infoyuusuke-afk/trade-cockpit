import unittest
from scripts import local_source_health_contract as c
from scripts import source_health_event_bridge as b
class LocalSourceHealthContractTests(unittest.TestCase):
 def good(self):
  return {"schema_version":"local-source-health-1.0","source":"MS2_RSS","state":"HEALTHY","observed_at":"2026-09-21T09:10:00+09:00","last_data_at":"2026-09-21T09:09:59+09:00","symbol":"TSE:285A","correlation_id":None,"consecutive_failures":0,"reasons":[]}
 def test_valid(self): self.assertTrue(c.validate(self.good()))
 def test_unknown_field_rejected(self):
  x=self.good(); x["position_qty"]=100; self.assertFalse(c.validate(x))
 def test_naive_timestamp_rejected(self):
  x=self.good(); x["observed_at"]="2026-09-21T09:10:00"; self.assertFalse(c.validate(x))
 def test_negative_failures_rejected(self):
  x=self.good(); x["consecutive_failures"]=-1; self.assertFalse(c.validate(x))
 def test_validated_snapshot_builds_event(self):
  x=self.good(); self.assertTrue(c.validate(x)); e=b.source_health_event(x); self.assertEqual(e["event_type"],"SOURCE_HEALTH")

 def test_missing_required_rejected(self):
  x=self.good(); del x["reasons"]; self.assertFalse(c.validate(x))
 def test_bool_failure_count_rejected(self):
  x=self.good(); x["consecutive_failures"]=True; self.assertFalse(c.validate(x))
 def test_non_string_reason_rejected(self):
  x=self.good(); x["reasons"]=[123]; self.assertFalse(c.validate(x))
 def test_non_string_optional_identity_rejected(self):
  x=self.good(); x["symbol"]=285; self.assertFalse(c.validate(x))
