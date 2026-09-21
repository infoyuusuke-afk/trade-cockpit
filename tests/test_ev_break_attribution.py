import unittest
from scripts.ev_break_attribution import make_break_event,attribute_trade_breaks,summarize_break_reasons

class EVBreakAttributionTests(unittest.TestCase):
 def test_preexisting_event_is_not_post_trade_excuse(self):
  t={"trade_id":"T1","decision_ts":"2026-09-18T10:00:00+09:00","net_pnl":-1}
  e=[{"reason":"MARKET_REGIME_DOWNSHIFT","observed_at":"2026-09-18T09:59:00+09:00","magnitude":-1}]
  x=attribute_trade_breaks(t,e)
  self.assertEqual(x["break_reasons"],["UNKNOWN"])

 def test_post_decision_multiple_reasons_are_preserved(self):
  t={"trade_id":"T1","decision_ts":"2026-09-18T10:00:00+09:00","net_pnl":-2}
  e=[
   {"reason":"KOREA_SEMICON_CONTAGION","observed_at":"2026-09-18T10:01:00+09:00"},
   {"reason":"TIME_REGIME_SHIFT","observed_at":"2026-09-18T10:02:00+09:00"}]
  x=attribute_trade_breaks(t,e)
  self.assertEqual(len(x["break_reasons"]),2)
  self.assertFalse(x["causal_claim"])

 def test_reason_needs_30_for_initial_evidence(self):
  rows=[{"net_pnl":-1,"break_reasons":["TIME_REGIME_SHIFT"]} for _ in range(30)]
  x=summarize_break_reasons(rows)
  self.assertEqual(x[0]["evidence_status"],"INITIAL_EVIDENCE")

if __name__=="__main__": unittest.main()
