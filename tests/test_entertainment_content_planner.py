import unittest
from scripts.entertainment_content_planner import plan_content

def item(channel):
 return {"source_event_id":"a"*64,"channel":channel,"working_title":"負けた日の話","status":"DRAFT_INTERNAL","external_publish_allowed":False}

class TestContentPlanner(unittest.TestCase):
 def test_manga_has_four_beats_and_full_cast(self):
  p=plan_content(item("MANGA"))
  self.assertEqual(len(p["beats"]),4);self.assertEqual(len(p["cast"]),4)
  self.assertTrue(p["avoid_generic_ai_prose"]);self.assertFalse(p["external_publish_allowed"])
 def test_x_is_not_same_structure_as_manga(self):
  self.assertNotEqual(plan_content(item("X"))["beats"],plan_content(item("MANGA"))["beats"])
 def test_youtube_has_evidence_beat(self):
  self.assertIn("evidence",plan_content(item("YOUTUBE"))["beats"])
 def test_rejects_publishable_input(self):
  x=item("X");x["external_publish_allowed"]=True
  with self.assertRaises(ValueError): plan_content(x)
 def test_unknown_channel_fails(self):
  with self.assertRaises(ValueError): plan_content(item("BLOG"))

if __name__=="__main__": unittest.main()
