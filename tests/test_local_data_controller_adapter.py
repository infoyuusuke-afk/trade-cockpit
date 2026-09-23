import unittest
from scripts.local_data_controller_adapter import adapt
class TestAdapter(unittest.TestCase):
 def test_fresh_verified_ok(self):
  x=adapt({"symbol":"285A","source":"MS2_RSS","observed_at":"2026-09-24T09:00:00+09:00","verified":True},"2026-09-24T09:00:30+09:00")
  self.assertEqual(x["data_health"],"OK")
 def test_stale_degrades(self):
  x=adapt({"symbol":"285A","source":"MS2_RSS","observed_at":"2026-09-24T09:00:00+09:00","verified":True},"2026-09-24T09:02:00+09:00")
  self.assertEqual(x["incident_code"],"STALE_DATA")
 def test_future_blocks(self):
  x=adapt({"symbol":"285A","source":"MS2_RSS","observed_at":"2026-09-24T09:01:00+09:00","verified":True},"2026-09-24T09:00:00+09:00")
  self.assertEqual(x["data_health"],"BLOCKED")
 def test_missing_blocks(self):
  self.assertEqual(adapt({},"2026-09-24T09:00:00+09:00")["data_health"],"BLOCKED")
if __name__=="__main__": unittest.main()
