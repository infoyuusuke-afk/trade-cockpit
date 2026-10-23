"""Synthetic, safe, no network, no broker, no paid API and no Excel."""
from __future__ import annotations

from datetime import datetime, timezone
import csv
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.zero_token_strategy_worker import (
    LEDGER, REPORT, ResearchBlocked, run_once, _persist_atomic, REPO_ROOT,
)
from test_zero_token_strategy_lab import synthetic_rows, encode


class ZeroTokenWorkerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="zero_token_strategy_lab_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.output=self.root/"private_reports"
        self.output.mkdir(mode=0o700)
        self.csv=self.root/"confirmed_15s.csv"
        rows=synthetic_rows(breach=True,n=100)
        # A completed afternoon observation marks this test day final.
        from datetime import datetime
        rows.append({**rows[-1], "time":"2026-10-19T15:25:00+09:00",
                     "available_at":"2026-10-19T15:25:00+09:00"})
        self.csv.write_bytes(encode(rows))

    def test_first_run_persists_and_independent_readback(self):
        r=run_once(self.csv,self.output,clock=lambda:datetime(2026,10,23,tzinfo=timezone.utc))
        self.assertEqual(r["state"],"RESEARCH_RECORDED")
        self.assertEqual(r["analysis_status"],"INSUFFICIENT_HISTORY")
        self.assertEqual(r["llm_api_tokens_used"],0)
        self.assertFalse(r["real_submit_allowed"])
        report=json.loads((self.output/REPORT).read_text("utf-8"))
        self.assertEqual(report["analysis"]["status"],"INSUFFICIENT_HISTORY")
        self.assertEqual(report["analysis"]["cumulative_history"]["completed_symbol_days"],1)
        self.assertEqual(report["analysis"]["cumulative_history"]["pending_symbol_days"],0)
        self.assertFalse(report["paid_api_connected"])
        self.assertFalse(report["broker_connected"])
        self.assertFalse(report["automatic_order_execution"])
        self.assertIs(report["real_submit_allowed"],False)
        self.assertEqual(hashlib.sha256((self.output/REPORT).read_bytes()).hexdigest(),r["report_sha256"])
        with closing(sqlite3.connect(self.output/LEDGER)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM runs").fetchone()[0],1)

    def test_second_run_same_input_no_new_analysis_or_rewrite(self):
        first=run_once(self.csv,self.output)
        old=(self.output/REPORT).read_bytes()
        second=run_once(self.csv,self.output)
        self.assertEqual(second["state"],"UNCHANGED_NO_NEW_ANALYSIS")
        self.assertEqual((self.output/REPORT).read_bytes(),old)
        with closing(sqlite3.connect(self.output/LEDGER)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM runs").fetchone()[0],1)

    def test_changed_dataset_triggers_new_analysis(self):
        run_once(self.csv,self.output)
        rows=synthetic_rows(breach=False,n=100,date="2026-10-20")
        rows.append({**rows[-1], "time":"2026-10-20T15:25:00+09:00",
                     "available_at":"2026-10-20T15:25:00+09:00"})
        self.csv.write_bytes(encode(rows))
        result=run_once(self.csv,self.output)
        self.assertEqual(result["state"],"RESEARCH_RECORDED")
        with closing(sqlite3.connect(self.output/LEDGER)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM runs").fetchone()[0],2)

    def test_missing_data_is_not_fabricated(self):
        result=run_once(self.root/"missing.csv",self.output)
        self.assertEqual(result["state"],"DATA_UNAVAILABLE")
        self.assertFalse((self.output/REPORT).exists())
        self.assertFalse((self.output/LEDGER).exists())

    def test_corrupt_input_fails_closed_without_report(self):
        self.csv.write_text("garbage",encoding="utf-8")
        with self.assertRaisesRegex(ResearchBlocked,"BAR_HEADER_MISMATCH"):
            run_once(self.csv,self.output)
        self.assertFalse((self.output/REPORT).exists())

    def test_low_cost_prohibited(self):
        with self.assertRaisesRegex(ResearchBlocked,"COST_ASSUMPTION_TOO_LOW"):
            run_once(self.csv,self.output,base_cost_bps=1)
        self.assertFalse((self.output/REPORT).exists())

    def test_public_repository_output_denied(self):
        with self.assertRaisesRegex(ResearchBlocked,"PUBLIC_REPO_PATH_FORBIDDEN"):
            run_once(self.csv,REPO_ROOT)

    def test_relative_output_denied(self):
        with self.assertRaisesRegex(ResearchBlocked,"PRIVATE_ABSOLUTE_PATH_REQUIRED"):
            run_once(self.csv,Path("public_reports"))

    def test_symlink_input_denied(self):
        link=self.root/"linked.csv"
        try:
            link.symlink_to(self.csv)
        except (OSError,NotImplementedError):
            self.skipTest("host does not allow symlink creation")
        with self.assertRaisesRegex(ResearchBlocked,"SYMLINK_PATH_FORBIDDEN"):
            run_once(link,self.output)
        self.assertFalse((self.output/REPORT).exists())

    def test_malformed_output_report_denied_no_overwrite(self):
        target=self.output/REPORT
        target.mkdir()
        with self.assertRaisesRegex(ResearchBlocked,"OUTPUT_FILE_UNSAFE"):
            run_once(self.csv,self.output)

    def test_input_file_not_a_broker_gateway(self):
        out=run_once(self.csv,self.output)
        self.assertEqual(out["llm_api_tokens_used"],0)
        self.assertFalse(out["real_submit_allowed"])
        report=json.loads((self.output/REPORT).read_text("utf-8"))
        self.assertNotIn("order",report["analysis"])
        self.assertFalse(report["analysis"]["shadow_order_created"])

    def test_missing_output_directory_denied(self):
        with self.assertRaisesRegex(ResearchBlocked,"PRIVATE_PARENT_MISSING|OUTPUT_DIRECTORY_REQUIRED"):
            run_once(self.csv,self.root/"unknown"/"report")

    def test_multi_copy_csv_dedupes_by_sha(self):
        first=run_once(self.csv,self.output)
        copy=self.root/"same_content.csv"
        copy.write_bytes(self.csv.read_bytes())
        again=run_once(copy,self.output)
        self.assertEqual(again["state"],"UNCHANGED_NO_NEW_ANALYSIS")
        self.assertEqual(again["input_sha256"],first["input_sha256"])


if __name__=="__main__":
    unittest.main()
