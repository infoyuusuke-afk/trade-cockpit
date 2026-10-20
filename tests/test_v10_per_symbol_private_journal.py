"""Synthetic-only offline freshness contract tests."""
import importlib.util
import tempfile
import sqlite3
from pathlib import Path
import unittest

module = Path(__file__).resolve().parents[1] / "scripts" / "v10_per_symbol_private_journal.py"
spec = importlib.util.spec_from_file_location("v10_per_symbol_private_journal", module)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def board(rows=None, heartbeat="2026-10-20T13:00:00+09:00"):
    return {"schema_version": "v10-freshness-input-1",
            "evaluated_at": "2026-10-20T13:00:30+09:00",
            "collector_heartbeat_at": heartbeat, "session_id": "TEST_20261020",
            "source_mode": "MS2_RSS_WORKBOOK", "workbook_identity_verified": True,
            "expected_tickers": ["1111.T", "2222.T"],
            "rows": rows if rows is not None else [
                {"ticker": x, "source_authenticated": True, "quote_present": True,
                 "quote_observed_at": "2026-10-20T13:00:00+09:00",
                 "quote_available_at": "2026-10-20T13:00:05+09:00"}
                for x in ("1111.T", "2222.T")]}


class FreshnessJournalTests(unittest.TestCase):
    def test_all_fresh_no_candidate_values(self):
        x = m.assess(board())
        self.assertEqual((x["fresh"], x["blocked"]), (2, 0))
        self.assertTrue(x["aggregate_eligible"])
        self.assertIn("WITHHELD", x["candidate_values"])
        self.assertFalse(x["real_submit_allowed"])

    def test_unchanged_price_not_health_failure(self):
        x = m.assess(board())
        self.assertTrue(x["collector_healthy"])
        self.assertEqual(x["fresh"], 2)

    def test_stale_one_row_does_not_hide_other_fresh_row(self):
        q = board()
        q["rows"][0]["quote_available_at"] = "2026-10-20T12:50:00+09:00"
        q["rows"][0]["quote_observed_at"] = "2026-10-20T12:49:55+09:00"
        x = m.assess(q)
        self.assertEqual(x["fresh"], 1)
        self.assertFalse(x["aggregate_eligible"])
        self.assertEqual(x["rows"][1]["state"], "FRESH")

    def test_heartbeat_failure_blocks_both(self):
        x = m.assess(board(heartbeat="2026-10-20T12:40:00+09:00"))
        self.assertEqual(x["fresh"], 0)
        self.assertFalse(x["collector_healthy"])

    def test_missing_future_and_unauthenticated(self):
        q = board()
        q["rows"][0]["source_authenticated"] = False
        q["rows"][1]["quote_available_at"] = "2026-10-20T13:03:00+09:00"
        x = m.assess(q)
        self.assertEqual(x["blocked"], 2)

    def test_duplicates_and_missing(self):
        q = board()
        q["rows"] = [q["rows"][0], q["rows"][0]]
        with self.assertRaisesRegex(m.EvidenceRejected, "DUPLICATE_SYMBOL"):
            m.assess(q)
        q["rows"] = []
        self.assertEqual(m.assess(q)["blocked"], 2)

    def test_restart_retains_hash_chain_and_detects_tamper(self):
        if m.os.name == "nt":
            self.skipTest("Windows native append not accepted")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            a = m.assess(board())
            res = m.journal_append(path, a)
            self.assertEqual(res["records"], 1)
            b = m.assess(board(heartbeat="2026-10-20T12:59:00+09:00"))
            # Same event timestamp is deliberately rejected to prevent replay.
            with self.assertRaisesRegex(m.EvidenceRejected, "DUPLICATE_EVENT"):
                m.journal_append(path, b)
            b["evaluated_at"] = "2026-10-20T13:01:00+00:00"
            res = m.journal_append(path, b)
            self.assertEqual(res["records"], 2)
            self.assertEqual(len(m.journal_read(path)), 2)
            path.write_text(path.read_text().replace('"fresh":2', '"fresh":0'), encoding="utf-8")
            with self.assertRaisesRegex(m.EvidenceRejected, "JOURNAL_HASH_CHAIN_BROKEN"):
                m.journal_read(path)


    def test_sqlite_restart_readback_and_two_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "private.sqlite3"
            first = m.assess(board())
            x = m.sqlite_candidate_append(target, first)
            self.assertEqual(x["records"], 1)
            self.assertIn("NOT_WINDOWS_DURABILITY_ACCEPTED", x["status"])
            with self.assertRaises(sqlite3.IntegrityError):
                m.sqlite_candidate_append(target, first)
            second = m.assess(board())
            second["evaluated_at"] = "2026-10-20T13:01:00+00:00"
            got = m.sqlite_candidate_append(target, second)
            self.assertEqual(got["records"], 2)
            self.assertEqual(len(m.sqlite_candidate_read(target)), 2)

    def test_sqlite_rollback_keeps_previous_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.sqlite3"
            first = m.assess(board())
            m.sqlite_candidate_append(path, first)
            second = m.assess(board())
            second["evaluated_at"] = "2026-10-20T13:01:00+00:00"
            with self.assertRaisesRegex(OSError, "INJECTED_ROLLBACK"):
                m.sqlite_candidate_append(path, second, inject_failure=True)
            self.assertEqual(len(m.sqlite_candidate_read(path)), 1)
            m.sqlite_candidate_append(path, second)
            self.assertEqual(len(m.sqlite_candidate_read(path)), 2)

    def test_sqlite_modified_payload_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.sqlite3"
            first = m.assess(board())
            m.sqlite_candidate_append(path, first)
            with sqlite3.connect(path) as conn:
                conn.execute("UPDATE immutable_verdict SET payload=? WHERE seq=1", (b"{}",))
            with self.assertRaisesRegex(m.EvidenceRejected, "SQLITE_TAMPERED"):
                m.sqlite_candidate_read(path)

    def test_sqlite_rejects_repo_path_and_bad_real_submit(self):
        with self.assertRaisesRegex(m.EvidenceRejected, "PUBLIC_REPO_PATH_FORBIDDEN"):
            m.sqlite_candidate_append(m.REPO / "no-repo.sqlite3", m.assess(board()))
        with tempfile.TemporaryDirectory() as tmp:
            bad = m.assess(board())
            bad["real_submit_allowed"] = True
            with self.assertRaisesRegex(m.EvidenceRejected, "REAL_ORDER_FLAG_FORBIDDEN"):
                m.sqlite_candidate_append(Path(tmp) / "private.sqlite3", bad)

    def test_repo_path_rejected(self):
        with self.assertRaisesRegex(m.EvidenceRejected, "PUBLIC_REPO_PATH_FORBIDDEN"):
            m.journal_append(m.REPO / "private-do-not-write.jsonl", m.assess(board()))


if __name__ == "__main__":
    unittest.main()
