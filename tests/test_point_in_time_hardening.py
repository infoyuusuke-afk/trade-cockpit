import unittest
from datetime import datetime, tzinfo

from scripts import event_bus as eb
from scripts import event_intake_guard as g
from scripts.commentary_scheduler import schedule


class NullOffsetTZ(tzinfo):
    def utcoffset(self, dt):
        return None


def event(sec=0):
    return eb.build_event(timestamp=f"2026-09-21T09:10:{sec:02d}+09:00",domain="SYSTEM",event_type="X",source="test",payload={"summary":"x"})


def candidate(ts="2026-09-21T09:10:20+09:00"):
    return {"event_id":"e1","priority":1,"text":"x","speech_text":"x","timestamp":ts,"real_submit_allowed":False}


class PointInTimeHardeningTests(unittest.TestCase):
    def test_null_offset_now_rejected(self):
        with self.assertRaises(ValueError):
            g.intake([event(10)],now=datetime(2026,9,21,9,10,20,tzinfo=NullOffsetTZ()))

    def test_malformed_event_does_not_reach_sort(self):
        result=g.intake([None,{"timestamp":object()}],now=datetime.fromisoformat("2026-09-21T09:10:20+09:00"))
        self.assertEqual(result["status"],"BLOCK")
        self.assertEqual([x["reason"] for x in result["rejected"]],["INVALID_EVENT","INVALID_EVENT"])

    def test_scheduler_rejects_naive_candidate(self):
        with self.assertRaises(ValueError):
            schedule([candidate("2026-09-21T09:10:20")])

    def test_scheduler_rejects_malformed_candidate_before_sort(self):
        with self.assertRaises(ValueError):
            schedule([{"priority":object()}])

    def test_scheduler_rejects_backward_candidate(self):
        with self.assertRaises(ValueError):
            schedule([candidate("2026-09-21T09:10:19+09:00")],last_spoken_at="2026-09-21T09:10:20+09:00")

    def test_scheduler_rejects_naive_last_spoken(self):
        with self.assertRaises(ValueError):
            schedule([candidate()],last_spoken_at="2026-09-21T09:10:00")
