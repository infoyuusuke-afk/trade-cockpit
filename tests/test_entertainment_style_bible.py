import json,unittest
from pathlib import Path

class TestEntertainmentStyleBible(unittest.TestCase):
 def setUp(self):
  self.data=json.loads(Path("data/entertainment_style_bible.v1.json").read_text(encoding="utf-8"))
 def test_locked_modes(self):
  self.assertEqual(self.data["diary_visual_mode"],"COMPACT_DEFORMED")
  self.assertEqual(self.data["human_visual_mode"],"HIGH_DETAIL_ORIGINAL_JRPG_CINEMATIC")
  self.assertEqual(self.data["music_mode"],"ORIGINAL_MODERN_JAPANESE_HARD_ROCK")
 def test_human_editorial_and_publish_guard(self):
  self.assertIs(self.data["human_editorial_required"],True)
  self.assertIs(self.data["external_publish_allowed"],False)

if __name__=="__main__": unittest.main()
