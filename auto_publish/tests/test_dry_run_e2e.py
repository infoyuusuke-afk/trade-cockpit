"""Dry-run E2E: INGEST -> ... -> SCHEDULE -> WOULD_PUBLISH (network-free simulator).

Covers the frozen payload contract, the full state/audit chain, tampering and
approval mismatches, timing (before / on time / too late), duplicate runs and
concurrent runners, crash/restart (UNKNOWN, never resent), the kill switches and
the drill, and end-to-end determinism.
"""
import copy
import json
import os
import socket
import sqlite3
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from auto_publish.app import audit, controls
from auto_publish.app.clock import parse_aware
from auto_publish.app.db import connect
from auto_publish.app.dispatch import simulator
from auto_publish.app.dispatch.drill import run_drill
from auto_publish.app.dispatch.simulator import SimulatedCrash, run_due
from auto_publish.app.errors import ValidationError
from auto_publish.app.hashing import sha256_file, sha256_json, write_json_atomic
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.pipeline import approve, build_drafts, cancel, retry, schedule, story_dir
from auto_publish.app.publishers.contract import PayloadContractError, validate_payload, x_weighted_length
from auto_publish.app.tts.base import wav_bytes
from auto_publish.tests.helpers import FIXTURE_DROP, GOLDEN_DIR, SESSION, FakeRenderer, PipelineCase, copy_fixture, make_ctx

EU = "2026-09-24T13:00:00Z"        # tiktok + x   (22:00 JST, europe wave)
NA = "2026-09-24T23:00:00Z"        # youtube_shorts (08:00 JST next day)
UPDATE_GOLDEN = os.environ.get("AUTO_PUBLISH_UPDATE_GOLDEN") == "1"

# Frozen E2E audit trail (entity_type, action, from_state, to_state) for one story, all platforms.
E2E_AUDIT = [
    ("session", "ingest", None, "INGESTED"),
    ("session", "transition", "INGESTED", "VALIDATED"),
    ("story", "select", None, "SELECTED"),
    ("session", "story_select", None, None),
    ("story", "transition", "SELECTED", "FACT_CHECKED"),
    ("story", "transition", "FACT_CHECKED", "SCRIPTED"),
    ("story", "transition", "SCRIPTED", "LOCALIZED"),
    ("story", "transition", "LOCALIZED", "RENDERED"),
    ("story", "transition", "RENDERED", "AWAITING_APPROVAL"),
    ("story", "transition", "AWAITING_APPROVAL", "APPROVED"),
    ("story", "transition", "APPROVED", "SCHEDULED"),
    ("schedule", "dispatch_claimed", "SCHEDULED", "DISPATCHING"),     # tiktok @ EU
    ("schedule", "would_publish", "DISPATCHING", "WOULD_PUBLISH"),
    ("schedule", "dispatch_claimed", "SCHEDULED", "DISPATCHING"),     # x @ EU
    ("schedule", "would_publish", "DISPATCHING", "WOULD_PUBLISH"),
    ("schedule", "dispatch_claimed", "SCHEDULED", "DISPATCHING"),     # youtube_shorts @ NA
    ("schedule", "would_publish", "DISPATCHING", "WOULD_PUBLISH"),
]


class E2E(PipelineCase):
    overrides = {"max_stories_per_session": 1}

    def scheduled(self):
        self.ingest_validate()
        (r,) = build_drafts(self.ctx, SESSION, FakeRenderer())
        self.sid = r["story_id"]
        approve(self.ctx, self.sid, "yusuke")
        schedule(self.ctx, self.sid)
        self.sdir = story_dir(self.ctx, {"story_id": self.sid, "session_date": SESSION})
        return self.sid

    def at(self, ts, seconds=0, ctx=None):
        (ctx or self.ctx).clock.set(parse_aware(ts) + timedelta(seconds=seconds))

    def status(self, ctx=None):
        return {r["platform"]: r["status"] for r in (ctx or self.ctx).conn.execute(
            "SELECT platform, status FROM schedules ORDER BY platform")}

    def dispatches(self, ctx=None):
        return simulator.list_dispatches(ctx or self.ctx)

    def would_publish_count(self, ctx=None):
        return (ctx or self.ctx).conn.execute(
            "SELECT COUNT(*) FROM dispatches WHERE status='WOULD_PUBLISH'").fetchone()[0]

    def actions(self, ctx=None):
        return [r[0] for r in (ctx or self.ctx).conn.execute(
            "SELECT action FROM audit_log WHERE entity_type='schedule' ORDER BY seq")]

    def reopen(self):
        """Model a process restart: drop the connection, open a fresh one on the same DB."""
        now = self.ctx.clock.now()
        self.ctx.conn.close()
        self.ctx = make_ctx(self.root, now.isoformat(), self.overrides)
        return self.ctx


