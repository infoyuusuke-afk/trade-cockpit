import unittest
from scripts.regime_clustering import zscore_rows,nearest_neighbors,assign_fixed_k

class RegimeClusteringTests(unittest.TestCase):
 def rows(self):
  base=lambda i,p,t,o,r5,r15,vw,r: {"id":i,"price":p,"turnover":t,
   "opening_volume_share":o,"or5_width_pct":r5,"or15_width_pct":r15,
   "vwap_reversion_rate":vw,"intraday_range_pct":r}
  return [base("A",10000,50e9,.30,1.2,2.0,.5,5),
          base("B",10500,52e9,.31,1.1,2.1,.52,5.2),
          base("C",1000,5e9,.10,.3,.6,.8,1.2)]

 def test_neighbor_finds_similar_profile(self):
  x=nearest_neighbors(self.rows(),"A",1)
  self.assertEqual(x[0]["id"],"B")

 def test_constant_feature_does_not_divide_by_zero(self):
  rows=self.rows()
  for r in rows: r["vwap_reversion_rate"]=.5
  self.assertEqual(len(zscore_rows(rows)),3)

 def test_assignment_is_research_only(self):
  x=assign_fixed_k(self.rows(),["A","C"])
  self.assertTrue(all(r["research_only"] for r in x))

if __name__=="__main__": unittest.main()
