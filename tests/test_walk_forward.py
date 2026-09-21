import csv,tempfile,unittest
from pathlib import Path
from scripts.walk_forward import windows,validate
class WalkForwardTests(unittest.TestCase):
 def test_expanding_train_non_overlapping_oos(self):
  rows=[{"entry_ts":f"{i:03d}"} for i in range(50)]
  w=windows(rows,30,10)
  self.assertEqual([(len(a),len(b)) for a,b in w],[(30,10),(40,10)])
  self.assertEqual([x["entry_ts"] for x in w[0][1]], [f"{i:03d}" for i in range(30,40)])
  self.assertEqual([x["entry_ts"] for x in w[1][1]], [f"{i:03d}" for i in range(40,50)])
 def test_input_order_does_not_change_time_order(self):
  rows=[{"entry_ts":"3"},{"entry_ts":"1"},{"entry_ts":"4"},{"entry_ts":"2"}]
  w=windows(rows,2,1);self.assertEqual(w[0][1][0]["entry_ts"],"3");self.assertEqual(w[1][1][0]["entry_ts"],"4")
 def test_review_rows_are_excluded_from_walk_forward_evidence(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"t.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["strategy_key","entry_ts","pnl_pct","promotion_eligible"]);w.writeheader()
    for i in range(50):w.writerow({"strategy_key":"A","entry_ts":f"{i:03d}","pnl_pct":1,"promotion_eligible":"true" if i<40 else "false"})
   x=validate(p,30,10);self.assertEqual(len(x["folds"]),1);self.assertEqual(x["folds"][0]["oos_n"],10)
 def test_bad_window_rejected(self):
  with self.assertRaises(ValueError):windows([],0,10)
if __name__=="__main__":unittest.main()