# ------------------------------------------------------------------ payload contract

class TestPayloadContract(E2E):
    def payloads(self):
        self.scheduled()
        return {p: json.loads((self.sdir / "dry_run" / f"{p}.json").read_text(encoding="utf-8"))
                for p in ("youtube_shorts", "tiktok", "x")}

    def test_scheduled_payloads_are_contract_valid_and_golden(self):
        for platform, payload in self.payloads().items():
            validate_payload(payload, platform)
            golden = GOLDEN_DIR / f"payload_{platform}.json"
            if UPDATE_GOLDEN:
                write_json_atomic(golden, payload)
            self.assertEqual(payload, json.loads(golden.read_text(encoding="utf-8")), platform)

    def test_violations_are_rejected(self):
        pl = self.payloads()
        cases = [
            ("youtube_shorts", lambda p: p["request"]["status"].update(privacyStatus="public")),
            ("youtube_shorts", lambda p: p["request"]["snippet"].update(title="x" * 101)),
            ("youtube_shorts", lambda p: p["request"]["snippet"].update(title="<b>hi</b>")),
            ("tiktok", lambda p: p["request"]["post_info"].update(privacy_level="PUBLIC_TO_EVERYONE")),
            ("tiktok", lambda p: p["request"]["source_info"].update(video_size=1)),
            ("x", lambda p: p["request"].update(text="a" * 281)),
            ("x", lambda p: p["request"].update(text="東" * 141 + " Not investment advice")),
            ("x", lambda p: p["request"].update(text="Great stock!")),
            ("x", lambda p: p.update(dry_run=False)),
            ("x", lambda p: p.update(network="https")),
            ("x", lambda p: p.update(release_gate="R2")),
            ("x", lambda p: p.update(extra_field=1)),
            ("x", lambda p: p.pop("approved_by")),
            ("x", lambda p: p.update(idempotency_key="zz")),
            ("x", lambda p: p["schedule"].update(publish_at_utc="2026-09-24T14:00:00Z")),
            ("x", lambda p: p.update(fixture=False)),                       # data_class stays "fixture"
            ("tiktok", lambda p: p.update(platform="x")),
        ]
        for platform, mutate in cases:
            p = copy.deepcopy(pl[platform])
            mutate(p)
            with self.assertRaises(PayloadContractError, msg=(platform, p.get("request"))):
                validate_payload(p, platform)
        with self.assertRaises(PayloadContractError):
            validate_payload(pl["x"], "instagram")

    def test_x_weighted_length(self):
        self.assertEqual(x_weighted_length("abc"), 3)
        self.assertEqual(x_weighted_length("東京"), 4)

    def test_contract_enforced_at_schedule(self):
        self.ingest_validate()
        (r,) = build_drafts(self.ctx, SESSION, FakeRenderer())
        approve(self.ctx, r["story_id"], "yusuke")
        from auto_publish.app.publishers.dry_run import DryRunPublisher
        orig = DryRunPublisher.create_draft

        def public(self_, post):
            d = orig(self_, post)
            if self_.platform == "youtube_shorts":
                d["request"]["status"]["privacyStatus"] = "public"
            return d
        with mock.patch.object(DryRunPublisher, "create_draft", public):
            with self.assertRaises(PayloadContractError):
                schedule(self.ctx, r["story_id"])
        self.assertEqual(self.story_state(r["story_id"]), "FAILED")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], 0)


# ------------------------------------------------------------------ full chain

