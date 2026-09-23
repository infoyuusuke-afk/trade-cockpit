import unittest
from scripts.developer_growth_story import project_growth_event

class TestDeveloperGrowthStory(unittest.TestCase):
 def base(self):
  return {"skill":"debugging","delta":1,"event":"CI failure was isolated and fixed","lesson":"Read the failing contract before changing code","verified":True,"sanitized":True}
 def test_projects_growth_to_entertainment_event(self):
  x=project_growth_event(self.base())
  self.assertEqual(x["event_type"],"DEVELOPMENT_MILESTONE")
  self.assertEqual(x["growth"]["skill"],"debugging")
  self.assertFalse(x["external_publish_allowed"])
 def test_is_deterministic(self):
  self.assertEqual(project_growth_event(self.base())["event_id"],project_growth_event(self.base())["event_id"])
 def test_rejects_unverified(self):
  x=self.base();x["verified"]=False
  with self.assertRaises(ValueError): project_growth_event(x)
 def test_rejects_unsanitized(self):
  x=self.base();x["sanitized"]=False
  with self.assertRaises(ValueError): project_growth_event(x)
 def test_rejects_score_inflation(self):
  x=self.base();x["delta"]=10
  with self.assertRaises(ValueError): project_growth_event(x)

if __name__=="__main__": unittest.main()
