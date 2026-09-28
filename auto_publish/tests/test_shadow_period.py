"""Multi-business-day shadow observation (contract auto_publish.shadow_period.v1): point-in-time over
STORED day records, TSE-calendar aware, append-only, UNKNOWN-preserving, deterministic, offline.
Every flow here keeps the clock monotonic."""
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from auto_publish.app import audit, controls
from auto_publish.app.db import connect
from auto_publish.app.dispatch.simulator import run_due
from auto_publish.app.errors import ValidationError
from auto_publish.app.hashing import canonical_json
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.pipeline import approve, build_drafts, schedule, story_dir
from auto_publish.app.shadow import day as shadow
from auto_publish.app.shadow import period
from auto_publish.tests.helpers import GOLDEN_DIR, FakeRenderer, make_ctx
from auto_publish.tests.test_shadow_day import REPO, J, ShadowCase

GOLDEN = GOLDEN_DIR / "shadow_period_fixture.json"
UPDATE = os.environ.get("AUTO_PUBLISH_UPDATE_GOLDEN") == "1"
# TSE: 09-19/20 weekend, 09-21/22/23 holidays (敬老の日 / 国民の休日 / 秋分の日), 09-26/27 weekend
DATES = ("2026-09-17", "2026-09-18", "2026-09-24", "2026-09-25", "2026-09-28")
FROM, TO = "2026-09-17", "2026-09-28"
T_PERIOD = "2026-09-29T12:00:00"                    # after 09-28's due time (09-29 10:35 JST)


def nxt(ds: str) -> str:
    return (date.fromisoformat(ds) + timedelta(days=1)).isoformat()


class PeriodCase(ShadowCase):
    def session(self, ds, *, run=True, record="08:30", ingest_at="17:00", before_dispatch=None):
        """ingest/validate/build (17:00) -> approve+schedule (17:10) -> 22:00 EU -> 08:00/09:00 NA -> record."""
        new = self.root / "drops" / ds
        shutil.copytree(self.drop, new)
        p = new / "daily_summary.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update(session_date=ds, generated_at=f"{ds}T15:45:00+09:00")
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.at(f"{ds}T{ingest_at}:00" if len(ingest_at) == 5 else ingest_at)
        ingest(self.ctx, new)
        validate(self.ctx, ds)
        (r,) = build_drafts(self.ctx, ds, FakeRenderer())
        self.sid = r["story_id"]
        self.at(f"{ds}T17:10:00")
        approve(self.ctx, self.sid, "yusuke")
        schedule(self.ctx, self.sid)
        if before_dispatch:
            before_dispatch()
        if run:
            for t in (f"{ds}T22:00:00", f"{nxt(ds)}T08:00:00", f"{nxt(ds)}T09:00:00"):
                self.at(t)
                run_due(self.ctx)
        if record:
            self.at(max(f"{nxt(ds)}T09:00:00", f"{nxt(ds)}T{record}:01"))
            return shadow.record(self.ctx, ds, J(f"{nxt(ds)}T{record}:00"))

    def five_days(self, skip_record=()):
        return {ds: self.session(ds, record=None if ds in skip_record else "08:30") for ds in DATES}

    def per(self, t=T_PERIOD, a=FROM, b=TO, ctx=None):
        return period.build(ctx or self.ctx, a, b, J(t))

    def day_of(self, rep, ds):
        return next(e for e in rep["days"] if e["date"] == ds)