class TestStateTransitionChain(E2E):
    def test_ingest_to_would_publish(self):
        sid = self.scheduled()
        self.at(EU, -1)                                             # one second early
        self.assertEqual(run_due(self.ctx)["results"], [])
        self.assertEqual(set(self.status().values()), {"SCHEDULED"})
        self.at(EU)
        r = run_due(self.ctx)
        self.assertEqual([(x["platform"], x["status"]) for x in r["results"]],
                         [("tiktok", "WOULD_PUBLISH"), ("x", "WOULD_PUBLISH")])
        self.assertEqual(self.status()["youtube_shorts"], "SCHEDULED")
        self.at(NA)
        run_due(self.ctx)
        self.assertEqual(set(self.status().values()), {"WOULD_PUBLISH"})
        self.assertEqual(self.story_state(sid), "SCHEDULED")         # would_publish is not a story state
        got = [tuple(r) for r in self.ctx.conn.execute(
            "SELECT entity_type, action, from_state, to_state FROM audit_log ORDER BY seq")]
        self.assertEqual(got, E2E_AUDIT)
        self.assertTrue(audit.verify_chain(self.ctx.conn)["ok"])

    def test_trace_binds_everything_to_one_story(self):
        sid = self.scheduled()
        self.at(NA)
        run_due(self.ctx)                                           # EU slots are now > 30 min late
        (yt,) = [d for d in self.dispatches() if d["status"] == "WOULD_PUBLISH"]
        self.assertEqual(self.status(), {"tiktok": "MISSED", "x": "MISSED", "youtube_shorts": "WOULD_PUBLISH"})
        t = yt["trace"]
        story = dict(self.ctx.conn.execute("SELECT * FROM stories WHERE story_id=?", (sid,)).fetchone())
        sched = dict(self.ctx.conn.execute("SELECT * FROM schedules WHERE platform='youtube_shorts'").fetchone())
        session = self.ctx.conn.execute("SELECT manifest_sha256 FROM sessions").fetchone()[0]
        self.assertEqual((t["sent"], t["dry_run"], t["network"]), (False, True, "none"))
        self.assertEqual(t["story_id"], sid)
        self.assertEqual(t["approved_content_sha256"], story["approved_content_sha256"])
        self.assertEqual(t["approved_content_sha256"], story["content_sha256"])
        self.assertEqual(t["evidence_manifest_sha256"], session)
        self.assertEqual(t["idempotency_key"], sched["idempotency_key"])
        self.assertEqual(t["scheduled_publish_at_utc"], sched["publish_at_utc"])
        self.assertEqual(t["payload"]["sha256"], sched["payload_sha256"])
        self.assertEqual(t["payload"]["sha256"], sha256_file(self.ctx.paths.artifacts / sched["payload_path"]))
        self.assertEqual(sha256_json(t["artifacts"]), story["approved_content_sha256"])
        payload = json.loads((self.ctx.paths.artifacts / sched["payload_path"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["content_sha256"], t["approved_content_sha256"])
        self.assertEqual(payload["request"]["media"]["sha256"], t["artifacts"]["master_1080x1920.mp4"])
        hashes = {r[0] for r in self.ctx.conn.execute("SELECT hash FROM audit_log")}
        self.assertIn(t["approval_audit_hash"], hashes)
        self.assertIn(t["schedule_audit_hash"], hashes)
        wp = self.ctx.conn.execute("SELECT detail_json FROM audit_log WHERE action='would_publish'").fetchone()[0]
        self.assertEqual(json.loads(wp)["trace_sha256"], yt["trace_sha256"])
        self.assertEqual(sha256_json(t), yt["trace_sha256"])

    def test_no_network_during_would_publish(self):
        self.scheduled()

        def boom(*a, **k):
            raise AssertionError(f"network access attempted: {a!r}")
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            for ts in (EU, NA):
                self.at(ts)
                run_due(self.ctx)
        self.assertEqual(self.would_publish_count(), 3)


class TestDeterminism(E2E):
    def run_all(self, root):
        ctx = make_ctx(root, overrides=self.overrides)
        try:
            ingest(ctx, copy_fixture(root))
            validate(ctx, SESSION)
            (r,) = build_drafts(ctx, SESSION, FakeRenderer())
            approve(ctx, r["story_id"], "yusuke")
            schedule(ctx, r["story_id"])
            for ts in (EU, NA):
                ctx.clock.set(parse_aware(ts))
                run_due(ctx)
            traces = {d["platform"]: d["trace_sha256"] for d in simulator.list_dispatches(ctx)}
            trail = [tuple(x) for x in ctx.conn.execute(
                "SELECT entity_type, entity_id, action, from_state, to_state, detail_json FROM audit_log"
                " WHERE entity_type IN ('story','schedule') ORDER BY seq")]
            return traces, trail
        finally:
            ctx.conn.close()

    def test_two_independent_runs_are_identical(self):
        a = self.run_all(self.root / "a")
        b = self.run_all(self.root / "b")
        self.assertEqual(a, b)
        self.assertEqual(len(a[0]), 3)


# ------------------------------------------------------------------ tampering / approval mismatch

class TestTamperingFailsClosed(E2E):
    def expect_blocked(self, code, platform="tiktok"):
        self.at(EU)
        r = run_due(self.ctx)
        mine = [x for x in r["results"] if x["platform"] == platform]
        self.assertEqual(mine[0]["status"], "BLOCKED", r)
        self.assertEqual(mine[0]["error"]["code"], code, mine[0]["error"])
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM dispatches WHERE status='WOULD_PUBLISH'"
                                               " AND platform=?", (platform,)).fetchone()[0], 0)
        self.assertIn("dispatch_blocked", self.actions())
        self.assertEqual(run_due(self.ctx)["results"], [])            # terminal: never retried
        self.assertEqual(self.story_state(self.sid), "SCHEDULED")

    def test_master_video_changed(self):
        self.scheduled()
        (self.sdir / "master_1080x1920.mp4").write_bytes(b"other video")
        self.expect_blocked("ARTIFACT_TAMPERED")

    def test_captions_changed(self):
        self.scheduled()
        (self.sdir / "captions_ja-JP.srt").write_text("1\n00:00:00,000 --> 00:00:06,000\n今すぐ買い\n", encoding="utf-8")
        self.expect_blocked("ARTIFACT_TAMPERED")

    def test_payload_changed(self):
        self.scheduled()
        p = self.sdir / "dry_run" / "tiktok.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["request"]["post_info"]["title"] = "Buy now"
        write_json_atomic(p, d)
        self.expect_blocked("PAYLOAD_TAMPERED")

    def test_payload_missing(self):
        self.scheduled()
        (self.sdir / "dry_run" / "tiktok.json").unlink()
        self.expect_blocked("PAYLOAD_MISSING")

    def test_payload_and_schedule_row_rewritten_together(self):
        self.scheduled()
        p = self.sdir / "dry_run" / "tiktok.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["request"]["post_info"]["title"] = "Buy now"
        sha = write_json_atomic(p, d)
        self.ctx.conn.execute("UPDATE schedules SET payload_sha256=? WHERE platform='tiktok'", (sha,))
        self.expect_blocked("SCHEDULE_AUDIT_MISMATCH")

    def test_approval_hash_mismatch(self):
        self.scheduled()
        self.ctx.conn.execute("UPDATE stories SET approved_content_sha256=? WHERE story_id=?", ("0" * 64, self.sid))
        self.expect_blocked("APPROVAL_AUDIT_MISMATCH")

    def test_approval_missing(self):
        self.scheduled()
        self.ctx.conn.execute("UPDATE stories SET approved_by=NULL WHERE story_id=?", (self.sid,))
        self.expect_blocked("APPROVAL_MISSING")

    def test_source_evidence_changed(self):
        self.scheduled()
        row = self.ctx.conn.execute("SELECT store_path FROM evidence WHERE rel_path='daily_summary.json'").fetchone()
        p = Path(row[0])
        os.chmod(p, 0o644)
        p.write_bytes(p.read_bytes() + b" ")
        self.expect_blocked("EVIDENCE_TAMPERED")

    def test_adapter_swapped_in_db(self):
        self.scheduled()
        self.ctx.conn.execute("UPDATE schedules SET adapter='live' WHERE platform='tiktok'")
        self.expect_blocked("ADAPTER_NOT_ALLOWED")

    def test_audit_chain_broken(self):
        self.scheduled()
        self.ctx.conn.execute("DROP TRIGGER audit_log_no_update")
        self.ctx.conn.execute("UPDATE audit_log SET actor='mallory' WHERE seq=1")
        self.expect_blocked("AUDIT_CHAIN_BROKEN")


