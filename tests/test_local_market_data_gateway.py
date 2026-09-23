import copy
import unittest
from datetime import datetime,timedelta,timezone
from scripts.local_market_data_gateway import normalize_snapshot,normalize_sources

JST=timezone(timedelta(hours=9))
NOW=datetime(2026,9,24,9,20,0,tzinfo=JST)

def rec(**kw):
 r={"symbol":"285A","observed_at":NOW.isoformat(),"generated_at":NOW.isoformat(),
    "source":"MS2_RSS","current":1000.0,"open":990.0,"previous_close":980.0,
    "vwap":995.0,"or5_high":1001.0,"or5_mid":995.0,"or5_low":989.0,
    "or5_complete":True,"or15_complete":False,"flow_state":None}
 r.update(kw);return r

class GatewayTests(unittest.TestCase):
 def test_deterministic(self):
  self.assertEqual(normalize_snapshot(rec(),NOW),normalize_snapshot(copy.deepcopy(rec()),NOW))
 def test_stale_waits(self):
  old=(NOW-timedelta(seconds=61)).isoformat()
  x=normalize_snapshot(rec(observed_at=old,generated_at=old),NOW)
  self.assertEqual(x["status"],"WAIT_DATA");self.assertEqual(x["fail_reason"],"STALE_DATA")
 def test_future_fails_closed(self):
  future=(NOW+timedelta(seconds=1)).isoformat()
  with self.assertRaises(ValueError):normalize_snapshot(rec(observed_at=future),NOW)
 def test_or5_incomplete_blocks_breakout(self):
  x=normalize_snapshot(rec(or5_complete=False),NOW)
  self.assertEqual(x["status"],"WAIT_DATA");self.assertFalse(x["or5_breakout_eligible"])
 def test_or15_incomplete_never_confirms(self):
  x=normalize_snapshot(rec(or15_complete=False),NOW)
  self.assertFalse(x["or15_breakout_eligible"])
 def test_missing_flow_is_not_inferred(self):
  x=normalize_snapshot(rec(flow_state=None),NOW)
  self.assertFalse(x["flow_observed"]);self.assertIsNone(x["flow_state"])
 def test_source_disagreement_is_preserved(self):
  x=normalize_sources([rec(source="MS2_RSS",current=1000.0),rec(source="TRADINGVIEW_LOCAL",current=1001.0)],NOW)
  self.assertEqual([s["current"] for s in x["snapshots"]],[1000.0,1001.0])
  self.assertTrue(x["source_disagreement_preserved"])
 def test_private_and_order_fields_rejected(self):
  for key in ("account_id","order_id","broker_token","holdings"):
   r=rec();r[key]="secret"
   with self.assertRaises(ValueError):normalize_snapshot(r,NOW)
 def test_unknown_field_rejected(self):
  r=rec();r["mystery"]=1
  with self.assertRaises(ValueError):normalize_snapshot(r,NOW)
 def test_no_submit_surface(self):
  x=normalize_snapshot(rec(),NOW)
  self.assertFalse(x["real_submit_allowed"]);self.assertNotIn("submit",x)

if __name__=="__main__":unittest.main()
