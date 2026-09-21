import unittest
from scripts.walk_forward import windows
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
 def test_bad_window_rejected(self):
  with self.assertRaises(ValueError):windows([],0,10)
if __name__=="__main__":unittest.main()
