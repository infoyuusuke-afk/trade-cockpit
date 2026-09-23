import unittest
from scripts.owner_exception_inbox import build_inbox
class TestOwnerInbox(unittest.TestCase):
 def test_routine_info_hidden(self):
  self.assertEqual(build_inbox([{"code":"OK","severity":"INFO"}]),[])
 def test_blocking_visible(self):
  self.assertEqual(build_inbox([{"code":"WAIT","severity":"BLOCKING"}])[0]["code"],"WAIT")
 def test_authority_request_visible(self):
  x=build_inbox([{"code":"PUBLISH","severity":"ATTENTION","owner_authority_required":True}])
  self.assertEqual(x[0]["code"],"PUBLISH")
 def test_critical_first(self):
  x=build_inbox([{"code":"B","severity":"BLOCKING"},{"code":"C","severity":"CRITICAL"}])
  self.assertEqual(x[0]["code"],"C")
if __name__=="__main__": unittest.main()
