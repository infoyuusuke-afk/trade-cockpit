import json,unittest
from pathlib import Path
from scripts.strategy_research_engine import generate_variants,rank_evidence,next_experiments
class T(unittest.TestCase):
 def setUp(self):self.r=json.loads(Path("data/strategy_registry.v1.json").read_text())
 def test_generates_all_single_candidates(self):self.assertGreaterEqual(len(generate_variants(self.r)),len(self.r["strategies"]))
 def test_pairs_never_cross_horizon(self):
  by={s["id"]:s["horizon"] for s in self.r["strategies"]}
  for v in generate_variants(self.r):
   self.assertEqual(len({by[m] for m in v["members"]}),1)
 def test_bad_evidence_not_ranked(self):
  rows=[{"strategy_id":"a","evidence_integrity":False,"lookahead_safe":True,"sample_size":100,"expectancy":9,"max_drawdown_pct":1}]
  self.assertEqual(rank_evidence(rows),[])
 def test_ranking_never_grants_submit(self):
  rows=[{"strategy_id":"a","evidence_integrity":True,"lookahead_safe":True,"sample_size":100,"expectancy":1,"max_drawdown_pct":2}]
  self.assertFalse(rank_evidence(rows)[0]["real_submit_allowed"])
 def test_unseen_becomes_backtest(self):self.assertTrue(all(x["action"]=="BACKTEST" for x in next_experiments(self.r,[])))
if __name__=="__main__":unittest.main()