class TestNarrationTamperFailsClosed(TestTamperingFailsClosed):
    overrides = {"max_stories_per_session": 1,
                 "tts": {"voices": {"en-US": {"provider": "fake_tone"}, "ja-JP": {"provider": "fake_tone"}}}}

    def test_narration_changed_after_schedule(self):
        self.scheduled()
        (self.sdir / "narration_en-US.wav").write_bytes(wav_bytes(b"\x00\x00" * 24000, 24000))
        self.expect_blocked("ARTIFACT_TAMPERED")

    def test_happy_trace_records_narration(self):
        self.scheduled()
        self.at(EU)
        run_due(self.ctx)
        t = [d for d in self.dispatches() if d["platform"] == "tiktok"][0]["trace"]
        self.assertEqual(t["narration"]["en-US"], sha256_file(self.sdir / "narration_en-US.wav"))


# ------------------------------------------------------------------ timing

class TestTiming(E2E):
    def test_not_before_publish_time(self):
        self.scheduled()
        self.at(EU, -60)
        self.assertEqual(run_due(self.ctx)["results"], [])
        self.assertEqual(self.dispatches(), [])
        self.assertEqual(self.actions(), [])

    def test_within_lateness_is_dispatched(self):
        self.scheduled()
        self.at(EU, 30 * 60)
        self.assertEqual({x["status"] for x in run_due(self.ctx)["results"]}, {"WOULD_PUBLISH"})

    def test_too_late_is_missed_never_sent_late(self):
        self.scheduled()
        self.at(EU, 30 * 60 + 1)
        r = run_due(self.ctx)
        self.assertEqual({x["status"] for x in r["results"]}, {"MISSED"})
        self.assertEqual(run_due(self.ctx)["results"], [])
        self.assertEqual(self.would_publish_count(), 0)


