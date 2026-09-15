import importlib.util
import unittest
from datetime import date, datetime
from pathlib import Path
import pandas as pd

spec=importlib.util.spec_from_file_location('ec', Path(__file__).parents[1]/'scripts/earnings_calendar.py')
ec=importlib.util.module_from_spec(spec);spec.loader.exec_module(ec)

class CalendarTests(unittest.TestCase):
    def test_schedule_uses_header_and_alphanumeric_code(self):
        frame=pd.DataFrame([['コード','会社名','決算期末','決算発表予定日'],['285A','キオクシア','2026-03-31','2026-09-18']])
        rows,valid=ec.parse_schedule(frame,'https://example.com',date(2026,9,15))
        self.assertTrue(valid);self.assertEqual(rows[0]['date'],'2026-09-18');self.assertEqual(rows[0]['code'],'285A')
    def test_unknown_headers_do_not_guess(self):
        rows,valid=ec.parse_schedule(pd.DataFrame([['285A','name','2026-09-18']]),'u',date(2026,9,15))
        self.assertFalse(valid);self.assertEqual(rows,[])
    def test_generic_revision_is_not_upward(self):
        tags=ec.classify('通期業績予想の修正に関するお知らせ')
        self.assertIn('業績修正・方向要確認',tags);self.assertNotIn('上方修正',tags)
    def test_stock_split_is_not_dividend_increase(self):
        self.assertNotIn('増配',ec.classify('株式分割ならびに配当予想の修正'))
    def test_future_disclosure_is_excluded(self):
        raw='<table><tr><td>15:00</td><td>285A0</td><td>K</td><td><a href="x.pdf">業績予想の上方修正</a></td></tr></table>'
        rows,_=ec.parse_disclosures(raw,'2026-09-15',datetime.fromisoformat('2026-09-15T14:00:00+09:00'))
        self.assertEqual(rows,[])
        rows,_=ec.parse_disclosures(raw.encode('utf-8'),'2026-09-15',datetime.fromisoformat('2026-09-15T16:00:00+09:00'))
        self.assertEqual(rows[0]['code'],'285A');self.assertIn('上方修正',rows[0]['tags'])
    def test_no_disclosure_does_not_invent_probability(self):
        a=ec.analysis({'code':'285A'},[]);self.assertIsNone(a['upward_revision_probability'])

if __name__=='__main__':unittest.main()
