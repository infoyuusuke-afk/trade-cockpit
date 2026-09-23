import unittest
from scripts.autonomy_health import health
class TestHealth(unittest.TestCase):
 def base(self): return {k:"OK" for k in ("data","strategy","execution","reporting","learning")}
 def test_all_ok(self): self.assertEqual(health(self.base())["overall"],"HEALTHY")
 def test_degraded(self):
  x=self.base();x["data"]="DEGRADED";self.assertEqual(health(x)["overall"],"DEGRADED")
 def test_blocked_fails_safe(self):
  x=self.base();x["execution"]="BLOCKED";self.assertEqual(health(x)["overall"],"SAFE")
if __name__=="__main__": unittest.main()