class TestBusinessDays(PeriodCase):
    def test_five_trading_days_across_holidays_are_ok_and_meet_the_gate(self):
        self.five_days()
        self.at("2026-09-29T13:00:00")
        rep = self.per()
        self.assertEqual((rep["contract"], rep["period_status"], rep["sent"], rep["network"]),
                         ("auto_publish.shadow_period.v1", "OK", False, "none"))
        self.assertEqual({e["date"]: e["status"] for e in rep["days"] if e["status"] != "CLOSED"},
                         {ds: "OK" for ds in DATES})
        closed = {e["date"]: e["calendar"] for e in rep["days"] if e["status"] == "CLOSED"}
        self.assertEqual(closed["2026-09-21"], "closure:敬老の日")
        self.assertEqual(closed["2026-09-26"], "weekend")
        self.assertEqual(len(closed), 7)
        self.assertEqual((rep["calendar"]["trading_days"], rep["totals"]["trading_days_due"]), (5, 5))
        self.assertEqual((rep["totals"]["would_publish"], rep["totals"]["full_chain_days"]), (15, 5))
        self.assertEqual(rep["acceptance"], {"target_trading_days": 5, "full_chain_days": 5, "met": True})
        self.assertTrue(all(v == "VERIFIED" for v in rep["checks"].values()), rep["checks"])
        self.assertEqual(rep["cross_day_duplicates"], {"payload_sha256": [], "trace_sha256": [], "story_id": []})
        self.assertNotIn("generated_at_utc", rep)                          # own generation time is outside

    def test_missing_session_and_missing_record_are_unknown_not_skipped(self):
        self.five_days(skip_record=("2026-09-25",))
        self.at("2026-09-30T13:00:00")
        rep = self.per("2026-09-30T12:00:00", "2026-09-16", "2026-09-29")
        self.assertEqual(self.day_of(rep, "2026-09-16")["reasons"], ["SESSION_MISSING"])       # no ingest at all
        self.assertEqual(self.day_of(rep, "2026-09-29")["reasons"], ["SESSION_MISSING"])
        self.assertEqual(self.day_of(rep, "2026-09-25")["reasons"], ["SHADOW_DAY_MISSING"])    # ran, not recorded
        self.assertEqual((rep["checks"]["calendar_coverage"], rep["period_status"]), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual((rep["totals"]["days_unknown"], rep["acceptance"]["met"]), (3, False))

    def test_not_yet_due_is_pending_and_premature_record_becomes_unknown_once_due(self):
        for ds in DATES[:4]:
            self.session(ds)
        self.session("2026-09-28", run=False, record=None)
        self.at("2026-09-28T22:00:00")
        run_due(self.ctx)                                                   # EU slot done, NA slot still ahead
        self.at("2026-09-28T23:00:00")
        early = shadow.record(self.ctx, "2026-09-28", J("2026-09-28T22:30:00"))
        self.assertEqual(early["report"]["day_status"], "OK")              # the day record itself is fine ...
        self.at("2026-09-29T00:00:00")
        rep = self.per("2026-09-28T23:30:00")
        e = self.day_of(rep, "2026-09-28")
        self.assertEqual((e["status"], e["final"], e["due"]), ("PENDING", False, False))    # ... but not final yet
        self.assertEqual((rep["period_status"], rep["totals"]["trading_days_pending"]), ("OK", 1))
        self.assertEqual(rep["acceptance"]["met"], False)
        self.at("2026-09-29T12:30:00")                                      # due has passed, no newer record
        e = self.day_of(self.per(), "2026-09-28")
        self.assertEqual((e["status"], e["reasons"]), ("UNKNOWN", ["SHADOW_DAY_PREMATURE"]))

    def test_fail_closed_session_is_observed_but_not_a_full_chain_day(self):
        self.at("2026-09-18T12:00:00")                                      # evidence is > 18 h old
        new = self.root / "drops" / "2026-09-17"
        shutil.copytree(self.drop, new)
        p = new / "daily_summary.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update(session_date="2026-09-17", generated_at="2026-09-17T15:45:00+09:00")
        p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        ingest(self.ctx, new)
        with self.assertRaises(ValidationError):
            validate(self.ctx, "2026-09-17")
        self.at("2026-09-18T12:10:00")
        shadow.record(self.ctx, "2026-09-17", J("2026-09-18T12:05:00"))
        self.at("2026-09-18T13:00:00")
        rep = self.per("2026-09-18T12:30:00", "2026-09-17", "2026-09-17")
        e = self.day_of(rep, "2026-09-17")
        self.assertEqual((e["status"], e["final"], e["full_chain"], e["facts"]["stories"]), ("OK", True, False, 0))
        self.assertEqual((rep["period_status"], rep["acceptance"]["met"]), ("OK", False))


class TestPointInTime(PeriodCase):
    def test_records_generated_after_as_of_are_invisible(self):
        self.session("2026-09-17")                         # record: as_of 09-18 08:30, generated 09-18 09:00
        self.at("2026-09-18T12:00:00")
        e = self.day_of(self.per("2026-09-18T08:45:00", FROM, FROM), FROM)
        self.assertEqual((e["status"], e["record"]), ("PENDING", None))    # knowable only from 09:00
        e = self.day_of(self.per("2026-09-18T11:00:00", FROM, FROM), FROM)
        self.assertEqual((e["status"], e["record"]["observation_as_of_utc"]), ("OK", "2026-09-17T23:30:00Z"))

    def test_past_period_is_never_rewritten_by_later_evidence(self):
        self.five_days()
        self.at("2026-09-29T13:00:00")
        first = period.record(self.ctx, FROM, TO, J(T_PERIOD))
        sdir = story_dir(self.ctx, {"story_id": self.sid, "session_date": "2026-09-28"})
        (sdir / "master_1080x1920.mp4").write_bytes(b"changed after would_publish")
        self.at("2026-09-29T14:00:00")
        shadow.record(self.ctx, "2026-09-28", J("2026-09-29T13:30:00"))   # new day observation: UNKNOWN
        self.at("2026-09-29T15:00:00")
        later = period.record(self.ctx, FROM, TO, J("2026-09-29T14:30:00"))
        e = self.day_of(later["report"], "2026-09-28")
        self.assertEqual((later["report"]["period_status"], e["status"]), ("UNKNOWN", "UNKNOWN"))
        self.assertFalse(later["report"]["acceptance"]["met"])
        again = period.record(self.ctx, FROM, TO, J(T_PERIOD))            # the past observation is unchanged
        self.assertEqual((again["noop"], again["report_sha256"]), (True, first["report_sha256"]))
        self.assertEqual(period.load(self.ctx, first["record_id"])["report"]["period_status"], "OK")

    def test_future_and_backdated_audit_rows_are_unknown(self):
        self.session("2026-09-17")
        self.at("2026-09-18T08:50:00")                      # appended now, stamped earlier than the head
        controls.pause_all(self.ctx.conn, self.ctx.clock, "ops")
        self.at("2026-09-18T12:00:00")
        rep = self.per("2026-09-18T11:30:00", FROM, FROM)
        self.assertEqual((rep["checks"]["audit_time"], rep["period_status"]), ("UNKNOWN", "UNKNOWN"))
        self.assertTrue(rep["audit"]["non_monotonic_seqs"])

    def test_as_of_must_be_past(self):
        self.session("2026-09-17")
        with self.assertRaises(ValidationError) as cm:
            self.per("2026-09-18T09:00:00", FROM, FROM)                  # == now
        self.assertEqual(cm.exception.code, "AS_OF_NOT_IN_PAST")


class TestResolutionAndKillSwitch(PeriodCase):
    def test_kill_switch_held_schedules_are_resolved_not_unknown(self):
        self.session("2026-09-24", record=None,
                     before_dispatch=lambda: controls.pause_all(self.ctx.conn, self.ctx.clock, "ops"))
        self.at("2026-09-25T11:00:00")
        rec = shadow.record(self.ctx, "2026-09-24", J("2026-09-25T10:40:00"))     # after due
        self.assertEqual(rec["report"]["dispatch_counts"], {})
        self.at("2026-09-25T12:00:00")
        rep = self.per("2026-09-25T11:30:00", "2026-09-24", "2026-09-24")
        e = self.day_of(rep, "2026-09-24")
        self.assertEqual((e["status"], e["final"], e["full_chain"]), ("OK", True, False))
        self.assertEqual((e["facts"]["held_by_kill_switch"], e["facts"]["kill_switch_paused"]), (3, True))
        self.assertEqual((rep["checks"]["resolution"], rep["totals"]["days_kill_switch_paused"]), ("VERIFIED", 1))

    def test_disabled_platform_is_held_and_others_publish(self):
        self.session("2026-09-24", record=None, before_dispatch=lambda: controls.set_platform_enabled(
            self.ctx.conn, self.ctx.clock, "tiktok", False, "ops", "drill"))
        self.at("2026-09-25T11:00:00")
        shadow.record(self.ctx, "2026-09-24", J("2026-09-25T10:40:00"))
        self.at("2026-09-25T12:00:00")
        e = self.day_of(self.per("2026-09-25T11:30:00", "2026-09-24", "2026-09-24"), "2026-09-24")
        self.assertEqual((e["status"], e["facts"]["platforms_disabled"], e["facts"]["would_publish"]),
                         ("OK", ["tiktok"], 2))

    def test_never_dispatched_after_due_is_unknown(self):
        self.session("2026-09-24", run=False, record=None)                 # nobody ran would-publish
        self.at("2026-09-25T11:00:00")
        shadow.record(self.ctx, "2026-09-24", J("2026-09-25T10:40:00"))
        self.at("2026-09-25T12:00:00")
        rep = self.per("2026-09-25T11:30:00", "2026-09-24", "2026-09-24")
        e = self.day_of(rep, "2026-09-24")
        self.assertEqual((e["status"], e["reasons"]), ("UNKNOWN", ["SCHEDULE_UNRESOLVED_AFTER_DUE"]))
        self.assertEqual((rep["checks"]["resolution"], rep["period_status"]), ("UNKNOWN", "UNKNOWN"))


class TestIntegrity(PeriodCase):
    def test_tampered_day_record_is_unknown_and_period_conflict_is_refused(self):
        self.five_days()
        self.at("2026-09-29T13:00:00")
        first = period.record(self.ctx, FROM, TO, J(T_PERIOD))
        c = self.ctx.conn
        c.execute("DROP TRIGGER shadow_days_append_only_u")
        c.execute("UPDATE shadow_days SET report_json = replace(report_json, '\"WOULD_PUBLISH\":3', '\"WOULD_PUBLISH\":4')"
                  " WHERE session_date='2026-09-24'")
        rep = self.per()
        self.assertEqual(self.day_of(rep, "2026-09-24")["reasons"], ["SHADOW_RECORD_TAMPERED"])
        self.assertEqual((rep["checks"]["record_integrity"], rep["period_status"]), ("UNKNOWN", "UNKNOWN"))
        with self.assertRaises(ValidationError) as cm:
            period.record(self.ctx, FROM, TO, J(T_PERIOD))
        self.assertEqual(cm.exception.code, "SHADOW_PERIOD_CONFLICT")
        rows = c.execute("SELECT record_id, report_sha256, period_status FROM shadow_periods").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(first["record_id"], first["report_sha256"], "OK")])

    def test_rewritten_audit_is_a_violation(self):
        self.five_days()
        c = self.ctx.conn
        for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'").fetchall():
            c.execute(f"DROP TRIGGER {name}")
        head = json.loads(c.execute("SELECT report_json FROM shadow_days WHERE session_date='2026-09-18'")
                          .fetchone()[0])["audit"]["head_at_as_of"]
        c.execute("UPDATE audit_log SET hash = ? WHERE hash = ?", ("0" * 64, head))
        self.at("2026-09-29T13:00:00")
        rep = self.per()
        self.assertIn("AUDIT_HEAD_MISSING", self.day_of(rep, "2026-09-18")["reasons"])
        self.assertEqual((rep["checks"]["record_integrity"], rep["checks"]["audit_chain"], rep["period_status"]),
                         ("VIOLATION", "VIOLATION", "VIOLATION"))

    def test_unanchored_record_is_unknown(self):
        self.session("2026-09-17")
        c = self.ctx.conn
        row = dict(c.execute("SELECT * FROM shadow_days").fetchone())
        self.at("2026-09-18T09:10:00")                      # a record inserted without its audit row
        c.execute("INSERT INTO shadow_days(session_date, observation_as_of_utc, contract, generated_at_utc,"
                  " report_json, report_sha256, day_status) VALUES (?,?,?,?,?,?,?)",
                  (FROM, "2026-09-17T23:31:00Z", row["contract"], "2026-09-18T00:10:00Z",
                   row["report_json"].replace("2026-09-17T23:30:00Z", "2026-09-17T23:31:00Z"),
                   shadow.report_hash(json.loads(row["report_json"].replace("2026-09-17T23:30:00Z",
                                                                            "2026-09-17T23:31:00Z"))), "OK"))
        self.at("2026-09-18T12:00:00")
        e = self.day_of(self.per("2026-09-18T11:00:00", FROM, FROM), FROM)
        self.assertEqual((e["status"], e["reasons"]), ("UNKNOWN", ["SHADOW_RECORD_UNANCHORED"]))

    def test_dry_run_boundary_breach_in_a_record_is_a_violation(self):
        self.session("2026-09-17")
        c = self.ctx.conn
        rep = json.loads(c.execute("SELECT report_json FROM shadow_days").fetchone()[0])
        rep.update(sent=True, observation_as_of_utc="2026-09-17T23:31:00Z")
        sha = shadow.report_hash(rep)
        self.at("2026-09-18T09:10:00")
        cur = c.execute("INSERT INTO shadow_days(session_date, observation_as_of_utc, contract, generated_at_utc,"
                        " report_json, report_sha256, day_status) VALUES (?,?,?,?,?,?,?)",
                        (FROM, rep["observation_as_of_utc"], shadow.CONTRACT, "2026-09-18T00:10:00Z",
                         canonical_json(rep), sha, "OK"))
        audit.append(c, self.ctx.clock, actor="test", entity_type="shadow_day", entity_id=FROM,
                     action="shadow_day_recorded", to_state="RECORDED",
                     detail={"record_id": cur.lastrowid, "observation_as_of_utc": rep["observation_as_of_utc"],
                             "report_sha256": sha, "day_status": "OK"})
        self.at("2026-09-18T12:00:00")
        rep = self.per("2026-09-18T11:00:00", FROM, FROM)
        self.assertEqual(self.day_of(rep, FROM)["reasons"], ["DRY_RUN_BOUNDARY"])
        self.assertEqual((rep["checks"]["dry_run_boundary"], rep["period_status"]), ("VIOLATION", "VIOLATION"))

    def test_cross_day_duplicates_are_detected_from_stored_records(self):
        def rep(story, payload, trace):
            return {"stories": [{"story_id": story, "schedules": [{"payload_sha256": payload}]}],
                    "dispatches": [{"trace_sha256": trace}, {"trace_sha256": None}]}
        d = period.cross_day_duplicates({"2026-09-24": rep("s1", "p1", "t1"), "2026-09-25": rep("s2", "p1", "t1"),
                                         "2026-09-28": rep("s3", "p3", "t3")})
        self.assertEqual(d, {"payload_sha256": [["p1", ["2026-09-24", "2026-09-25"]]],
                             "trace_sha256": [["t1", ["2026-09-24", "2026-09-25"]]], "story_id": []})


