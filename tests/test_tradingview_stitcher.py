import unittest
from scripts.tradingview_stitcher import stitch_segments

def r(ts,c=100):
 return {"symbol":"285A","market_date":ts[:10],"timestamp":ts,
         "open":100,"high":101,"low":99,"close":c,"volume":10}

class StitcherTests(unittest.TestCase):
 def test_identical_overlap_deduplicates(self):
  a=[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:15+09:00")]
  b=[r("2026-09-18T09:00:15+09:00"),r("2026-09-18T09:00:30+09:00")]
  x=stitch_segments([a,b])
  self.assertEqual(len(x["rows"]),3);self.assertEqual(x["audit"]["duplicate_overlap_rows"],1)
 def test_overlap_mismatch_fails(self):
  a=[r("2026-09-18T09:00:00+09:00",100)]
  b=[r("2026-09-18T09:00:00+09:00",101)]
  with self.assertRaises(ValueError):stitch_segments([a,b])
 def test_intraday_gap_is_audited_not_filled(self):
  x=stitch_segments([[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:45+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],1);self.assertFalse(x["audit"]["interpolation_used"])
 def test_overnight_gap_not_flagged(self):
  x=stitch_segments([[r("2026-09-17T15:30:00+09:00"),r("2026-09-18T09:00:00+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],0)
 def test_lunch_recess_is_expected_break(self):
  x=stitch_segments([[r("2026-09-18T11:29:45+09:00"),r("2026-09-18T12:30:00+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],0);self.assertEqual(x["audit"]["expected_session_break_count"],1);self.assertEqual(x["audit"]["expected_session_breaks"][0]["reason"],"LUNCH_RECESS")
 def test_closing_auction_is_expected_break(self):
  x=stitch_segments([[r("2026-09-18T15:24:45+09:00"),r("2026-09-18T15:30:00+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],0);self.assertEqual(x["audit"]["expected_session_break_count"],1);self.assertEqual(x["audit"]["expected_session_breaks"][0]["reason"],"CLOSING_AUCTION")
 def test_observed_1525_bar_is_preserved_before_closing_break(self):
  rows=[r("2026-09-18T15:24:45+09:00"),r("2026-09-18T15:25:00+09:00"),r("2026-09-18T15:30:00+09:00")]
  x=stitch_segments([rows]);self.assertEqual(len(x["rows"]),3);self.assertEqual(x["audit"]["gap_count"],0);self.assertEqual(x["audit"]["expected_session_break_count"],1)
 def test_missing_last_pre_lunch_bar_is_not_hidden(self):
  x=stitch_segments([[r("2026-09-18T11:29:30+09:00"),r("2026-09-18T12:30:00+09:00")]])
  self.assertEqual(x["audit"]["gap_count"],1)

# Issue #169: a delayed first observed print must not be silently treated
# as verified data loss, and must not be silently treated as a complete
# session either. It stays unresolved until an independent source resolves it.
class OpeningAbsenceTests(unittest.TestCase):
 def test_session_open_at_0900_has_no_opening_absence(self):
  x=stitch_segments([[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:15+09:00")]])
  self.assertEqual(x["audit"]["opening_absence_count"],0)
  self.assertEqual(x["audit"]["or_promotion_blocked_dates"],[])
 def test_first_bar_within_15s_tolerance_has_no_opening_absence(self):
  x=stitch_segments([[r("2026-09-18T09:00:15+09:00")]])
  self.assertEqual(x["audit"]["opening_absence_count"],0)
 def test_delayed_first_print_is_unresolved_not_verified(self):
  # Matches the real Issue #169 example: first observed print at 09:08:45.
  x=stitch_segments([[r("2026-09-18T09:08:45+09:00")]])
  self.assertEqual(x["audit"]["opening_absence_count"],1)
  entry=x["audit"]["opening_absences"][0]
  self.assertEqual(entry["market_date"],"2026-09-18")
  self.assertEqual(entry["status"],"UNRESOLVED_NO_BAR_INTERVAL")
  self.assertEqual(x["audit"]["unresolved_opening_dates"],["2026-09-18"])
  self.assertEqual(x["audit"]["or_promotion_blocked_dates"],["2026-09-18"])
  self.assertFalse(x["audit"]["synthesized_bars"])
 def test_delayed_first_print_does_not_promote_session_as_complete(self):
  x=stitch_segments([[r("2026-09-18T09:08:45+09:00"),r("2026-09-18T15:30:00+09:00")]])
  self.assertIn("2026-09-18",x["audit"]["or_promotion_blocked_dates"])
 def test_independent_evidence_can_verify_opening_gap(self):
  primary=[r("2026-09-18T09:08:45+09:00")]
  evidence=[r("2026-09-18T09:03:00+09:00")]
  x=stitch_segments([primary],independent_evidence=evidence)
  entry=x["audit"]["opening_absences"][0]
  self.assertEqual(entry["status"],"VERIFIED_ACQUISITION_GAP")
  # Verified loss still blocks OR promotion: the bars are still missing.
  self.assertEqual(x["audit"]["unresolved_opening_dates"],[])
  self.assertEqual(x["audit"]["or_promotion_blocked_dates"],["2026-09-18"])
 def test_independent_evidence_on_other_date_does_not_verify(self):
  primary=[r("2026-09-18T09:08:45+09:00")]
  evidence=[r("2026-09-17T09:03:00+09:00")]
  x=stitch_segments([primary],independent_evidence=evidence)
  self.assertEqual(x["audit"]["opening_absences"][0]["status"],"UNRESOLVED_NO_BAR_INTERVAL")
 def test_independent_evidence_outside_window_does_not_verify(self):
  primary=[r("2026-09-18T09:08:45+09:00")]
  evidence=[r("2026-09-18T09:08:45+09:00")]  # exactly at first_observed, not strictly inside (open, first)
  x=stitch_segments([primary],independent_evidence=evidence)
  self.assertEqual(x["audit"]["opening_absences"][0]["status"],"UNRESOLVED_NO_BAR_INTERVAL")
 def test_multiple_dates_are_evaluated_independently(self):
  x=stitch_segments([[r("2026-09-17T09:00:00+09:00"),r("2026-09-18T09:08:45+09:00")]])
  self.assertEqual(x["audit"]["opening_absence_count"],1)
  self.assertEqual(x["audit"]["opening_absences"][0]["market_date"],"2026-09-18")

class InteriorGapClassificationTests(unittest.TestCase):
 def test_unresolved_gap_has_explicit_status_by_default(self):
  x=stitch_segments([[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:45+09:00")]])
  self.assertEqual(x["audit"]["intraday_gaps"][0]["status"],"UNRESOLVED_NO_BAR_INTERVAL")
 def test_interior_gap_verified_by_independent_evidence(self):
  primary=[r("2026-09-18T09:00:00+09:00"),r("2026-09-18T09:00:45+09:00")]
  evidence=[r("2026-09-18T09:00:15+09:00")]
  x=stitch_segments([primary],independent_evidence=evidence)
  self.assertEqual(x["audit"]["intraday_gaps"][0]["status"],"VERIFIED_ACQUISITION_GAP")
 def test_expected_break_is_not_reclassified_by_evidence(self):
  # No legitimate execution occurs during the lunch recess; even if a
  # candidate "evidence" bar were supplied inside it, the interval is a
  # known non-execution window and must stay EXPECTED_SESSION_BREAK.
  primary=[r("2026-09-18T11:29:45+09:00"),r("2026-09-18T12:30:00+09:00")]
  evidence=[r("2026-09-18T12:00:00+09:00")]
  x=stitch_segments([primary],independent_evidence=evidence)
  self.assertEqual(x["audit"]["gap_count"],0)
  self.assertEqual(x["audit"]["expected_session_breaks"][0]["status"],"EXPECTED_SESSION_BREAK")
if __name__=="__main__":unittest.main()
