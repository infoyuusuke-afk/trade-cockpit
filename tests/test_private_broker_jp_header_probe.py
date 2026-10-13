import tempfile
import unittest
from pathlib import Path
from scripts.private_broker_jp_header_probe import inspect_header,main

HEADERS=["約定日","受渡日","銘柄コード","銘柄名","売買区分","数量［株］","単価［円］","手数料［円］","税金等［円］","諸費用［円］"]

class JapaneseBrokerHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.path=self.root/"sample.csv"
    def tearDown(self):
        self.tmp.cleanup()
    def make(self,headers=HEADERS,encoding="cp932",row="PRIVATE_ACCOUNT_123,1500"):
        self.path.write_bytes((",".join(headers)+"\n"+row+"\n").encode(encoding))
        return self.path
    def test_cp932_japanese_header_candidate_not_authentication(self):
        r=inspect_header(self.make())
        self.assertEqual(r["status"],"JP_HEADER_CANDIDATE_ONLY")
        self.assertEqual(r["encoding_candidate"],"cp932")
        self.assertFalse(r["source_authenticated"])
        self.assertFalse(r["reconciliation_allowed"])
        self.assertFalse(r["ev_training_allowed"])
        self.assertFalse(r["real_submit_allowed"])
    def test_utf8_header_candidate(self):
        self.assertEqual(inspect_header(self.make(encoding="utf-8-sig"))["encoding_candidate"],"utf-8-sig")
    def test_missing_critical_column_blocks(self):
        r=inspect_header(self.make(headers=HEADERS[:-1][:2]+HEADERS[3:]))
        self.assertEqual(r["status"],"BLOCKED")
        self.assertIn("銘柄コード",r["missing_known_fields"])
    def test_duplicate_columns_blocked(self):
        r=inspect_header(self.make(headers=HEADERS+["約定日"]))
        self.assertEqual(r["status"],"BLOCKED")
        self.assertEqual(r["duplicate_header_count"],1)
    def test_private_row_never_printed(self):
        secret="PRIVATE_ACCOUNT_123"
        report=inspect_header(self.make(row=secret))
        self.assertNotIn(secret,str(report))
        self.assertNotIn("1500",str(report))
    def test_unknown_header_does_not_get_raw_disclosed(self):
        r=inspect_header(self.make(headers=["MY_SECRET_ACCOUNT","123"]))
        self.assertEqual(r["status"],"BLOCKED")
        self.assertNotIn("MY_SECRET_ACCOUNT",str(r))
        self.assertNotIn("123",str(r))
if __name__=="__main__":
    unittest.main()
