import json
import os
import sqlite3
import unittest
from pathlib import Path

from auto_publish.app import audit, controls
from auto_publish.app.config import load_config
from auto_publish.app.errors import (
    AdapterNotAllowedError, ApprovalError, ControlBlockedError, PublishBlockedError, RenderError, TransientError,
    ValidationError,
)
from auto_publish.app.pipeline import approve, build_drafts, cancel, retry, schedule, story_dir
from auto_publish.app.publishers.dry_run import DryRunPublisher
from auto_publish.app.publishers.registry import get_adapter
from auto_publish.tests.helpers import SESSION, FakeRenderer, PipelineCase


class Base(PipelineCase):
    def drafts(self, renderer=None):
        self.ingest_validate()
        return build_drafts(self.ctx, SESSION, renderer or FakeRenderer())

    def first(self, results):
        return results[0]["story_id"]


class TestHappyPath(Base):
    def test_full_r1_flow_stops_at_scheduled(self):
        results = self.drafts()
        self.assertEqual([r["state"] for r in results], ["AWAITING_APPROVAL"] * 2)
        sid = self.first(results)
        approve(self.ctx, sid, "yusuke")
        res = schedule(self.ctx, sid)
        self.assertEqual(res["state"], "SCHEDULED")
        self.assertEqual({s["platform"] for s in res["schedules"]}, {"tiktok", "x", "youtube_shorts"})
        sdir = story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})
        for p in ("tiktok", "x", "youtube_shorts"):
            payload = json.loads((sdir / "dry_run" / f"{p}.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["network"], "none")
            self.assertEqual(payload["approved_by"], "yusuke")
        self.assertTrue((sdir / "schedule.json").is_file())
        self.assertTrue(audit.verify_chain(self.ctx.conn)["ok"])


class TestApprovalRequired(Base):
    def test_schedule_without_approval_is_refused(self):
        sid = self.first(self.drafts())
        with self.assertRaises(ApprovalError) as cm:
            schedule(self.ctx, sid)
        self.assertEqual(cm.exception.code, "APPROVAL_REQUIRED")
        self.assertEqual(self.story_state(sid), "AWAITING_APPROVAL")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], 0)
        sdir = story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})
        self.assertFalse((sdir / "dry_run").exists())

    def test_machine_approver_rejected(self):
        sid = self.first(self.drafts())
        for who in ("", "system", "cron", "  "):
            with self.assertRaises(ApprovalError):
                approve(self.ctx, sid, who)
        self.assertEqual(self.story_state(sid), "AWAITING_APPROVAL")

    def test_artifact_edited_before_approval_fails_closed(self):
        sid = self.first(self.drafts())
        sdir = story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})
        p = sdir / "post_en.json"
        p.write_text(p.read_text(encoding="utf-8").replace("closed at", "rocketed to"), encoding="utf-8")
        with self.assertRaises(Exception) as cm:
            approve(self.ctx, sid, "yusuke")
        self.assertEqual(cm.exception.code, "ARTIFACT_TAMPERED")
        self.assertEqual(self.story_state(sid), "FAILED")

    def test_artifact_edited_after_approval_blocks_schedule(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        sdir = story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})
        (sdir / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:06,000\nBuy now!\n", encoding="utf-8")
        with self.assertRaises(Exception) as cm:
            schedule(self.ctx, sid)
        self.assertEqual(cm.exception.code, "ARTIFACT_TAMPERED")
        self.assertEqual(self.story_state(sid), "FAILED")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], 0)


