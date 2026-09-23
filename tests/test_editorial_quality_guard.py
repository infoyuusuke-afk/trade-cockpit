import unittest
from scripts.editorial_quality_guard import lint_briefs
class TestEditorialQualityGuard(unittest.TestCase):
 def test_clean(self):
  self.assertEqual(lint_briefs([{"working_title":"赤いCI","beats":["ムギが固まる","ハムがログを見る"],"external_publish_allowed":False}]),[])
 def test_duplicate_title(self):
  x={"working_title":"same","beats":["a"],"external_publish_allowed":False}
  self.assertTrue(any(i["code"]=="DUPLICATE_TITLE" for i in lint_briefs([x,x])))
 def test_canned_phrase(self):
  x={"working_title":"x","beats":["Key takeaway from today"],"external_publish_allowed":False}
  self.assertTrue(any(i["code"]=="CANNED_PHRASE" for i in lint_briefs([x])))
 def test_publication_guard(self):
  x={"working_title":"x","beats":["specific"],"external_publish_allowed":True}
  self.assertTrue(any(i["code"]=="UNSAFE_PUBLICATION_STATE" for i in lint_briefs([x])))
if __name__=="__main__": unittest.main()
