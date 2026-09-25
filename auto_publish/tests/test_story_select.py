import json
import os
import tempfile
import unittest
from pathlib import Path

from auto_publish.app.pipeline import _draft, build_drafts
from auto_publish.app.story.select import build_candidate, score, select_stories
from auto_publish.tests.helpers import GOLDEN_DIR, SESSION, FakeRenderer, PipelineCase, copy_fixture, make_ctx
from auto_publish.app.ingest.ingest import ingest, validate


class TestSelection(PipelineCase):
    def test_complete_evidence_beats_dramatic_thin_evidence(self):
        self.ingest_validate()
        ids = select_stories(self.ctx, SESSION)
        topics = [self.ctx.conn.execute("SELECT topic FROM stories WHERE story_id=?", (i,)).fetchone()[0] for i in ids]
        # TEST2 moved +9.8% but has a single evidence bullet -> never selected
        self.assertNotIn("TEST2.T", topics)
        self.assertEqual(topics, ["TEST1.T", "TEST3.T"])
        audit = self.ctx.conn.execute(
            "SELECT detail_json FROM audit_log WHERE action='story_select'").fetchone()[0]
        rejected = json.loads(audit)["rejected"]
        self.assertEqual(rejected[0]["topic"], "TEST2.T")
        self.assertIn("evidence-backed bullets", rejected[0]["reason"])

    def test_magnitude_alone_does_not_outrank_completeness(self):
        weak = {"magnitude": 1.0, "volume_anomaly": 0.0, "radar_quality": 0.0, "evidence_completeness": 0.25,
                "learning_value": 0.0}
        strong = {"magnitude": 0.2, "volume_anomaly": 0.2, "radar_quality": 0.5, "evidence_completeness": 1.0,
                  "learning_value": 1.0}
        self.assertLess(score(weak, False)[0], score(strong, False)[0])

    def test_candidate_requires_min_bullets(self):
        facts = [{"fact_id": "f1", "kind": "mover", "value": {"change_pct": 5, "close": 1}}]
        c = build_candidate("X", facts, 3)
        self.assertFalse(c["eligible"])

    def test_selection_is_idempotent(self):
        self.ingest_validate()
        a = select_stories(self.ctx, SESSION)
        b = select_stories(self.ctx, SESSION)
        self.assertEqual(a, b)
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0], 2)

    def test_story_id_is_stable_across_independent_runs(self):
        self.ingest_validate()
        a = select_stories(self.ctx, SESSION)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
            root = Path(other)
            drop = copy_fixture(root)
            ctx2 = make_ctx(root)
            ingest(ctx2, drop)
            validate(ctx2, SESSION)
            b = select_stories(ctx2, SESSION)
            ctx2.conn.close()
            for dp, _d, fs in os.walk(root):
                for f in fs:
                    os.chmod(os.path.join(dp, f), 0o644)
        self.assertEqual(a, b)

    def test_repeat_topic_penalty(self):
        self.ingest_validate()
        select_stories(self.ctx, SESSION)
        # A previous session that already covered TEST1 penalises it today.
        self.ctx.conn.execute("INSERT INTO sessions(session_date,input_dir,state,created_at,updated_at)"
                              " VALUES ('2026-09-22','x','VALIDATED','t','t')")
        from auto_publish.app.story.select import _load_facts
        facts = _load_facts(self.ctx, SESSION)["TEST1.T"]
        c = build_candidate("TEST1.T", facts, 3)
        s_fresh, _ = score(c["features"], False)
        s_repeat, bd = score(c["features"], True)
        self.assertAlmostEqual(s_fresh - s_repeat, 0.30)
        self.assertEqual(bd["repeat_topic_penalty"], -0.30)

    def test_concurrent_runner_sees_existing_selection(self):
        """Second runner with its own connection gets the same ids, no IntegrityError."""
        from auto_publish.app.db import connect
        from auto_publish.app.context import Ctx
        self.ingest_validate()
        other = Ctx(conn=connect(self.ctx.paths.db), clock=self.ctx.clock, cfg=self.ctx.cfg, paths=self.ctx.paths)
        try:
            a = select_stories(self.ctx, SESSION)
            b = select_stories(other, SESSION)
        finally:
            other.conn.close()
        self.assertEqual(a, b)
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0], 2)


class TestGoldenStory(PipelineCase):
    def test_canonical_story_json_matches_golden(self):
        self.ingest_validate()
        results = build_drafts(self.ctx, SESSION, FakeRenderer())
        for r in results:
            self.assertEqual(r["state"], "AWAITING_APPROVAL", r)
        for sid in (r["story_id"] for r in results):
            topic = self.ctx.conn.execute("SELECT topic FROM stories WHERE story_id=?", (sid,)).fetchone()[0]
            for lang in ("canonical", "en-US", "ja-JP"):
                got = _draft(self.ctx, sid, lang)
                golden = GOLDEN_DIR / f"{topic.split('.')[0]}_{lang}.json"
                if os.environ.get("AUTO_PUBLISH_UPDATE_GOLDEN") == "1":
                    golden.write_text(json.dumps(got, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
                self.assertTrue(golden.is_file(), f"missing golden {golden.name}")
                self.assertEqual(got, json.loads(golden.read_text(encoding="utf-8")), golden.name)


if __name__ == "__main__":
    unittest.main()
