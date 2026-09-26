import unittest
from datetime import datetime, timezone, timedelta
from scripts.world_market import market_session_state, narration_availability
JST=timezone(timedelta(hours=9))
class MarketSessionStateTest(unittest.TestCase):
 def test_us_cash_previous_session_known(self):
  now=datetime(2026,9,24,15,0,tzinfo=JST); self.assertEqual(market_session_state("us_close",now),"CLOSED_KNOWN"); self.assertEqual(narration_availability({"verified":False,"session_state":"CLOSED_KNOWN"}),"EXPECTED_INACTIVE")
 def test_tse_lunch_break(self): self.assertEqual(market_session_state("japan",datetime(2026,9,24,12,0,tzinfo=JST)),"BREAK")
 def test_missing_open_feed_invalid(self): self.assertEqual(narration_availability({"verified":False,"session_state":"OPEN"}),"DATA_INVALID")
if __name__=="__main__": unittest.main()
