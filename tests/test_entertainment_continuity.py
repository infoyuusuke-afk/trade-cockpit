import unittest
from scripts.entertainment_continuity import apply_event
class TestContinuity(unittest.TestCase):
 def test_growth_accumulates(self):
  s=apply_event({},{"sanitized":True,"character_growth":[{"character":"MUGI","axis":"patience","delta":1}]})
  self.assertEqual(s["MUGI"]["patience"],1)
 def test_setback_is_preserved(self):
  s=apply_event({"MUGI":{"patience":2}},{"sanitized":True,"character_growth":[{"character":"MUGI","axis":"patience","delta":-1}]})
  self.assertEqual(s["MUGI"]["patience"],1)
 def test_unsanitized_rejected(self):
  with self.assertRaises(ValueError): apply_event({},{"sanitized":False})
 def test_large_growth_rejected(self):
  with self.assertRaises(ValueError): apply_event({},{"sanitized":True,"character_growth":[{"character":"HAMU","axis":"warmth","delta":5}]})
if __name__=="__main__": unittest.main()
