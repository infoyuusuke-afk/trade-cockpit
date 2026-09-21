import unittest
from datetime import datetime,tzinfo
from scripts.event_intake_guard import intake
from scripts.commentary_scheduler import schedule
class NullTZ(tzinfo):
 def utcoffset(self,dt): return None
 def dst(self,dt): return None
class TimeBoundaryHardeningTest(unittest.TestCase):
 def test_intake_rejects_non_dict_without_crash(self):
  r=intake([None],now=datetime.fromisoformat("2026-09-21T15:00:00+09:00"));self.assertEqual(r["status"],"BLOCK");self.assertEqual(r["rejected"][0]["reason"],"INVALID_EVENT")
 def test_intake_requires_list(self): self.assertRaises(ValueError,intake,{},now=datetime.fromisoformat("2026-09-21T15:00:00+09:00"))
 def test_commentary_rejects_malformed_candidate(self): self.assertRaises(ValueError,schedule,[{"timestamp":"2026-09-21T15:00:00+09:00"}])
 def test_commentary_skips_backward_time(self):
  c={"priority":1,"timestamp":"2026-09-21T14:59:00+09:00","event_id":"e"};self.assertEqual(schedule([c],last_spoken_at="2026-09-21T15:00:00+09:00"),[])
