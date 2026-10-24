"""Persistent offline daily outcome ledger; no private market data in GitHub."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from scripts.zero_token_strategy_history import (
    HISTORY_DB, append_and_analyze_history,
)
from scripts.zero_token_strategy_lab import ResearchBlocked, load_bars_bytes
from scripts.zero_token_strategy_worker import run_once, REPORT, LEDGER
from test_zero_token_strategy_lab import synthetic_rows, encode

AFTER_CLOSE=datetime(2026,10,23,9,0,tzinfo=timezone.utc)


def finished_day(date, *, source="SYNTHETIC_TEST_ONLY", breach=True):
    rows=synthetic_rows(date=date,n=110,breach=breach,source=source)
    rows.append({**rows[-1], "time":date+"T15:25:00+09:00",
                 "available_at":date+"T15:25:00+09:00"})
    return rows


def parse(rows):
    return load_bars_bytes(encode(rows))[0]


class RollingStrategyHistoryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="zero_token_strategy_history_")
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.out=self.root/"private"
        self.out.mkdir(mode=0o700)
        self.csv=self.root/"daily.csv"

    def write_and_run(self, date, *, source="SYNTHETIC_TEST_ONLY", breach=True):
        self.csv.write_bytes(encode(finished_day(date,source=source,breach=breach)))
        return run_once(self.csv,self.out,clock=lambda:AFTER_CLOSE)

    def test_rotating_daily_csv_accumulates_observation_days(self):
        first=self.write_and_run("2026-10-19")
        second=self.write_and_run("2026-10-20")
        third=self.write_and_run("2026-10-21")
        self.assertEqual(first["observed_days"],1)
        self.assertEqual(second["observed_days"],2)
        self.assertEqual(third["observed_days"],3)
        report=json.loads((self.out/REPORT).read_text("utf-8"))
        h=report["analysis"]["cumulative_history"]
        self.assertEqual(h["completed_symbol_days"],3)
        self.assertGreater(h["recorded_trade_candidates"],0)
        self.assertEqual(h["pending_symbol_days"],0)
        self.assertEqual(report["analysis"]["llm_api_tokens_used"],0)
        self.assertFalse(report["analysis"]["promotion_eligible"])
        self.assertFalse(report["analysis"]["real_submit_allowed"])
        with closing(sqlite3.connect(self.out/HISTORY_DB)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM evidence_days").fetchone()[0],3)
        with closing(sqlite3.connect(self.out/LEDGER)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM runs").fetchone()[0],3)

    def test_same_finished_snapshot_is_idempotent(self):
        self.write_and_run("2026-10-19")
        bars=parse(finished_day("2026-10-19"))
        ret=append_and_analyze_history(self.out,bars,base_cost_bps=18,now=AFTER_CLOSE)
        self.assertEqual(ret["cumulative_history"]["newly_finalized_symbol_days"],0)
        self.assertEqual(ret["cumulative_history"]["completed_symbol_days"],1)

    def test_early_bar_revision_after_finalization_is_blocked(self):
        self.write_and_run("2026-10-19")
        rows=finished_day("2026-10-19")
        rows[5]["close"]=100.001
        with self.assertRaisesRegex(ResearchBlocked,"HISTORICAL_BAR_REVISION_CONFLICT"):
            append_and_analyze_history(self.out,parse(rows),base_cost_bps=18,now=AFTER_CLOSE)
        with closing(sqlite3.connect(self.out/HISTORY_DB)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM evidence_days").fetchone()[0],1)

    def test_late_afternoon_snapshot_addition_does_not_rewrite_early_strategy(self):
        self.write_and_run("2026-10-19")
        rows=finished_day("2026-10-19")
        rows[-1]["volume"]=2222
        r=append_and_analyze_history(self.out,parse(rows),base_cost_bps=18,now=AFTER_CLOSE)
        self.assertEqual(r["cumulative_history"]["newly_finalized_symbol_days"],0)

    def test_incomplete_day_never_enters_history(self):
        bars=parse(synthetic_rows(date="2026-10-19",n=100,breach=True))
        r=append_and_analyze_history(self.out,bars,base_cost_bps=18,now=AFTER_CLOSE)
        self.assertEqual(r["observed_days"],0)
        self.assertEqual(r["cumulative_history"]["pending_symbol_days"],1)

    def test_history_does_not_finalize_before_late_afternoon(self):
        bars=parse(finished_day("2026-10-19"))
        during=datetime(2026,10,19,5,0,tzinfo=timezone.utc)
        r=append_and_analyze_history(self.out,bars,base_cost_bps=18,now=during)
        self.assertEqual(r["observed_days"],0)
        self.assertEqual(r["cumulative_history"]["pending_symbol_days"],1)
        after=datetime(2026,10,19,7,0,tzinfo=timezone.utc)
        later=append_and_analyze_history(self.out,bars,base_cost_bps=18,now=after)
        self.assertEqual(later["observed_days"],1)

    def test_worker_reexamines_same_csv_after_finalization(self):
        self.csv.write_bytes(encode(finished_day("2026-10-19")))
        early=datetime(2026,10,19,5,0,tzinfo=timezone.utc)
        first=run_once(self.csv,self.out,clock=lambda:early)
        self.assertEqual(first["observed_days"],0)
        self.assertEqual(first["pending_symbol_days"],1)
        after=datetime(2026,10,19,7,0,tzinfo=timezone.utc)
        second=run_once(self.csv,self.out,clock=lambda:after)
        self.assertEqual(second["observed_days"],1)
        self.assertEqual(second["pending_symbol_days"],0)
        third=run_once(self.csv,self.out,clock=lambda:after)
        self.assertEqual(third["state"],"UNCHANGED_NO_NEW_ANALYSIS")

    def test_source_change_does_not_mix_simulated_and_real(self):
        self.write_and_run("2026-10-19")
        with self.assertRaisesRegex(ResearchBlocked,"HISTORY_SOURCE_OR_COST_MISMATCH"):
            append_and_analyze_history(self.out,parse(finished_day(
                "2026-10-20",source="MS2_RSS_15S_CONFIRMED")),
                base_cost_bps=18,now=AFTER_CLOSE)

    def test_changed_execution_cost_requires_new_history_version(self):
        self.write_and_run("2026-10-19")
        with self.assertRaisesRegex(ResearchBlocked,"HISTORY_SOURCE_OR_COST_MISMATCH"):
            append_and_analyze_history(self.out,parse(finished_day("2026-10-20")),
                                       base_cost_bps=35,now=AFTER_CLOSE)

    def test_corrupt_trade_record_does_not_claim_statistics(self):
        self.write_and_run("2026-10-19")
        with closing(sqlite3.connect(self.out/HISTORY_DB)) as conn, conn:
            conn.execute("UPDATE evidence_trades SET raw_json='{}'")
        with self.assertRaisesRegex(ResearchBlocked,"HISTORY_TRADE_TAMPERED"):
            append_and_analyze_history(self.out,parse(finished_day("2026-10-19")),
                                       base_cost_bps=18,now=AFTER_CLOSE)

    def test_private_history_never_stores_raw_bar_series(self):
        self.write_and_run("2026-10-19")
        with closing(sqlite3.connect(self.out/HISTORY_DB)) as con:
            cols={row[1] for row in con.execute("PRAGMA table_info(evidence_trades)")}
            self.assertNotIn("open",cols)
            self.assertNotIn("high",cols)
            self.assertNotIn("low",cols)
            self.assertNotIn("close",cols)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM evidence_days").fetchone()[0],1)


if __name__=="__main__":
    unittest.main()
