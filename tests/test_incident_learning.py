import unittest
from scripts.incident_learning import learn
class TestIncidentLearning(unittest.TestCase):
 def test_repeated_incident_becomes_candidate(self):
  xs=[{"code":"STALE_DATA","sanitized":True,"recovered":True,"terminal_state":"RECOVERED"}]*2
  self.assertTrue(learn(xs)[0]["engineering_candidate"])
 def test_failed_recovery_becomes_candidate(self):
  xs=[{"code":"X","sanitized":True,"recovered":False,"terminal_state":"SAFE"}]
  self.assertTrue(learn(xs)[0]["engineering_candidate"])
 def test_unsanitized_excluded(self):
  self.assertEqual(learn([{"code":"X","sanitized":False}]),[])
if __name__=="__main__": unittest.main()
