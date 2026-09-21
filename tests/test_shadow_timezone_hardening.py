import unittest
from datetime import datetime,tzinfo
import scripts.shadow_execution as se
import scripts.shadow_position as sp
import scripts.shadow_fill_model as sfm
class NullOffsetTZ(tzinfo):
 def utcoffset(self,dt): return None
 def dst(self,dt): return None
class ShadowTimezoneHardeningTest(unittest.TestCase):
 def bad(self): return datetime(2026,9,21,15,0,tzinfo=NullOffsetTZ())
 def test_position_helper_rejects_null_offset(self): self.assertFalse(sp._is_aware_datetime(self.bad()))
 def test_execution_helper_rejects_null_offset(self): self.assertFalse(se._is_aware_datetime(self.bad()))
 def test_fill_model_now_rejects_null_offset(self):
  ok,reasons=sfm.validate_observation({"observed_at":self.bad()},now=self.bad());self.assertFalse(ok);self.assertTrue(reasons)