# ------------------------------------------------------------------ duplicates / idempotency

class TestIdempotency(E2E):
    def test_repeated_runs_do_nothing_more(self):
        self.scheduled()
        self.at(EU)
        run_due(self.ctx)
        before = self.actions()
        for _ in range(3):
            self.assertEqual(run_due(self.ctx)["results"], [])
        self.assertEqual(self.actions(), before)
        self.assertEqual(self.would_publish_count(), 2)

    def test_concurrent_runner_cannot_double_claim(self):
        self.scheduled()
        self.at(EU)
        other = make_ctx(self.root, EU, self.overrides)
        seen = []

        def second_runner(point, info):
            if point == "after_claim" and info["platform"] == "tiktok":
                seen.append(run_due(other, runner_id="B"))
        try:
            run_due(self.ctx, runner_id="A", hook=second_runner)
        finally:
            other.conn.close()
        # B saw tiktok already claimed; it evaluated x (still SCHEDULED) itself, A then found x taken
        self.assertEqual([(x["platform"], x["status"]) for x in seen[0]["results"]], [("x", "WOULD_PUBLISH")])
        self.assertEqual(self.would_publish_count(), 2)
        rows = self.ctx.conn.execute("SELECT platform, runner_id FROM dispatches ORDER BY platform").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("tiktok", "A"), ("x", "B")])

    def test_db_refuses_second_attempt_even_if_schedule_is_reset(self):
        self.scheduled()
        self.at(EU)
        run_due(self.ctx)
        self.ctx.conn.execute("UPDATE schedules SET status='SCHEDULED' WHERE platform='tiktok'")   # simulated bug
        r = run_due(self.ctx)
        self.assertEqual([(x["platform"], x["status"]) for x in r["results"]], [("tiktok", "DUPLICATE_REFUSED")])
        self.assertEqual(self.would_publish_count(), 2)
        self.assertIn("dispatch_duplicate_refused", self.actions())

    def test_outcomes_are_immutable_and_append_only(self):
        self.scheduled()
        self.at(EU)
        run_due(self.ctx)
        c = self.ctx.conn
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("UPDATE dispatches SET status='IN_FLIGHT' WHERE platform='tiktok'")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("DELETE FROM dispatches")
        row = dict(c.execute("SELECT * FROM dispatches WHERE platform='tiktok'").fetchone())
        with self.assertRaises(sqlite3.IntegrityError):   # second WOULD_PUBLISH for the same idempotency key
            c.execute("INSERT INTO dispatches(schedule_id, story_id, platform, idempotency_key, status, runner_id,"
                      " claimed_at, lease_until) VALUES (?,?,?,?, 'WOULD_PUBLISH', 'x', 't', 't')",
                      (row["schedule_id"] + 100, row["story_id"], "tiktok", row["idempotency_key"]))


# ------------------------------------------------------------------ crash / restart / UNKNOWN

