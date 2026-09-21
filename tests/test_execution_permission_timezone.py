import unittest
from datetime import datetime,tzinfo
import scripts.execution_permission as ep
class NullOffsetTZ(tzinfo):
 def utcoffset(self,dt): return None
 def dst(self,dt): return None
class ExecutionPermissionTimezoneTest(unittest.TestCase):
 def test_parse_aware_rejects_naive(self): self.assertIsNone(ep._parse_aware("2026-09-21T15:00:00"))
 def test_parse_aware_accepts_real_offset(self): self.assertIsNotNone(ep._parse_aware("2026-09-21T15:00:00+09:00"))
 def test_null_offset_datetime_is_not_valid_now(self):
  bad=datetime(2026,9,21,15,0,tzinfo=NullOffsetTZ())
  self.assertIsNone(bad.utcoffset())
  base={"policy_version":"v0.1"}
  out=ep.evaluate_permission({}, {}, {}, base, now=bad)
  self.assertEqual(out["permission_status"],"BLOCKED")
  self.assertIn("BLOCK_NOW_NOT_TIMEZONE_AWARE",out["block_reasons"])
  self.assertIsNone(out["generated_at"])
