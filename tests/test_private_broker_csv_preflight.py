import csv
import tempfile
import unittest
from pathlib import Path
from scripts.private_broker_csv_preflight import FIELDS,private_csv_path,audit_csv,main

def sample(**kw):
    v=dict(execution_id="E1",order_id="O1",ticker="285A.T",side="BUY",
           price="1500",quantity="100",fee="55",
           executed_at="2026-10-13T09:15:00+09:00",decision_snapshot_id="D1")
    v.update(kw)
    return v

class PrivateBrokerCSVPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.directory=self.root/"data"/"private"/"broker_exports"
        self.directory.mkdir(parents=True)
    def tearDown(self):
        self.tmp.cleanup()
    def write(self,rows,filename="test.csv",fields=FIELDS):
        path=self.directory/filename
        with path.open("w",newline="",encoding="utf-8") as handle:
            wr=csv.DictWriter(handle,fieldnames=fields)
            wr.writeheader()
            wr.writerows(rows)
        return path

    def test_valid_csv_is_structurally_only_not_source_authenticated(self):
        p=self.write([sample()])
        report=audit_csv(private_csv_path(self.root,"data/private/broker_exports/test.csv"))
        self.assertEqual(report["eligible_to_compare"],1)
        self.assertEqual(report["rejected_records"],0)
        self.assertFalse(report["source_authenticated"])
        self.assertFalse(report["automated_reconciliation_allowed"])
        self.assertFalse(report["ev_training_allowed"])
        self.assertFalse(report["real_submit_allowed"])
        self.assertEqual(len(report["source_sha256"]),64)

    def test_broker_shaped_file_without_ai_decision_id_is_not_rejected(self):
        fields=tuple(x for x in FIELDS if x!="decision_snapshot_id")
        report=audit_csv(self.write([{k:v for k,v in sample().items() if k in fields}],fields=fields))
        self.assertEqual(report["rejected_records"],0)
        self.assertEqual(report["decision_unlinked_records"],1)
        self.assertFalse(report["automated_reconciliation_allowed"])
        self.assertFalse(report["ev_training_allowed"])

    def test_trade_day_missing_fees_are_pending_not_zero(self):
        report=audit_csv(self.write([sample(fee="")]))
        self.assertEqual(report["rejected_records"],0)
        self.assertEqual(report["fee_pending_records"],1)
        self.assertEqual(report["eligible_to_compare"],0)
        self.assertFalse(report["source_authenticated"])

    def test_real_zero_fee_is_explicitly_distinct_from_pending(self):
        report=audit_csv(self.write([sample(fee="0")]))
        self.assertEqual(report["fee_pending_records"],0)
        self.assertEqual(report["eligible_to_compare"],1)

    def test_duplicate_execution_id_rejected(self):
        report=audit_csv(self.write([sample(),sample(order_id="O2")]))
        self.assertEqual(report["reasons"]["DUPLICATE_EXECUTION_ID"],1)

    def test_naive_timestamp_rejected_not_assumed_jst(self):
        report=audit_csv(self.write([sample(executed_at="2026-10-13 09:15:00")]))
        self.assertEqual(report["reasons"]["TIMESTAMP_INVALID"],1)

    def test_fee_and_price_nonfinite_rejected(self):
        for field,value in (("price","nan"),("quantity","Infinity"),("fee","-5")):
            report=audit_csv(self.write([sample(**{field:value})]))
            self.assertEqual(report["reasons"]["PRICE_QTY_FEE_INVALID"],1)

    def test_columns_must_be_exact(self):
        path=self.write([sample()],fields=FIELDS)
        with path.open("w",encoding="utf-8") as f:
            f.write("execution_id,price\nE1,100\n")
        with self.assertRaisesRegex(ValueError,"CSV_COLUMN_CONTRACT_MISMATCH"):
            audit_csv(path)

    def test_outside_and_traversal_forbidden(self):
        self.write([sample()])
        for path in ("/etc/passwd","../broker_exports/test.csv",
                     "data/private/../private/broker_exports/test.csv",
                     "paper_trade_history.json"):
            with self.assertRaises(ValueError):
                private_csv_path(self.root,path)

    def test_symlink_rejected(self):
        p=self.write([sample()])
        alias=self.directory/"alias.csv"
        try:
            alias.symlink_to(p)
        except (OSError,NotImplementedError):
            self.skipTest("no symlink permissions")
        with self.assertRaises(ValueError):
            private_csv_path(self.root,"data/private/broker_exports/alias.csv")

    def test_never_emits_private_row_values(self):
        secret="my-private-execution-account"
        report=audit_csv(self.write([sample(execution_id=secret,order_id=secret)]))
        self.assertNotIn(secret,str(report))
        self.assertNotIn("1500",str(report))

if __name__=="__main__":
    unittest.main()