class TestAppendOnlyDeterminism(PeriodCase):
    def test_db_enforces_append_only_and_identity(self):
        self.session("2026-09-17")
        self.at("2026-09-18T12:00:00")
        period.record(self.ctx, FROM, FROM, J("2026-09-18T11:00:00"))
        c = self.ctx.conn
        for sql in ("UPDATE shadow_periods SET period_status='OK'", "DELETE FROM shadow_periods"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                c.execute(sql)
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO shadow_periods(date_from, date_to, observation_as_of_utc, contract,"
                      " generated_at_utc, report_json, report_sha256, period_status) SELECT date_from, date_to,"
                      " observation_as_of_utc, contract, generated_at_utc, '{}', report_sha256, 'OK' FROM shadow_periods")

    def test_recording_changes_no_state(self):
        self.five_days()
        self.at("2026-09-29T13:00:00")
        before = self.snapshot(exclude=("shadow_periods", "audit_log", "sqlite_sequence"))
        n = self.ctx.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        period.record(self.ctx, FROM, TO, J(T_PERIOD))
        self.assertEqual(self.snapshot(exclude=("shadow_periods", "audit_log", "sqlite_sequence")), before)
        rows = self.ctx.conn.execute("SELECT action FROM audit_log WHERE seq > ?", (n,)).fetchall()
        self.assertEqual([r[0] for r in rows], ["shadow_period_recorded"])
        self.assertTrue(audit.verify_chain(self.ctx.conn)["ok"])

    def test_deterministic_path_independent_and_golden(self):
        days = self.five_days()
        self.at("2026-09-29T13:00:00")
        a = period.report_hash(self.per())
        self.assertEqual(a, period.report_hash(self.per()))
        self.assertTrue(period.canonical_bytes(self.per()).startswith(b"auto_publish.shadow_period.v1\n"))
        other = self.root / "copy"
        shutil.copytree(self.ctx.paths.home, other / "home")
        ctx2 = make_ctx(other, "2026-09-29T13:00:00+09:00", self.overrides)
        try:
            self.assertEqual(period.report_hash(self.per(ctx=ctx2)), a)
        finally:
            ctx2.conn.close()
        rec = period.record(self.ctx, FROM, TO, J(T_PERIOD))
        got = {"period": {"observation_as_of_utc": rec["report"]["observation_as_of_utc"],
                          "report_sha256": rec["report_sha256"], "period_status": rec["report"]["period_status"],
                          "audit_head_at_as_of": rec["report"]["audit"]["head_at_as_of"],
                          "acceptance": rec["report"]["acceptance"]},
               "days": {ds: d["report_sha256"] for ds, d in sorted(days.items())},
               "tse_calendar_sha256": rec["report"]["calendar"]["tse_calendar_sha256"]}
        if UPDATE:
            GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertEqual(got, json.loads(GOLDEN.read_text(encoding="utf-8")))


class TestFailClosedInputs(PeriodCase):
    def test_range_calendar_and_config_are_fail_closed(self):
        self.at("2026-09-29T12:00:00")
        for a, b in (("2026-09-28", "2026-09-17"), ("2026-07-01", "2026-09-28"), ("2026-9-1", "2026-09-28")):
            with self.assertRaises(ValidationError) as cm:
                self.per("2026-09-29T11:00:00", a, b)
            self.assertEqual(cm.exception.code, "PERIOD_RANGE_INVALID", (a, b))
        with self.assertRaises(ValidationError) as cm:
            self.per("2026-09-29T11:00:00", "2031-01-06", "2031-01-10")
        self.assertEqual(cm.exception.code, "CALENDAR_UNAVAILABLE")
        for bad in (0, 63, "5", True, 2.0):
            self.ctx.cfg["shadow"] = {"acceptance_trading_days": bad}
            with self.assertRaises(ValidationError) as cm:
                self.per("2026-09-29T11:00:00")
            self.assertEqual(cm.exception.code, "CONFIG_INVALID", bad)


class TestMigrationNetworkCli(PeriodCase):
    def test_migration_006_leaves_existing_data_bit_for_bit(self):
        self.five_days()
        c = self.ctx.conn
        c.execute("DROP TRIGGER shadow_periods_append_only_u")
        c.execute("DROP TRIGGER shadow_periods_append_only_d")
        c.execute("DROP TABLE shadow_periods")
        c.execute("DELETE FROM schema_migrations WHERE version='006_shadow_periods'")
        before = self.snapshot(exclude=("sqlite_sequence", "schema_migrations"))
        chain = audit.verify_chain(c)
        c.close()
        self.ctx.conn = connect(self.ctx.paths.db)                         # applies 006 again
        self.assertEqual(self.snapshot(exclude=("sqlite_sequence", "schema_migrations", "shadow_periods")), before)
        self.assertEqual(audit.verify_chain(self.ctx.conn), chain)

    def test_offline(self):
        def boom(*a, **k):
            raise AssertionError(f"network access attempted: {a!r}")
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            self.five_days()
            self.at("2026-09-29T13:00:00")
            period.record(self.ctx, FROM, TO, J(T_PERIOD))

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "AUTO_PUBLISH_HOME": os.path.join(d, "home"), "PYTHONPATH": str(REPO)}
            env.pop("AUTO_PUBLISH_NOW", None)

            def cli(*args):
                out = subprocess.run([sys.executable, "-m", "auto_publish.cli", *args], capture_output=True,
                                     text=True, encoding="utf-8", env=env, cwd=REPO, timeout=120)
                return out.returncode, json.loads(out.stdout)
            rc, doc = cli("shadow-period", "--from", "2026-09-28", "--to", "2026-09-17")
            self.assertEqual((rc, doc["error"]["code"]), (2, "PERIOD_RANGE_INVALID"))
            rc, doc = cli("shadow-period", "--from", FROM, "--to", TO, "--as-of", "2099-01-01T00:00:00Z")
            self.assertEqual((rc, doc["error"]["code"]), (2, "AS_OF_NOT_IN_PAST"))
            rc, doc = cli("shadow-period", "--from", "2026-09-14", "--to", "2026-09-18", "--as-of",
                          "2026-09-20T00:00:00Z")                            # real clock: a date safely in the past
            rep = doc["result"]["report"]
            self.assertEqual((rc, rep["period_status"], rep["totals"]["days_unknown"]), (0, "UNKNOWN", 5))
            self.assertEqual({e["reasons"][0] for e in rep["days"] if e["trading"]}, {"SESSION_MISSING"})


if __name__ == "__main__":
    unittest.main()
