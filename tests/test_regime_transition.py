import unittest
from scripts.regime_transition import detect_regime_transition

F=["x","y"]
class RegimeTransitionTests(unittest.TestCase):
 def base(self):
  return [{"x":0,"y":0,"empirical_cluster":"A"} for _ in range(5)]

 def test_small_change_stable(self):
  x=detect_regime_transition(self.base(),{"x":.2,"y":.1,"empirical_cluster":"A"},F)
  self.assertEqual(x["status"],"STABLE")

 def test_single_large_cluster_change_is_watch(self):
  x=detect_regime_transition(self.base(),{"x":3,"y":0,"empirical_cluster":"B"},F)
  self.assertEqual(x["status"],"WATCH")

 def test_persistent_large_cluster_change_is_candidate(self):
  h=self.base()
  h[-1]["transition_watch"]=True
  x=detect_regime_transition(h,{"x":3,"y":0,"empirical_cluster":"B"},F)
  self.assertEqual(x["status"],"TRANSITION_CANDIDATE")
  self.assertTrue(x["persistent"])

 def test_insufficient_history_fails_closed(self):
  x=detect_regime_transition(self.base()[:2],{"x":3,"y":0,"empirical_cluster":"B"},F)
  self.assertEqual(x["status"],"INSUFFICIENT_HISTORY")
  self.assertFalse(x["auto_execute"])

if __name__=="__main__": unittest.main()
