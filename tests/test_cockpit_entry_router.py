import unittest
from scripts.cockpit_entry_router import route
class TestCockpitEntryRouter(unittest.TestCase):
 def test_routes_all_user_functions_behind_cockpit(self):
  for kind in ("TRADE_RESEARCH","MARKET_DAILY","DEVELOPER_GROWTH","ENTERTAINMENT","COMMUNITY_LEAD","DIARY"):
   self.assertEqual(route({"kind":kind})["entry"],"AI_COCKPIT")
 def test_no_real_submit(self):
  with self.assertRaises(ValueError): route({"kind":"TRADE_RESEARCH","real_submit":True})
 def test_no_external_publish_without_owner(self):
  with self.assertRaises(ValueError): route({"kind":"ENTERTAINMENT","external_publish":True})
if __name__=="__main__": unittest.main()