class TestIdempotency(Base):
    def test_build_drafts_twice_creates_no_duplicates(self):
        a = self.drafts()
        b = build_drafts(self.ctx, SESSION, FakeRenderer())
        self.assertEqual([r["story_id"] for r in a], [r["story_id"] for r in b])
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0], 2)

    def test_schedule_twice_is_noop_and_payload_unchanged(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        first = schedule(self.ctx, sid)
        second = schedule(self.ctx, sid)
        self.assertTrue(second["noop"])
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], 3)
        self.assertEqual(sorted(s["payload_sha256"] for s in first["schedules"]),
                         sorted(s["payload_sha256"] for s in second["schedules"]))
        self.assertTrue(approve(self.ctx, sid, "yusuke")["noop"])

    def test_same_story_cannot_be_queued_twice_per_platform(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        schedule(self.ctx, sid)
        row = dict(self.ctx.conn.execute("SELECT * FROM schedules WHERE platform='x'").fetchone())
        row.pop("schedule_id")
        row["idempotency_key"] = "different-key"
        row["publish_at_utc"] = "2026-09-24T14:00:00Z"
        cols = ",".join(row)
        with self.assertRaises(sqlite3.IntegrityError):
            self.ctx.conn.execute(f"INSERT INTO schedules({cols}) VALUES ({','.join('?' * len(row))})",
                                  list(row.values()))

    def test_two_stories_get_distinct_slots(self):
        results = self.drafts()
        for r in results:
            approve(self.ctx, r["story_id"], "yusuke")
            schedule(self.ctx, r["story_id"])
        xs = [r[0] for r in self.ctx.conn.execute("SELECT publish_at_jst FROM schedules WHERE platform='x' ORDER BY 1")]
        self.assertEqual(xs, ["2026-09-24T22:00:00+09:00", "2026-09-24T22:30:00+09:00"])


class TestControls(Base):
    def test_pause_all_blocks_generation_and_scheduling(self):
        self.ingest_validate()
        controls.pause_all(self.ctx.conn, self.ctx.clock, "owner", "incident")
        with self.assertRaises(ControlBlockedError):
            build_drafts(self.ctx, SESSION, FakeRenderer())
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0], 0)
        controls.resume_all(self.ctx.conn, self.ctx.clock, "owner")
        sid = self.first(build_drafts(self.ctx, SESSION, FakeRenderer()))
        approve(self.ctx, sid, "yusuke")
        controls.pause_all(self.ctx.conn, self.ctx.clock, "owner")
        with self.assertRaises(ControlBlockedError):
            schedule(self.ctx, sid)
        self.assertEqual(self.story_state(sid), "APPROVED")

    def test_disabled_platform_gets_no_payload(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        controls.set_platform_enabled(self.ctx.conn, self.ctx.clock, "tiktok", False, "owner")
        res = schedule(self.ctx, sid)
        self.assertEqual({s["platform"] for s in res["schedules"]}, {"x", "youtube_shorts"})
        sdir = story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})
        self.assertFalse((sdir / "dry_run" / "tiktok.json").exists())

    def test_all_platforms_disabled_refuses_without_failing_story(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        for p in ("tiktok", "x", "youtube_shorts"):
            controls.set_platform_enabled(self.ctx.conn, self.ctx.clock, p, False, "owner")
        with self.assertRaises(ControlBlockedError):
            schedule(self.ctx, sid)
        self.assertEqual(self.story_state(sid), "APPROVED")

    def test_cancel_scheduled_post(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        schedule(self.ctx, sid)
        res = cancel(self.ctx, sid, "owner changed mind")
        self.assertEqual(res["cancelled_schedules"], 3)
        statuses = {r[0] for r in self.ctx.conn.execute("SELECT status FROM schedules")}
        self.assertEqual(statuses, {"CANCELLED"})
        self.assertEqual(self.story_state(sid), "CANCELLED")


class TestRetryAndErrors(Base):
    def test_transient_errors_retry_then_succeed(self):
        r = FakeRenderer(fail_times=2, exc=TransientError("ffmpeg busy"))
        results = self.drafts(r)
        sid = self.first(results)
        self.assertEqual(results[0]["error"]["code"], "TRANSIENT")
        self.assertEqual(self.story_state(sid), "LOCALIZED")  # waiting for retry, not failed
        build_drafts(self.ctx, SESSION, r)
        self.assertEqual(self.story_state(sid), "LOCALIZED")
        build_drafts(self.ctx, SESSION, r)
        self.assertEqual(self.story_state(sid), "AWAITING_APPROVAL")
        attempts = self.ctx.conn.execute("SELECT attempts FROM stories WHERE story_id=?", (sid,)).fetchone()[0]
        self.assertEqual(attempts, 2)
        actions = [a[0] for a in self.ctx.conn.execute(
            "SELECT action FROM audit_log WHERE entity_id=? ORDER BY seq", (sid,))]
        self.assertEqual(actions.count("transient_error"), 2)

    def test_transient_errors_exhaust_to_failed(self):
        r = FakeRenderer(fail_times=99, exc=TransientError("timeout"))
        self.drafts(r)
        for _ in range(3):
            build_drafts(self.ctx, SESSION, r)
        states = {row[0] for row in self.ctx.conn.execute("SELECT state FROM stories")}
        self.assertEqual(states, {"FAILED"})
        err = json.loads(self.ctx.conn.execute("SELECT last_error FROM stories").fetchone()[0])
        self.assertEqual(err["attempt"], 3)
        sid = self.ctx.conn.execute("SELECT story_id FROM stories").fetchone()[0]
        with self.assertRaises(ValidationError) as cm:
            retry(self.ctx, sid, "again", FakeRenderer())
        self.assertEqual(cm.exception.code, "MAX_ATTEMPTS_EXCEEDED")

    def test_render_failure_fails_closed_then_manual_retry(self):
        results = self.drafts(FakeRenderer(fail_times=99, exc=RenderError("ffmpeg missing", code="FFMPEG_MISSING")))
        sid = self.first(results)
        self.assertEqual(self.story_state(sid), "FAILED")
        self.assertIsNone(self.ctx.conn.execute("SELECT 1 FROM artifacts WHERE story_id=?", (sid,)).fetchone())
        res = retry(self.ctx, sid, "ffmpeg installed", FakeRenderer())
        self.assertEqual(res["state"], "AWAITING_APPROVAL")

    def test_unexpected_exception_is_fail_closed(self):
        results = self.drafts(FakeRenderer(fail_times=99, exc=KeyError("boom")))
        for r in results:
            self.assertEqual(r["state"], "FAILED")
            self.assertEqual(r["error"]["code"], "UNEXPECTED")

    def test_one_failing_story_does_not_block_the_other(self):
        class FailFirst(FakeRenderer):
            def render(self, story_dir, post_en, plan=None):
                if "TEST1" in post_en["title"]:
                    raise RenderError("bad", code="FFMPEG_FAILED")
                return super().render(story_dir, post_en, plan)
        results = self.drafts(FailFirst())
        self.assertEqual(sorted(r["state"] for r in results), ["AWAITING_APPROVAL", "FAILED"])

    def test_missed_window_fails_closed(self):
        sid = self.first(self.drafts())
        approve(self.ctx, sid, "yusuke")
        self.ctx.clock.set(self.ctx.clock.now().replace(day=25, hour=12))  # both waves over
        with self.assertRaises(Exception) as cm:
            schedule(self.ctx, sid)
        self.assertEqual(cm.exception.code, "SCHEDULE_WINDOW_MISSED")
        self.assertEqual(self.story_state(sid), "FAILED")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], 0)


class TestPublishGate(unittest.TestCase):
    def test_dry_run_publish_is_blocked(self):
        pub = DryRunPublisher("youtube_shorts")
        for call in (lambda: pub.publish(None), lambda: pub.verify_publish("x"), lambda: pub.fetch_metrics("x")):
            with self.assertRaises(PublishBlockedError):
                call()

    def test_real_adapter_cannot_be_configured(self):
        with self.assertRaises(ValidationError) as cm:
            load_config(overrides={"platforms": {"youtube_shorts": {"adapter": "youtube"}}})
        self.assertEqual(cm.exception.code, "ADAPTER_NOT_ALLOWED")
        with self.assertRaises(ValidationError):
            load_config(overrides={"release_gate": "R2"})

    def test_registry_refuses_non_dry_run(self):
        cfg = load_config()
        cfg["platforms"]["x"]["adapter"] = "x"  # bypass validation deliberately
        with self.assertRaises(AdapterNotAllowedError):
            get_adapter("x", cfg)
        self.assertIsInstance(get_adapter("tiktok", load_config()), DryRunPublisher)


if __name__ == "__main__":
    unittest.main()
