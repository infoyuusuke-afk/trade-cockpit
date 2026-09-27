"""Shadow day records (contract auto_publish.shadow_day.v1): point-in-time, deterministic,
append-only, UNKNOWN-preserving, offline. Every flow here keeps the clock monotonic."""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from auto_publish.app import audit, controls
from auto_publish.app.clock import parse_aware
from auto_publish.app.db import connect, transaction
from auto_publish.app.dispatch.simulator import SimulatedCrash, run_due
from auto_publish.app.errors import ValidationError
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.metrics.csv_import import import_csv
from auto_publish.app.metrics.optimizer import propose
from auto_publish.app.pipeline import approve, build_drafts, schedule, story_dir
from auto_publish.app.shadow import day as shadow
from auto_publish.tests.helpers import SESSION, FakeRenderer, PipelineCase, make_ctx
from auto_publish.tests.test_slot_optimizer import series, write_csv

REPO = Path(__file__).resolve().parents[2]
J = lambda s: parse_aware(s + "+09:00")          # JST wall time
T_FINAL = "2026-09-25T08:30:00"


class ShadowCase(PipelineCase):
    overrides = {"max_stories_per_session": 1}

    def at(self, jst):
        self.ctx.clock.set(J(jst))

    def day(self, *, with_proposal=False, stop_at=None):
        """17:00 ingest/build -> (17:05 proposal) -> 17:10 approve+schedule -> 22:00 EU -> 08:00 NA -> 09:00."""
        self.ingest_validate()
        (r,) = build_drafts(self.ctx, SESSION, FakeRenderer())
        self.sid = r["story_id"]
        self.sdir = story_dir(self.ctx, {"story_id": self.sid, "session_date": SESSION})
        if with_proposal:
            import_csv(self.ctx, "tiktok", write_csv(self.root / "m.csv",
                       series("tiktok", parse_aware("2026-08-10T00:00:00+09:00").date(), 20, "22:00", 1000, "a")
                       + series("tiktok", parse_aware("2026-08-15T00:00:00+09:00").date(), 20, "23:00", 3000, "b")))
            self.at("2026-09-24T17:05:00")
            self.proposal = propose(self.ctx, "tiktok", J("2026-09-24T17:04:59"))
        self.at("2026-09-24T17:10:00")
        approve(self.ctx, self.sid, "yusuke")
        schedule(self.ctx, self.sid)
        for t in ("2026-09-24T22:00:00", "2026-09-25T08:00:00"):
            if stop_at and t >= stop_at:
                break
            self.at(t)
            run_due(self.ctx)
        self.at("2026-09-25T09:00:00")

    def rep(self, t=T_FINAL, ctx=None):
        return shadow.build(ctx or self.ctx, SESSION, J(t))

    def snapshot(self, exclude=("shadow_days", "audit_log", "sqlite_sequence")):
        c = self.ctx.conn
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: [tuple(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables
                if t not in exclude}


class TestContractAndDeterminism(ShadowCase):
    def test_full_day_is_ok_and_nothing_is_sent(self):
        self.day()
        rep = self.rep()
        self.assertEqual((rep["contract"], rep["day_status"], rep["sent"], rep["network"]),
                         ("auto_publish.shadow_day.v1", "OK", False, "none"))
        self.assertEqual(rep["observation_as_of_utc"], "2026-09-24T23:30:00Z")
        self.assertEqual(rep["dispatch_counts"], {"WOULD_PUBLISH": 3})
        self.assertEqual(rep["stories"][0]["state_at_as_of"], "SCHEDULED")
        self.assertEqual(rep["stories"][0]["human_approval"], "VERIFIED")
        self.assertTrue(all(v in ("VERIFIED", "NOT_APPLICABLE") for v in rep["checks"].values()), rep["checks"])
        self.assertNotIn("generated_at_utc", json.dumps(rep))

    def test_same_input_same_hash_and_generated_at_is_outside(self):
        self.day()
        a = shadow.report_hash(self.rep())
        self.assertEqual(a, shadow.report_hash(self.rep()))
        first = shadow.record(self.ctx, SESSION, J(T_FINAL))
        self.at("2026-09-25T15:00:00")                       # later wall clock, same observation_as_of
        again = shadow.record(self.ctx, SESSION, J(T_FINAL))
        self.assertEqual((again["noop"], again["report_sha256"], again["generated_at_utc"]),
                         (True, first["report_sha256"], first["generated_at_utc"]))
        self.assertEqual(first["report_sha256"], a)
        # a copy of the whole home at another path gives the same hash (no path/env dependence)
        other = self.root / "copy"
        shutil.copytree(self.ctx.paths.home, other / "home")
        ctx2 = make_ctx(other, "2026-09-25T09:00:00+09:00", self.overrides)
        try:
            self.assertEqual(shadow.report_hash(self.rep(ctx=ctx2)), a)
        finally:
            ctx2.conn.close()

    def test_canonical_rules(self):
        self.day()
        rep = self.rep()
        self.assertTrue(shadow.canonical_bytes(rep).startswith(b"auto_publish.shadow_day.v1\n"))
        for bad in ({"x": 1.5}, {"a": [{"b": 0.1}]}, {"when_utc": "2026-09-24T22:00:00+09:00"}, {1: "k"}):
            with self.assertRaises(ValidationError) as cm:
                shadow.report_hash(bad)
            self.assertEqual(cm.exception.code, "SHADOW_CANONICAL_INVALID")
        self.assertIsNone(rep["stories"][0]["failed_code"])            # nulls are explicit keys

    def test_observation_as_of_must_be_past(self):
        self.day()
        for t in ("2026-09-25T09:00:00", "2026-09-25T10:00:00"):
            with self.assertRaises(ValidationError) as cm:
                self.rep(t)
            self.assertEqual(cm.exception.code, "AS_OF_NOT_IN_PAST")


class TestPointInTime(ShadowCase):
    def test_state_is_reconstructed_as_of(self):
        self.day(with_proposal=True)
        r = self.rep("2026-09-24T17:04:00")                   # before proposal and approval
        self.assertEqual(r["stories"][0]["state_at_as_of"], "AWAITING_APPROVAL")
        self.assertEqual((r["stories"][0]["schedules"], r["proposals"], r["dispatches"]), ([], [], []))
        r = self.rep("2026-09-24T21:00:00")                   # scheduled, nothing due yet
        self.assertEqual({s["status_at_as_of"] for s in r["stories"][0]["schedules"]}, {"SCHEDULED"})
        self.assertEqual(r["dispatches"], [])
        r = self.rep("2026-09-24T22:30:00")                   # EU done, NA not yet
        self.assertEqual({s["platform"]: s["status_at_as_of"] for s in r["stories"][0]["schedules"]},
                         {"tiktok": "WOULD_PUBLISH", "x": "WOULD_PUBLISH", "youtube_shorts": "SCHEDULED"})
        self.assertEqual(r["dispatch_counts"], {"WOULD_PUBLISH": 2})
        self.assertEqual(self.rep()["dispatch_counts"], {"WOULD_PUBLISH": 3})

    def test_future_stamped_evidence_is_unknown(self):
        self.day()
        self.at("2026-09-26T00:00:00")                        # a record stamped after generation time
        controls.pause_all(self.ctx.conn, self.ctx.clock, "ops")
        self.at("2026-09-25T09:00:00")
        r = self.rep()
        self.assertEqual((r["checks"]["audit_time"], r["day_status"]), ("UNKNOWN", "UNKNOWN"))
        self.assertIn("FUTURE_EVIDENCE", r["fail_closed"]["evidence"]["by_code"])
        self.assertEqual(r["fail_closed"]["evidence"]["by_category"]["future"], 1)
        self.assertFalse(r["kill_switch"]["paused"])                   # the future row is not used

    def test_backdated_evidence_is_unknown_not_corrected(self):
        self.day()
        self.at("2026-09-24T20:00:00")                        # appended now, stamped in the past
        controls.pause_all(self.ctx.conn, self.ctx.clock, "ops")
        self.at("2026-09-25T09:00:00")
        r = self.rep()
        self.assertEqual(r["checks"]["audit_time"], "UNKNOWN")
        self.assertEqual(r["fail_closed"]["evidence"]["by_code"]["AUDIT_TIME_NON_MONOTONIC"], 1)
        self.assertTrue(r["audit"]["non_monotonic_seqs"])
        self.assertEqual(r["dispatch_counts"], {"WOULD_PUBLISH": 3})    # recorded outcomes untouched


class TestAppendOnlyAndConflict(ShadowCase):
    def test_conflict_is_refused_and_nothing_is_rewritten(self):
        self.day()
        first = shadow.record(self.ctx, SESSION, J(T_FINAL))
        (self.sdir / "master_1080x1920.mp4").write_bytes(b"changed after would_publish")
        with self.assertRaises(ValidationError) as cm:
            shadow.record(self.ctx, SESSION, J(T_FINAL))
        self.assertEqual(cm.exception.code, "SHADOW_DAY_CONFLICT")
        rows = self.ctx.conn.execute("SELECT record_id, report_sha256 FROM shadow_days").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(first["record_id"], first["report_sha256"])])
        later = shadow.record(self.ctx, SESSION, J("2026-09-25T08:45:00"))     # a new observation is new evidence
        rep = later["report"]
        self.assertEqual((rep["day_status"], rep["checks"]["trace_integrity"]), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual({d["evidence_reason"] for d in rep["dispatches"]}, {"ARTIFACT_CHANGED"})
        self.assertEqual(rep["dispatch_counts"], {"WOULD_PUBLISH": 3})     # never re-classified

    def test_db_enforces_append_only(self):
        self.day()
        shadow.record(self.ctx, SESSION, J(T_FINAL))
        for sql in ("UPDATE shadow_days SET day_status='OK'", "DELETE FROM shadow_days"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.ctx.conn.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):                   # identity is unique in the DB too
            self.ctx.conn.execute("INSERT INTO shadow_days(session_date, observation_as_of_utc, contract,"
                                  " generated_at_utc, report_json, report_sha256, day_status)"
                                  " SELECT session_date, observation_as_of_utc, contract, generated_at_utc, '{}',"
                                  " report_sha256, 'OK' FROM shadow_days")

    def test_recording_changes_no_state(self):
        self.day(with_proposal=True)
        before = self.snapshot()
        n = self.ctx.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        shadow.record(self.ctx, SESSION, J(T_FINAL))
        self.assertEqual(self.snapshot(), before)
        rows = self.ctx.conn.execute("SELECT action FROM audit_log WHERE seq > ?", (n,)).fetchall()
        self.assertEqual([r[0] for r in rows], ["shadow_day_recorded"])
        self.assertTrue(audit.verify_chain(self.ctx.conn)["ok"])


class TestUnknownStaleMissing(ShadowCase):
    def test_in_flight_then_unknown_is_kept_as_is(self):
        self.ingest_validate()
        (r,) = build_drafts(self.ctx, SESSION, FakeRenderer())
        sid = r["story_id"]
        self.at("2026-09-24T17:10:00")
        approve(self.ctx, sid, "yusuke")
        schedule(self.ctx, sid)
        self.at("2026-09-24T22:00:00")

        def crash(p, info):
            if p == "after_claim" and info["platform"] == "tiktok":
                raise SimulatedCrash(p)
        with self.assertRaises(SimulatedCrash):
            run_due(self.ctx, hook=crash)
        self.at("2026-09-24T22:02:00")
        mid = self.rep("2026-09-24T22:01:00")
        self.assertEqual(mid["attention"]["IN_FLIGHT"], 1)
        self.at("2026-09-24T22:06:00")
        run_due(self.ctx)                                      # lease expired -> UNKNOWN, never resent
        self.at("2026-09-24T22:10:00")
        r = self.rep("2026-09-24T22:07:00")
        self.assertEqual(r["attention"]["UNKNOWN"], 1)
        self.assertEqual(r["fail_closed"]["dispatches"]["by_code"], {"DISPATCH_OUTCOME_UNKNOWN": 1})
        self.assertEqual(r["fail_closed"]["dispatches"]["by_category"], {"unknown": 1})
        self.assertEqual({d["platform"]: d["status_at_as_of"] for d in r["dispatches"]},
                         {"tiktok": "UNKNOWN", "x": "WOULD_PUBLISH"})

    def test_missing_artifact_is_unknown(self):
        self.day()
        (self.sdir / "cover.jpg").unlink()
        r = self.rep()
        self.assertEqual({d["evidence_reason"] for d in r["dispatches"]}, {"ARTIFACT_MISSING"})
        self.assertEqual(r["fail_closed"]["evidence"]["by_category"], {"missing": 3})
        self.assertEqual(r["day_status"], "UNKNOWN")

    def test_missed_window_is_stale(self):
        self.ingest_validate()
        (r,) = build_drafts(self.ctx, SESSION, FakeRenderer())
        self.at("2026-09-24T17:10:00")
        approve(self.ctx, r["story_id"], "yusuke")
        schedule(self.ctx, r["story_id"])
        self.at("2026-09-24T23:00:00")                         # 60 min late for the EU slot
        run_due(self.ctx)
        self.at("2026-09-24T23:10:00")
        rep = self.rep("2026-09-24T23:05:00")
        self.assertEqual(rep["attention"]["MISSED"], 2)
        self.assertEqual(rep["fail_closed"]["dispatches"]["by_category"], {"stale": 2})

    def test_stale_session_is_counted_by_code(self):
        self.at("2026-09-26T12:00:00")
        ingest(self.ctx, self.drop)
        with self.assertRaises(ValidationError):
            validate(self.ctx, SESSION)
        self.at("2026-09-26T13:00:00")
        r = self.rep("2026-09-26T12:30:00")
        self.assertEqual((r["session"]["state_at_as_of"], r["session"]["failed_code"]), ("FAILED", "EVIDENCE_STALE"))
        self.assertEqual(r["fail_closed"]["session"], {"by_code": {"EVIDENCE_STALE": 1}, "by_category": {"stale": 1}})
        self.assertEqual(r["stories"], [])


class TestProposalsAndDuplicates(ShadowCase):
    def test_proposal_verified_and_compared_without_changing_schedule(self):
        self.day(with_proposal=True)
        r = self.rep()
        self.assertEqual([(p["platform"], p["verdict"]) for p in r["proposals"]], [("tiktok", "VERIFIED")])
        tik = [s for s in r["stories"][0]["schedules"] if s["platform"] == "tiktok"][0]
        self.assertEqual((tik["fixed_slot"], tik["proposal_then"]["recommended_slot"], tik["proposal_differs"]),
                         ("europe@22:00", "europe@23:00", True))
        self.assertEqual(tik["publish_at_utc"], "2026-09-24T13:00:00Z")        # still the fixed slot

    def test_changed_config_is_not_reproducible_not_a_violation(self):
        self.day(with_proposal=True)
        self.ctx.cfg["optimizer"]["min_arm_samples"] = 6
        p = self.rep()["proposals"][0]
        self.assertEqual((p["verdict"], p["reason"]), ("UNKNOWN", "CONDITIONS_NOT_REPRODUCIBLE"))

    def test_tampered_stored_proposal_is_unknown(self):
        self.day(with_proposal=True)
        c = self.ctx.conn
        c.execute("DROP TRIGGER slot_proposals_append_only_u")
        c.execute("UPDATE slot_proposals SET proposal_json = replace(proposal_json, 'PROPOSED', 'INCONCLUSIVE')")
        p = self.rep()["proposals"][0]
        self.assertEqual((p["verdict"], p["reason"]), ("UNKNOWN", "PROPOSAL_TAMPERED"))

    def test_duplicates_are_reported_separately_and_not_fixed(self):
        self.day()
        c = self.ctx.conn
        tik = c.execute("SELECT payload_sha256 FROM schedules WHERE platform='tiktok'").fetchone()[0]
        c.execute("UPDATE schedules SET payload_sha256=? WHERE platform='x'", (tik,))
        c.execute("DROP INDEX ux_dispatch_would_publish")
        c.execute("DROP INDEX ux_dispatch_once")
        c.execute("INSERT INTO dispatches(schedule_id, story_id, platform, idempotency_key, status, runner_id,"
                  " claimed_at, lease_until, finished_at, trace_json, trace_sha256)"
                  " SELECT schedule_id, story_id, platform, idempotency_key, status, 'dup', claimed_at, lease_until,"
                  " finished_at, trace_json, trace_sha256 FROM dispatches WHERE platform='tiktok'")
        r = self.rep()
        d = r["duplicates"]
        self.assertEqual((len(d["idempotency_key"]), len(d["story_platform"]), len(d["payload_sha256"]),
                          d["dispatch_id"]), (1, 1, 1, []))
        self.assertEqual((r["checks"]["duplicates"], r["day_status"]), ("VIOLATION", "VIOLATION"))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM dispatches WHERE platform='tiktok'").fetchone()[0], 2)


class TestSubtitlesAndSummary(ShadowCase):
    def test_subtitle_metric_is_heuristic_and_not_a_verdict(self):
        q = shadow.subtitle_quality("1\n00:00:00,000 --> 00:00:06,000\nフィクスチャ・メ\nモリーHD\n")
        self.assertEqual((q["suspected_midword_breaks"], q["heuristic"], q["used_for_safety"]), (1, True, False))
        self.day()
        s = self.rep()["stories"][0]["content"]["ja_subtitles"]
        self.assertEqual(s["suspected_midword_breaks"], 4)
        self.assertEqual(self.rep()["day_status"], "OK")                  # observation only

    def second_session(self):
        new = self.root / "drop" / "2026-09-25"
        shutil.copytree(self.drop, new)
        p = new / "daily_summary.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update(session_date="2026-09-25", generated_at="2026-09-25T15:45:00+09:00")
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.at("2026-09-25T17:00:00")
        ingest(self.ctx, new)
        validate(self.ctx, "2026-09-25")
        (r,) = build_drafts(self.ctx, "2026-09-25", FakeRenderer())
        self.at("2026-09-25T17:10:00")
        approve(self.ctx, r["story_id"], "yusuke")
        schedule(self.ctx, r["story_id"])
        for t in ("2026-09-25T22:00:00", "2026-09-26T08:00:00", "2026-09-26T09:00:00"):
            self.at(t)
            run_due(self.ctx)

    def test_summary_over_days_uses_stored_records_only(self):
        self.day()
        shadow.record(self.ctx, SESSION, J(T_FINAL))
        self.second_session()
        shadow.record(self.ctx, "2026-09-25", J("2026-09-26T08:30:00"))
        s = shadow.summary(self.ctx, "2026-09-24", "2026-09-25")
        self.assertEqual((s["totals"]["days"], s["totals"]["days_ok"], s["totals"]["would_publish"]), (2, 2, 6))
        self.assertEqual(s["input_contract"], "auto_publish.shadow_day.v1")
        (self.sdir / "master_1080x1920.mp4").write_bytes(b"x")                # current DB/files change ...
        self.assertEqual(shadow.summary(self.ctx, "2026-09-24", "2026-09-25"), s)   # ... past results do not
        c = self.ctx.conn
        c.execute("DROP TRIGGER shadow_days_append_only_u")
        c.execute("UPDATE shadow_days SET report_json = replace(report_json, '\"OK\"', '\"VIOLATION\"')"
                  " WHERE session_date=?", (SESSION,))
        with self.assertRaises(ValidationError) as cm:
            shadow.summary(self.ctx, "2026-09-24", "2026-09-25")
        self.assertEqual(cm.exception.code, "SHADOW_RECORD_TAMPERED")


class TestMigrationAndNetwork(ShadowCase):
    def test_migration_005_leaves_existing_data_bit_for_bit(self):
        self.day(with_proposal=True)
        c = self.ctx.conn
        c.execute("DROP TRIGGER shadow_days_append_only_u")
        c.execute("DROP TRIGGER shadow_days_append_only_d")
        c.execute("DROP TABLE shadow_days")
        c.execute("DELETE FROM schema_migrations WHERE version='005_shadow_days'")
        before = self.snapshot(exclude=("sqlite_sequence", "schema_migrations"))
        chain = audit.verify_chain(c)
        c.close()
        self.ctx.conn = connect(self.ctx.paths.db)                         # applies 005 again
        after = self.snapshot(exclude=("sqlite_sequence", "schema_migrations", "shadow_days"))
        self.assertEqual(before, after)
        self.assertEqual(audit.verify_chain(self.ctx.conn), chain)
        self.assertIn("005_shadow_days", [r[0] for r in self.ctx.conn.execute("SELECT version FROM schema_migrations")])

    def test_offline(self):
        self.day(with_proposal=True)

        def boom(*a, **k):
            raise AssertionError(f"network access attempted: {a!r}")
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            shadow.record(self.ctx, SESSION, J(T_FINAL))
            shadow.summary(self.ctx, SESSION, SESSION)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "AUTO_PUBLISH_HOME": str(Path(d) / "home"), "PYTHONPATH": str(REPO)}
            env.pop("AUTO_PUBLISH_NOW", None)

            def cli(*args):
                out = subprocess.run([sys.executable, "-m", "auto_publish.cli", *args], capture_output=True,
                                     text=True, encoding="utf-8", env=env, cwd=REPO, timeout=120)
                return out.returncode, json.loads(out.stdout)
            rc, doc = cli("shadow-day", "--date", SESSION)
            self.assertEqual((rc, doc["error"]["code"]), (2, "SESSION_NOT_FOUND"))
            rc, doc = cli("shadow-day", "--date", SESSION, "--as-of", "2099-01-01T00:00:00Z")
            self.assertEqual((rc, doc["error"]["code"]), (2, "AS_OF_NOT_IN_PAST"))
            rc, doc = cli("shadow-summary", "--from", "2026-09-01", "--to", "2026-09-30")
            self.assertEqual((rc, doc["result"]["totals"]["days"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
