import unittest
from scripts.strategy_evolution import evaluate
class T(unittest.TestCase):
 def base(self,state="CANDIDATE"):return {"name":"OR15","state":state,"sample_size":100,"expectancy":0.2,"max_drawdown_pct":8,"evidence_integrity":True}
 def test_candidate_to_replay(self):self.assertEqual(evaluate(self.base())["next_state"],"REPLAY")
 def test_replay_to_shadow_requires_oos(self):
  x=self.base("REPLAY");self.assertEqual(evaluate(x)["action"],"HOLD");x["out_of_sample_pass"]=True;self.assertEqual(evaluate(x)["next_state"],"SHADOW")
 def test_shadow_to_candidate(self):
  x=self.base("SHADOW");x["shadow_pass"]=True;self.assertEqual(evaluate(x)["next_state"],"PROMOTION_CANDIDATE")
 def test_negative_expectancy_demotes(self):
  x=self.base("SHADOW");x["expectancy"]=-.1;self.assertEqual(evaluate(x)["next_state"],"DEMOTED")
 def test_never_grants_real_submit(self):self.assertFalse(evaluate(self.base())["real_submit_allowed"])
if __name__=="__main__":unittest.main()
