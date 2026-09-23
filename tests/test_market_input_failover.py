import unittest
from scripts.market_input_failover import choose
class TestFailover(unittest.TestCase):
 def test_primary_selected(self):
  x=choose([{"source":"MS2","health":"OK","verified":True,"priority":1,"fingerprint":"a"},{"source":"TV","health":"OK","verified":True,"priority":2,"fingerprint":"a"}])
  self.assertEqual(x["selected"],"MS2")
 def test_secondary_when_primary_bad(self):
  x=choose([{"source":"MS2","health":"DEGRADED","verified":True,"priority":1},{"source":"TV","health":"OK","verified":True,"priority":2}])
  self.assertEqual(x["selected"],"TV")
 def test_no_source_waits(self):
  self.assertEqual(choose([])["status"],"WAIT_DATA")
 def test_equal_priority_disagreement_safe(self):
  x=choose([{"source":"A","health":"OK","verified":True,"priority":1,"fingerprint":"x"},{"source":"B","health":"OK","verified":True,"priority":1,"fingerprint":"y"}])
  self.assertEqual(x["status"],"SAFE")
if __name__=="__main__": unittest.main()
