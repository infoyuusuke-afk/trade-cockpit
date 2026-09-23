import unittest
from scripts.entertainment_department import build_daily_brief

def ev(i,kind="TRADE_RESULT"):
 return {"event_id":("%064x"%i),"timestamp":"2026-09-24T09:00:00+09:00","event_type":kind,"summary":"trade story"}

class TestEntertainmentDepartment(unittest.TestCase):
 def test_three_internal_drafts_per_candidate(self):
  b=build_daily_brief([ev(1)])
  self.assertEqual(b["draft_count"],3)
  self.assertEqual({x["channel"] for x in b["queue"]},{"MANGA","X","YOUTUBE"})
  self.assertTrue(all(not x["external_publish_allowed"] for x in b["queue"]))
  self.assertTrue(all(x["owner_approval_required"] for x in b["queue"]))
  self.assertFalse(b["real_submit_allowed"])
 def test_low_value_note_is_filtered(self):
  b=build_daily_brief([ev(2,"DAILY_NOTE")])
  self.assertEqual(b["status"],"NO_CANDIDATE")
  self.assertEqual(b["queue"],[])
 def test_deterministic(self):
  e=[ev(2,"AI_DISAGREEMENT"),ev(1)]
  self.assertEqual(build_daily_brief(e),build_daily_brief(e))
 def test_unsanitized_rejected(self):
  bad=ev(3);bad["account"]="secret"
  with self.assertRaises(ValueError): build_daily_brief([bad])

if __name__=="__main__": unittest.main()