class TestCrashRestart(E2E):
    def crash_at(self, point):
        self.scheduled()
        self.at(EU)

        def hook(p, info):
            if p == point and info["platform"] == "tiktok":
                raise SimulatedCrash(point)
        with self.assertRaises(SimulatedCrash):
            run_due(self.ctx, hook=hook)
        return self.reopen()

    def assert_unknown_forever(self):
        ctx = self.ctx
        r = run_due(ctx)                                             # restart within the lease
        self.assertEqual(r["reconciled_unknown"], [])
        self.assertEqual(self.status()["tiktok"], "DISPATCHING")      # not re-claimed, not assumed done
        self.assertEqual([(x["platform"], x["status"]) for x in r["results"]], [("x", "WOULD_PUBLISH")])
        self.at(EU, 301)                                             # lease (300 s) expired
        r = run_due(ctx)
        self.assertEqual([x["platform"] for x in r["reconciled_unknown"]], ["tiktok"])
        self.assertEqual(self.status()["tiktok"], "UNKNOWN")
        for _ in range(2):                                           # never retried / resent
            self.at(EU, 600)
            self.assertEqual(run_due(ctx)["results"], [])
        self.assertEqual([d["status"] for d in self.dispatches() if d["platform"] == "tiktok"], ["UNKNOWN"])
        self.assertEqual(self.ctx.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action='would_publish' AND entity_id LIKE '%:tiktok'").fetchone()[0], 0)
        with self.assertRaises(ValidationError) as cm:              # no manual retry path either
            retry(ctx, self.sid, "resend?")
        self.assertEqual(cm.exception.code, "NOT_FAILED")
        cancel(ctx, self.sid, "operator")
        self.assertEqual(self.status()["tiktok"], "UNKNOWN")          # outcome record kept as-is
        self.assertTrue(audit.verify_chain(ctx.conn)["ok"])

    def test_crash_after_claim(self):
        self.crash_at("after_claim")
        self.assert_unknown_forever()

    def test_crash_before_record(self):
        self.crash_at("before_record")
        self.assert_unknown_forever()

    def test_crash_inside_record_transaction_rolls_back(self):
        self.crash_at("in_record")
        self.assertEqual(self.would_publish_count(), 0)              # the WOULD_PUBLISH write rolled back
        self.assertNotIn("would_publish", self.actions())
        self.assert_unknown_forever()

    def test_lease_expired_during_verification(self):
        self.scheduled()
        self.at(EU)

        def slow(p, info):
            if p == "before_record" and info["platform"] == "tiktok":
                self.at(EU, 301)
        r = run_due(self.ctx, hook=slow)
        self.assertEqual(r["results"][0]["status"], "UNKNOWN")
        self.assertEqual(r["results"][0]["error"]["code"], "DISPATCH_LEASE_EXPIRED")

    def test_restart_after_success_does_not_roll_back(self):
        self.scheduled()
        self.at(EU)
        run_due(self.ctx)
        snapshot = (self.status(), [d["trace_sha256"] for d in self.dispatches()])
        self.reopen()
        self.assertEqual(run_due(self.ctx)["results"], [])
        self.assertEqual((self.status(), [d["trace_sha256"] for d in self.dispatches()]), snapshot)
        self.assertEqual(self.story_state(self.sid), "SCHEDULED")


# ------------------------------------------------------------------ kill switch

class TestKillSwitch(E2E):
    def test_pause_all_blocks_the_whole_run(self):
        self.scheduled()
        controls.pause_all(self.ctx.conn, self.ctx.clock, "ops", "incident")
        self.at(EU)
        r = run_due(self.ctx)
        self.assertEqual((r["blocked"], r["due"], r["results"]), ("PAUSE_ALL", 2, []))
        self.assertEqual(self.dispatches(), [])
        self.assertEqual(set(self.status().values()), {"SCHEDULED"})
        controls.resume_all(self.ctx.conn, self.ctx.clock, "ops")
        self.assertEqual(self.would_publish_count(), 0)
        run_due(self.ctx)
        self.assertEqual(self.would_publish_count(), 2)

    def test_paused_past_the_window_is_missed(self):
        self.scheduled()
        controls.pause_all(self.ctx.conn, self.ctx.clock, "ops")
        self.at(EU)
        run_due(self.ctx)
        controls.resume_all(self.ctx.conn, self.ctx.clock, "ops")
        self.at(EU, 3600)
        self.assertEqual({x["status"] for x in run_due(self.ctx)["results"]}, {"MISSED"})
        self.assertEqual(self.would_publish_count(), 0)

    def test_pause_mid_flight_aborts_attempt_and_keeps_schedule(self):
        self.scheduled()
        self.at(EU)

        def pause(p, info):
            if p == "before_record" and info["platform"] == "tiktok":
                controls.pause_all(self.ctx.conn, self.ctx.clock, "ops", "mid-flight")
        r = run_due(self.ctx, hook=pause)
        self.assertEqual([(x["platform"], x["status"]) for x in r["results"]],
                         [("tiktok", "ABORTED"), ("x", "SKIPPED")])
        self.assertEqual(self.status(), {"tiktok": "SCHEDULED", "x": "SCHEDULED", "youtube_shorts": "SCHEDULED"})
        self.assertEqual(self.would_publish_count(), 0)
        controls.resume_all(self.ctx.conn, self.ctx.clock, "ops")
        run_due(self.ctx)                                            # ABORTED does not burn the schedule
        self.assertEqual(self.would_publish_count(), 2)

    def test_disabled_platform_is_skipped_others_proceed(self):
        self.scheduled()
        controls.set_platform_enabled(self.ctx.conn, self.ctx.clock, "x", False, "ops")
        self.at(EU)
        r = run_due(self.ctx)
        self.assertEqual([(x["platform"], x["status"]) for x in r["results"]],
                         [("tiktok", "WOULD_PUBLISH"), ("x", "SKIPPED")])

    def test_disable_mid_flight_aborts(self):
        self.scheduled()
        self.at(EU)

        def off(p, info):
            if p == "before_record" and info["platform"] == "x":
                controls.set_platform_enabled(self.ctx.conn, self.ctx.clock, "x", False, "ops")
        r = run_due(self.ctx, hook=off)
        self.assertEqual(dict((x["platform"], x["status"]) for x in r["results"]),
                         {"tiktok": "WOULD_PUBLISH", "x": "ABORTED"})

    def test_cancel_mid_flight_aborts_and_cancels(self):
        self.scheduled()
        self.at(EU)

        def cancel_now(p, info):
            if p == "before_record" and info["platform"] == "tiktok":
                cancel(self.ctx, self.sid, "ops")
        r = run_due(self.ctx, hook=cancel_now)
        self.assertEqual(r["results"][0]["status"], "ABORTED")
        self.assertEqual(r["results"][0]["reason"], "STORY_CANCELLED")
        self.assertEqual(set(self.status().values()), {"CANCELLED"})
        self.assertEqual(self.would_publish_count(), 0)

    def test_drill_passes_and_uses_an_isolated_home(self):
        before = sorted(p.name for p in self.ctx.paths.home.iterdir())
        rep = run_drill(self.ctx.cfg, FIXTURE_DROP / SESSION, renderer=FakeRenderer())
        self.assertTrue(rep["ok"], rep["checks"])
        self.assertEqual({c["check"] for c in rep["checks"]},
                         {"pause_all_blocks_run", "mid_flight_kill_switch_aborts", "disabled_platform_skipped",
                          "cancel_stops_everything", "audit_chain_intact"})
        self.assertEqual(sorted(p.name for p in self.ctx.paths.home.iterdir()), before)
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 0)

    def test_drill_refuses_real_data(self):
        drop = self.root / "real" / SESSION
        import shutil
        shutil.copytree(FIXTURE_DROP / SESSION, drop)
        p = drop / "daily_summary.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d["source"] = "ai_cockpit_export"
        d["data_class"] = "real"
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValidationError) as cm:
            run_drill(self.ctx.cfg, drop, renderer=FakeRenderer())
        self.assertIn(cm.exception.code, {"DRILL_REQUIRES_FIXTURE", "DATA_CLASS_MIXED"})


class TestMigrationFromR1(unittest.TestCase):
    def test_r1_database_gains_dispatch_tables(self):
        import tempfile
        from auto_publish.app.db import MIGRATIONS_DIR, _split_sql
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "r1.db"
            c = sqlite3.connect(db)
            c.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL"
                      " DEFAULT CURRENT_TIMESTAMP)")
            for stmt in _split_sql((MIGRATIONS_DIR / "001_init.sql").read_text(encoding="utf-8")):
                c.execute(stmt)
            c.execute("INSERT INTO schema_migrations(version) VALUES ('001_init')")
            c.commit()
            c.close()
            conn = connect(db)
            try:
                versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
                self.assertEqual(versions, ["001_init", "002_dispatch"])
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM dispatches").fetchone()[0], 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
