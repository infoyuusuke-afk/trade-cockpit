import unittest
from scripts.controller_market_input import control_with_market_inputs
class TestControllerMarketInput(unittest.TestCase):
 def health(self): return {k:"OK" for k in ("strategy","execution","reporting","learning")}
 def test_healthy_source_reaches_daily_loop(self):
  c=[{"source":"MS2","health":"OK","verified":True,"priority":1,"fingerprint":"x"}]
  x=control_with_market_inputs(c,self.health(),True)
  self.assertEqual(x["mode"],"DAILY_LOOP");self.assertEqual(x["market_input"]["selected"],"MS2")
 def test_secondary_source_keeps_loop_alive(self):
  c=[{"source":"MS2","health":"DEGRADED","verified":True,"priority":1},{"source":"TV","health":"OK","verified":True,"priority":2,"fingerprint":"x"}]
  self.assertEqual(control_with_market_inputs(c,self.health(),True)["mode"],"DAILY_LOOP")
 def test_no_source_routes_recovery(self):
  self.assertEqual(control_with_market_inputs([],self.health(),True)["mode"],"RECOVERY")
 def test_disagreement_routes_safe_recovery(self):
  c=[{"source":"A","health":"OK","verified":True,"priority":1,"fingerprint":"x"},{"source":"B","health":"OK","verified":True,"priority":1,"fingerprint":"y"}]
  x=control_with_market_inputs(c,self.health(),True)
  self.assertEqual(x["mode"],"RECOVERY");self.assertEqual(x["market_input"]["status"],"SAFE")
if __name__=="__main__": unittest.main()
