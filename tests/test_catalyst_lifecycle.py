import unittest
from scripts.catalyst_lifecycle import catalyst_snapshot,lifecycle_features

class CatalystLifecycleTests(unittest.TestCase):
 def events(self):
  return [
   {"event_id":"x","state":"RUMOR","observed_at":"2026-09-17T10:00:00"},
   {"event_id":"x","state":"REPORTED","observed_at":"2026-09-17T20:00:00"},
   {"event_id":"x","state":"CONFIRMED","observed_at":"2026-09-18T10:00:00"},
  ]

 def test_open_sees_report_not_later_confirmation(self):
  s=catalyst_snapshot(self.events(),"2026-09-18T09:00:00")
  self.assertEqual(len(s),1)
  self.assertEqual(s[0]["state"],"REPORTED")

 def test_after_confirmation_same_event_is_not_double_counted(self):
  f=lifecycle_features(self.events(),"2026-09-18T11:00:00")
  self.assertEqual(f["known_event_count"],1)
  self.assertEqual(f["confirmed_count"],1)
  self.assertEqual(f["rumor_count"],0)

 def test_future_only_event_is_invisible(self):
  f=lifecycle_features(self.events(),"2026-09-17T09:00:00")
  self.assertEqual(f["known_event_count"],0)
  self.assertEqual(f["catalyst_states"],"NONE")

if __name__=="__main__": unittest.main()
