import tempfile
import unittest
from pathlib import Path
from scripts.private_broker_csv_picker import safe_report
from scripts.private_broker_jp_header_probe import inspect_header

class PrivateBrokerFilePickerContractTests(unittest.TestCase):
    def test_output_is_allowlisted_and_never_discloses_unknown_fields(self):
        report={"status":"BLOCKED","format_family_candidate":"UNKNOWN_BROKER_CSV_TYPE",
                "encoding_candidate":"cp932","columns_count":3,
                "source_sha256":"private-digest","user_full_path":"C:/PRIVATE/ACCOUNT.csv",
                "unknown_header":"ACCOUNT_NUMBER_0001","row":"SECRET_TRADE_1500"}
        text=safe_report(report)
        for private in ("private-digest","C:/PRIVATE","ACCOUNT_NUMBER_0001","SECRET_TRADE_1500"):
            self.assertNotIn(private,text)
        self.assertIn("BLOCKED",text)
        self.assertIn("証明ではありません",text)

    def test_malicious_status_and_columns_are_not_echoed(self):
        report={"status":"secret-account-XYZ","format_family_candidate":"private-family",
                "columns_count":"my-password","recognized_column_count":-5}
        safe=safe_report(report)
        self.assertNotIn("secret-account-XYZ",safe)
        self.assertNotIn("private-family",safe)
        self.assertNotIn("my-password",safe)
        self.assertNotIn("-5",safe)

    def test_candidate_keeps_real_orders_disabled(self):
        header="約定日,受渡日,銘柄コード,売買区分,数量［株］,単価［円］\nSECRET,private\n"
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"local.csv"
            path.write_bytes(header.encode("cp932"))
            report=inspect_header(path)
            message=safe_report(report)
            self.assertNotIn("SECRET",message)
            self.assertNotIn("private",message)
            self.assertFalse(report["source_authenticated"])
            self.assertFalse(report["reconciliation_allowed"])
            self.assertFalse(report["ev_training_allowed"])
            self.assertFalse(report["real_submit_allowed"])

    def test_cmd_does_not_use_network_or_access_orders(self):
        text=(Path(__file__).resolve().parents[1]/"downloads/READ_ONLY_BROKER_CSV_CHECK.cmd").read_text(encoding="utf-8")
        self.assertIn("private_broker_csv_picker.py",text)
        for dangerous in ("curl ", "Invoke-WebRequest", "git push", "submit_order", "start /B"):
            self.assertNotIn(dangerous,text)

    def test_cmd_probes_python_and_tk_before_any_gui(self):
        text=(Path(__file__).resolve().parents[1]/"downloads/READ_ONLY_BROKER_CSV_CHECK.cmd").read_text(encoding="utf-8")
        self.assertEqual(text.count('import sys, tkinter; assert sys.version_info >= (3, 9)'),2)
        self.assertLess(text.index('py -3 -c'),text.index('py -3 "scripts'))
        self.assertLess(text.index('python -c'),text.index('python "scripts'))
        self.assertNotIn("exit /b %errorlevel%",text)
        self.assertIn("if errorlevel 1 exit /b 2",text)

if __name__=="__main__":
    unittest.main()
