import unittest
from scripts.transition_strategy_ev import transition_strategy_ev,compare_stable_to_transition

class TransitionStrategyEVTests(unittest.TestCase):
 def test_states_are_not_pooled(self):
  rows=[
   {"setup":"OR15","time_bucket":"10:00","transition_status":"STABLE","net_pnl":1},
   {"setup":"OR15","time_bucket":"10:00","transition_status":"TRANSITION_CANDIDATE","net_pnl":-2}]
  x=transition_strategy_ev(rows)
  self.assertEqual(len(x),2)

 def test_small_n_is_reference_only(self):
  rows=[{"setup":"VWAP","time_bucket":"09:30","transition_status":"WATCH","net_pnl":1}]
  self.assertEqual(transition_strategy_ev(rows)[0]["evidence_status"],"REFERENCE_ONLY")

 def test_delta_does_not_select_winner(self):
  rows=[]
  for _ in range(30):
   rows.append({"setup":"OR5","time_bucket":"09:15","transition_status":"STABLE","net_pnl":1})
   rows.append({"setup":"OR5","time_bucket":"09:15","transition_status":"TRANSITION_CANDIDATE","net_pnl":2})
  x=compare_stable_to_transition(rows)[0]
  self.assertEqual(x["avg_net_pnl_delta"],1)
  self.assertEqual(x["comparison_status"],"INITIAL_EVIDENCE")
  self.assertFalse(x["winner_selected"])
  self.assertFalse(x["causal_claim"])

if __name__=="__main__": unittest.main()
