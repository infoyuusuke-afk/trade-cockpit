import hashlib
import json
import os
import stat
import unittest
from pathlib import Path

from auto_publish.app.errors import EvidenceError, ValidationError
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.pipeline import build_drafts
from auto_publish.tests.helpers import SESSION, FakeRenderer, PipelineCase


def _edit_summary(drop: Path, **changes):
    p = drop / "daily_summary.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc.update(changes)
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class TestIngest(PipelineCase):
    def test_sha256_provenance_matches_source_files(self):
        res = ingest(self.ctx, self.drop)
        self.assertEqual(res["files"], 3)
        for r in self.ctx.conn.execute("SELECT * FROM evidence"):
            src = self.drop / r["rel_path"]
            self.assertEqual(r["sha256"], hashlib.sha256(src.read_bytes()).hexdigest())
            store = Path(r["store_path"])
            self.assertEqual(hashlib.sha256(store.read_bytes()).hexdigest(), r["sha256"])
            self.assertFalse(os.stat(store).st_mode & stat.S_IWUSR, "evidence copy must be read-only")
        self.assertEqual(len(res["manifest_sha256"]), 64)

    def test_reingest_identical_input_is_noop(self):
        first = ingest(self.ctx, self.drop)
        second = ingest(self.ctx, self.drop)
        self.assertTrue(second["noop"])
        self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], 3)

    def test_changed_input_after_lock_is_refused(self):
        ingest(self.ctx, self.drop)
        (self.drop / "session_notes.txt").write_text("edited after lock", encoding="utf-8")
        with self.assertRaises(EvidenceError) as cm:
            ingest(self.ctx, self.drop)
        self.assertEqual(cm.exception.code, "EVIDENCE_CHANGED_AFTER_LOCK")
        self.assertEqual(cm.exception.details["changed"], ["session_notes.txt"])

    def test_missing_required_summary_fails_closed(self):
        (self.drop / "daily_summary.json").unlink()
        with self.assertRaises(EvidenceError) as cm:
            ingest(self.ctx, self.drop)
        self.assertEqual(cm.exception.code, "EVIDENCE_MISSING")
        self.assertIsNone(self.ctx.conn.execute("SELECT * FROM sessions").fetchone())

    def test_symlink_is_rejected(self):
        os.symlink(self.drop / "session_notes.txt", self.drop / "link.txt")
        with self.assertRaises(EvidenceError) as cm:
            ingest(self.ctx, self.drop)
        self.assertEqual(cm.exception.code, "EVIDENCE_SYMLINK")

    def test_directory_name_must_match_date(self):
        with self.assertRaises(ValidationError) as cm:
            ingest(self.ctx, self.drop, session_date="2026-09-25")
        self.assertEqual(cm.exception.code, "DATE_MISMATCH")


class TestValidate(PipelineCase):
    def _expect_failed(self, code):
        ingest(self.ctx, self.drop)
        with self.assertRaises(ValidationError) as cm:
            validate(self.ctx, SESSION)
        self.assertEqual(cm.exception.code, code)
        row = self.ctx.conn.execute("SELECT state, last_error FROM sessions").fetchone()
        self.assertEqual(row["state"], "FAILED")
        self.assertIn(code, row["last_error"])
        with self.assertRaises(ValidationError):  # nothing downstream may run
            build_drafts(self.ctx, SESSION, FakeRenderer())

    def test_valid_fixture_extracts_facts(self):
        res = self.ingest_validate()
        self.assertEqual(res["state"], "VALIDATED")
        self.assertTrue(res["fixture"])
        kinds = [r[0] for r in self.ctx.conn.execute("SELECT kind FROM facts ORDER BY kind")]
        # 3 movers, 3 radar events, 1 paper trade (other-date and untriggered entries ignored)
        self.assertEqual(kinds.count("mover"), 3)
        self.assertEqual(kinds.count("radar_event"), 3)
        self.assertEqual(kinds.count("paper_trade"), 1)
        basis = self.ctx.conn.execute("SELECT basis FROM facts WHERE kind='paper_trade'").fetchone()[0]
        self.assertEqual(basis, "paper")

    def test_session_date_mismatch(self):
        _edit_summary(self.drop, session_date="2026-09-23")
        self._expect_failed("DATE_MISMATCH")

    def test_stale_evidence(self):
        self.ctx.clock.set(self.ctx.clock.now().replace(day=26))
        self._expect_failed("EVIDENCE_STALE")

    def test_generated_before_close(self):
        _edit_summary(self.drop, generated_at="2026-09-24T14:59:00+09:00")
        self._expect_failed("EVIDENCE_PREMATURE")

    def test_generated_in_future(self):
        _edit_summary(self.drop, generated_at="2026-09-24T18:30:00+09:00")
        self._expect_failed("EVIDENCE_FUTURE")

    def test_naive_timestamp_rejected(self):
        _edit_summary(self.drop, generated_at="2026-09-24T15:45:00")
        self._expect_failed("SCHEMA_INVALID")

    def test_non_finite_number_rejected(self):
        p = self.drop / "daily_summary.json"
        p.write_text(p.read_text(encoding="utf-8").replace('"change_pct": 6.4', '"change_pct": NaN'), encoding="utf-8")
        self._expect_failed("SCHEMA_INVALID")

    def test_unknown_source_rejected(self):
        _edit_summary(self.drop, source="somewhere")
        self._expect_failed("SCHEMA_INVALID")

    def test_evidence_store_tamper_detected_before_story_work(self):
        self.ingest_validate()
        row = self.ctx.conn.execute("SELECT store_path FROM evidence WHERE rel_path='daily_summary.json'").fetchone()
        p = Path(row["store_path"])
        os.chmod(p, 0o644)
        p.write_text(p.read_text(encoding="utf-8").replace("2345", "9999"), encoding="utf-8")
        results = build_drafts(self.ctx, SESSION, FakeRenderer())
        self.assertTrue(results)
        for r in results:
            self.assertEqual(r["state"], "FAILED")
            self.assertEqual(r["error"]["code"], "EVIDENCE_TAMPERED")


class TestWeekend(PipelineCase):
    def test_weekend_session_rejected(self):
        # Re-label the fixture as Saturday 2026-09-26
        new = self.drop.parent / "2026-09-26"
        self.drop.rename(new)
        _edit_summary(new, session_date="2026-09-26", generated_at="2026-09-26T15:45:00+09:00")
        self.ctx.clock.set(self.ctx.clock.now().replace(day=26))
        ingest(self.ctx, new)
        with self.assertRaises(ValidationError) as cm:
            validate(self.ctx, "2026-09-26")
        self.assertEqual(cm.exception.code, "NOT_TRADING_DAY")


if __name__ == "__main__":
    unittest.main()
