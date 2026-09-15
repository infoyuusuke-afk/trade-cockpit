import importlib.util
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
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

class MomentumTests(unittest.TestCase):
    """旧scripts/upcoming_earnings.pyから移植したモメンタムレーン・的中率検証の統合分。"""
    def test_load_save_log_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(ec, 'LOG_PATH', Path(d)/'log.json'):
                self.assertEqual(ec.load_log(), [])
                ec.save_log([{'code': '285A'}])
                self.assertEqual(ec.load_log(), [{'code': '285A'}])

    def test_resolve_pending_marks_hit(self):
        entry = {'code': '285A', 'target_date': '2026-09-01',
                  'momentum_direction': '上昇レーン（モメンタムのみ・決算内容は未考慮）', 'status': 'pending'}
        df = pd.DataFrame({'Close': [100.0, 105.0]}, index=pd.to_datetime(['2026-09-01', '2026-09-02']))
        with patch.object(ec.yf, 'download', return_value=df):
            resolved = ec.resolve_pending([entry], date(2026, 9, 15))
        self.assertEqual(resolved[0]['status'], 'resolved')
        self.assertTrue(resolved[0]['hit'])

    def test_resolve_pending_leaves_future_target_untouched(self):
        entry = {'code': '285A', 'target_date': '2099-01-01', 'status': 'pending'}
        resolved = ec.resolve_pending([entry], date(2026, 9, 15))
        self.assertEqual(resolved[0]['status'], 'pending')

    def test_apply_momentum_targets_nearest_future_date_only(self):
        events = [{'code': '285A', 'name': 'K', 'date': '2026-09-16'},
                  {'code': '7203', 'name': 'T', 'date': '2026-09-20'}]
        with tempfile.TemporaryDirectory() as d, \
             patch.object(ec, 'LOG_PATH', Path(d)/'log.json'), \
             patch.object(ec, 'momentum_lean', return_value={'available': True, 'momentum_direction': '中立', 'return_5d_pct': 0.1}):
            target_date, validation = ec.apply_momentum(events, date(2026, 9, 15))
        self.assertEqual(target_date, '2026-09-16')
        self.assertIn('momentum', events[0])
        self.assertNotIn('momentum', events[1])
        self.assertEqual(validation['min_n_threshold'], ec.MOMENTUM_MIN_N)

if __name__=='__main__':unittest.main()
