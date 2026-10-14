import json
import tempfile
import unittest
from pathlib import Path
from scripts.ms2_legacy_csv_audit import HEADERS,audit_bytes,audit_path

class LegacyTests(unittest.TestCase):
    def audit(self,kind,body):
        return audit_bytes((HEADERS[kind]+'\n'+body).encode('utf-8-sig'),kind,'2026-10-14')
    def test_ticks_restarts_and_ambiguous_duplicates(self):
        r=self.audit('ticks','2026-10-14 09:00:00,09:00:00,100,10,4\n2026-10-14 09:00:02,09:00:00,100,10,1\n')
        self.assertEqual(r['reasons']['POLL_RESET_OR_REGRESSION'],1)
        self.assertEqual(r['reasons']['REPEATED_TICK_KEY'],1)
    def test_diag_gap_empty_and_bad_counts(self):
        r=self.audit('diag','2026-10-14 09:00:00,300,0,300,True\n2026-10-14 09:00:02,0,0,0,False\n2026-10-14 09:00:04,2,3,2,False\n')
        self.assertEqual(r['reasons']['GAP_SUSPECTED'],1)
        self.assertEqual(r['reasons']['EMPTY_WINDOW_UNKNOWN'],1)
        self.assertEqual(r['reasons']['DIAG_COUNT_INVALID'],1)
    def test_quote_zero_is_ambiguous(self):
        r=self.audit('quotes','2026-10-14,09:00,0,50,1,101,100,約定あり\n')
        self.assertIn('ZERO_AND_MISSING_QUANTITY_NOT_DISTINGUISHABLE',r['reasons'])
    def test_corrupt_future_wrong_date_and_nonfinite(self):
        r=self.audit('ticks','2026-10-15 09:00:00,25:00:00,nan,10,1\n2026-10-14 09:00:00,09:00:00,inf,-1,2\nbroken\n')
        self.assertIn('DATE_MISMATCH',r['reasons'])
        self.assertIn('CLOCK_REGRESSION',r['reasons'])
        self.assertIn('PRICE_VOLUME_INVALID',r['reasons'])
        self.assertIn('ROW_SHAPE_INVALID',r['reasons'])
    def test_duplicate_truncated_and_interval(self):
        row='2026-10-14 09:00:00,09:00:00,100,10,1\n'
        r=self.audit('ticks',row+row+'2026-10-14 09:01:00,09:01:00,100,10,2')
        self.assertEqual(r['duplicate_rows'],1)
        self.assertIn('INCOMPLETE_FINAL_LINE',r['reasons'])
        self.assertIn('RECORDING_INTERVAL_GAP_SUSPECTED',r['reasons'])
    def test_fail_closed_naive_clock_no_private_output(self):
        r=self.audit('ticks','2026-10-14 09:00:00,09:00:00,12345,9876,1\n')
        self.assertEqual(r['freshness'],'UNKNOWN')
        self.assertEqual(r['timezone'],'UNKNOWN')
        self.assertEqual(r['eligible_observed_n'],0)
        for key in ('real_submit_allowed','promotion_eligible','statistical_edge_confirmed','fill_evidence_eligible'):
            self.assertIs(r[key],False)
        self.assertNotIn('12345',json.dumps(r));self.assertNotIn('9876',json.dumps(r))
    def test_file_unchanged_and_missing_refused(self):
        with self.assertRaises(ValueError):audit_path('//server/share/private.csv','ticks','2026-10-14')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d,'synthetic.csv');raw=(HEADERS['ticks']+'\n').encode();p.write_bytes(raw)
            audit_path(p,'ticks','2026-10-14');self.assertEqual(raw,p.read_bytes())
            with self.assertRaises(ValueError):audit_path(Path(d,'missing.csv'),'ticks','2026-10-14')
    def test_header_timezone_and_syntax_rejection(self):
        self.assertIn('HEADER_MISMATCH',audit_bytes(b'a,b\n','ticks','2026-10-14')['reasons'])
        r=self.audit('ticks','2026-10-14T09:00:00+09:00,09:00:00,100,10,1\n')
        self.assertIn('FIELD_OR_TIME_INVALID',r['reasons'])
        self.assertIn('CSV_DECODE_OR_SYNTAX_INVALID',audit_bytes(b'\xff','ticks','2026-10-14')['reasons'])

if __name__=='__main__':unittest.main()
