import csv,tempfile,unittest
from pathlib import Path
from scripts.validate_oos import split_rows,validate,net_pnl
class OOSTests(unittest.TestCase):
 def test_chronological_not_input_order(self):
  train,oos=split_rows([{"entry_ts":"3"},{"entry_ts":"1"},{"entry_ts":"2"},{"entry_ts":"4"}],.5)
  self.assertEqual([x["entry_ts"] for x in train],["1","2"]);self.assertEqual([x["entry_ts"] for x in oos],["3","4"])
 def test_net_pnl_does_not_subtract_cost_twice(self):
  self.assertEqual(net_pnl({"pnl_pct":"0.9","cost_pct":"0.1"}),0.9)
 def test_oos_is_later_holdout(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"t.csv"
   with p.open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=["strategy_key","entry_ts","pnl_pct","cost_pct"]);w.writeheader()
    for i in range(10):w.writerow({"strategy_key":"A","entry_ts":f"2026-01-{i+1:02d}","pnl_pct":1 if i<7 else -1,"cost_pct":.1})
   x=validate(p,.7);self.assertEqual(x["train"]["n"],7);self.assertEqual(x["oos"]["n"],3);self.assertEqual(x["oos"]["groups"]["A"]["avg_pl_pct"],-1.0)
if __name__=="__main__":unittest.main()
