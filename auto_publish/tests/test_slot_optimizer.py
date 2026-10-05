"""Timing optimisation (proposal-only): CSV contract, point-in-time dataset, sample gate,
Thompson-sampling proposals, Shadow comparison, determinism and no-lookahead.

All data is synthetic and generated here. Nothing in this phase changes a schedule.
"""
import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from auto_publish.app.clock import JST, parse_aware
from auto_publish.app.config import load_config
from auto_publish.app.errors import ValidationError
from auto_publish.app.metrics.csv_import import HEADER, MetricsError, import_csv
from auto_publish.app.metrics.dataset import allowed_slots, baseline_slot, build_dataset, gate, report
from auto_publish.app.metrics.optimizer import evaluate, load_proposal, propose, shadow
from auto_publish.tests.helpers import make_ctx

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "auto_publish"


def row(platform, ref, published, observed_h=30, views=1000, completion=0.5, story_id="", **over):
    pub = published if isinstance(published, datetime) else parse_aware(published)
    r = {"platform": platform, "post_ref": ref, "story_id": story_id, "published_at": pub.isoformat(),
         "observed_at": (pub + timedelta(hours=observed_h)).isoformat(), "impressions": views * 3, "views": views,
         "watch_time_seconds": views * 10, "completion_rate": completion, "likes": views // 20,
         "comments": views // 200, "shares": views // 100, "saves": views // 150, "follows_gained": views // 500,
         "video_duration_seconds": 30}
    r.update(over)
    return r


def at_jst(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=JST)


def series(platform, start: date, n_days: int, hhmm: str, base_views: int, prefix: str, completion=0.5):
    out = []
    for i in range(n_days):
        v = int(base_views * (1 + ((i * 37) % 11 - 5) / 50))
        out.append(row(platform, f"{prefix}{i:03d}", at_jst(start + timedelta(days=i), hhmm), views=v,
                       completion=completion))
    return out


def write_csv(path: Path, rows, header=HEADER) -> Path:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, "") if not isinstance(r, list) else "" for h in header] if isinstance(r, dict) else r)
    path.write_bytes(buf.getvalue().encode("utf-8"))    # LF bytes on every OS (no text-mode newline translation)
    return path


START = date(2026, 7, 1)
AS_OF = "2026-08-15T12:00:00+09:00"      # evaluation point
IMPORT_AT = "2026-08-15T11:00:00+09:00"  # data is imported before it
EVAL_AT = "2026-08-15T13:00:00+09:00"    # evaluations run after it (as_of must be in the past)


class Case(unittest.TestCase):
    overrides: dict | None = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ap_opt_")
        self.root = Path(self._tmp.name)
        self.ctx = make_ctx(self.root, IMPORT_AT, self.overrides)
        self.n = 0

    def tearDown(self):
        self.ctx.conn.close()
        for dp, _d, fs in os.walk(self.root):
            for f in fs:
                os.chmod(os.path.join(dp, f), 0o644)
        self._tmp.cleanup()

    def csv(self, rows, name=None):
        self.n += 1
        return write_csv(self.root / (name or f"m{self.n}.csv"), rows)

    def imp(self, rows, platform="tiktok", at=None):
        if at:
            self.ctx.clock.set(parse_aware(at))
        return import_csv(self.ctx, platform, self.csv(rows))

    def err(self, rows, platform="tiktok"):
        with self.assertRaises(MetricsError) as cm:
            self.imp(rows, platform)
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM post_metrics").fetchone()[0], 0)
        return cm.exception

    def as_of(self, s=AS_OF):
        return self.pit(s)

    def pit(self, s):
        """An as_of in the past: the evaluation runs an hour after it (M2: as_of < current second)."""
        t = parse_aware(s)
        if self.ctx.clock.now() <= t:
            self.ctx.clock.set(t + timedelta(hours=1))
        return t


# ------------------------------------------------------------------ CSV contract / importer

class TestImporter(Case):
    def test_import_is_read_only_hashed_and_idempotent(self):
        p = self.csv(series("tiktok", START, 3, "22:00", 1000, "a"))
        before = p.read_bytes()
        a = import_csv(self.ctx, "tiktok", p)
        b = import_csv(self.ctx, "tiktok", p)
        self.assertEqual((a["rows_new"], b["noop"], b["import_id"]), (3, True, a["import_id"]))
        self.assertEqual(p.read_bytes(), before)
        row_ = self.ctx.conn.execute("SELECT * FROM metrics_imports").fetchone()
        import hashlib
        self.assertEqual(row_["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(Path(row_["store_path"]).read_bytes(), before)       # reproducible input
        self.assertEqual(row_["source_name"], p.name)                           # no local path recorded
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM post_metrics").fetchone()[0], 3)

    def test_same_rows_in_a_new_file_are_duplicates_not_rewrites(self):
        rows = series("tiktok", START, 3, "22:00", 1000, "a")
        self.imp(rows)
        r = self.imp(rows + series("tiktok", START + timedelta(days=5), 1, "22:00", 1000, "b"))
        self.assertEqual((r["rows_new"], r["rows_duplicate"]), (1, 3))

    def test_identical_duplicate_row_in_file_is_collapsed(self):
        rows = series("tiktok", START, 2, "22:00", 1000, "a")
        r = self.imp(rows + [rows[0]])
        self.assertEqual((r["rows_new"], r["rows_duplicate"]), (2, 1))

    def test_conflicting_duplicate_row_rejects_file(self):
        rows = series("tiktok", START, 2, "22:00", 1000, "a")
        bad = dict(rows[0], views=5)
        e = self.err(rows + [bad])
        self.assertEqual(e.code, "DUPLICATE_CONFLICT")

    def test_updated_snapshot_is_appended_and_rewrite_is_refused(self):
        pub = at_jst(START, "22:00")
        self.imp([row("tiktok", "p1", pub, observed_h=30, views=1000)], at="2026-07-03T06:00:00+09:00")
        r = self.imp([row("tiktok", "p1", pub, observed_h=40, views=1500)], at="2026-07-03T16:00:00+09:00")
        self.assertEqual(r["rows_new"], 1)
        snaps = self.ctx.conn.execute("SELECT views, known_at_utc FROM post_metrics ORDER BY observed_at_utc").fetchall()
        self.assertEqual([s[0] for s in snaps], [1000, 1500])
        with self.assertRaises(MetricsError) as cm:          # same observation time, different numbers
            self.imp([row("tiktok", "p1", pub, observed_h=30, views=999)])
        self.assertEqual(cm.exception.code, "METRICS_CONFLICT")
        with self.assertRaises(MetricsError) as cm:          # post re-dated
            self.imp([row("tiktok", "p1", pub + timedelta(minutes=30), observed_h=50)])
        self.assertEqual(cm.exception.code, "METRICS_CSV_INVALID")

    def test_future_timestamp(self):
        e = self.err([row("tiktok", "f1", "2026-08-15T10:00:00+09:00", observed_h=5)])   # observed after now
        self.assertEqual(e.details["errors"][0]["code"], "FUTURE_TIMESTAMP")

    def test_platform_mismatch(self):
        e = self.err([row("youtube_shorts", "y1", at_jst(START, "08:00"))], platform="tiktok")
        self.assertEqual(e.details["errors"][0]["code"], "PLATFORM_MISMATCH")
        with self.assertRaises(MetricsError):
            self.imp([row("tiktok", "t", at_jst(START, "22:00"))], platform="instagram")

    def test_malformed_inputs(self):
        good = row("tiktok", "m1", at_jst(START, "22:00"))
        cases = [
            dict(good, views="1,000"), dict(good, views="-1"), dict(good, likes="3.5"),
            dict(good, published_at="2026-07-01T22:00:00"),                   # naive timestamp
            dict(good, completion_rate="1.2"), dict(good, views=5000, impressions=10),
            dict(good, observed_at="2026-07-01T00:00:00+09:00"),              # before published
            dict(good, views="", impressions=""), dict(good, post_ref="bad ref!"),
            dict(good, story_id="story-1"), dict(good, video_duration_seconds="0"),
        ]
        for c in cases:
            with self.subTest(c=c):
                self.err([c])
        with self.assertRaises(MetricsError) as cm:
            import_csv(self.ctx, "tiktok", write_csv(self.root / "h.csv", [], header=HEADER[:-1]))
        self.assertEqual(cm.exception.code, "METRICS_CSV_HEADER")
        with self.assertRaises(MetricsError) as cm:
            import_csv(self.ctx, "tiktok", write_csv(self.root / "e.csv", []))
        self.assertEqual(cm.exception.code, "METRICS_CSV_EMPTY")
        p = self.root / "bin.csv"
        p.write_bytes(b"\xff\xfe" + ",".join(HEADER).encode("utf-16-le"))
        with self.assertRaises(MetricsError) as cm:
            import_csv(self.ctx, "tiktok", p)
        self.assertEqual(cm.exception.code, "METRICS_CSV_ENCODING")
        short = self.root / "short.csv"
        short.write_text(",".join(HEADER) + "\ntiktok,x1\n", encoding="utf-8")
        with self.assertRaises(MetricsError):
            import_csv(self.ctx, "tiktok", short)

    def test_excel_bom_and_optional_blanks_accepted(self):
        p = self.root / "bom.csv"
        r = row("tiktok", "b1", at_jst(START, "22:00"), follows_gained="", saves="", impressions="")
        write_csv(p, [r])
        p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
        import_csv(self.ctx, "tiktok", p)
        got = self.ctx.conn.execute("SELECT impressions, saves, follows_gained FROM post_metrics").fetchone()
        self.assertEqual(tuple(got), (None, None, None))                     # "not available", never 0

    def test_tables_are_append_only(self):
        self.imp(series("tiktok", START, 1, "22:00", 1000, "a"))
        for sql in ("UPDATE post_metrics SET views=1", "DELETE FROM post_metrics",
                    "UPDATE metrics_imports SET sha256='x'", "DELETE FROM metrics_imports"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.ctx.conn.execute(sql)

    def test_stored_copy_tamper_fails_closed(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START, 20, "23:00", 1000, "b"))
        p = Path(self.ctx.conn.execute("SELECT store_path FROM metrics_imports").fetchone()[0])
        os.chmod(p, 0o644)
        p.write_bytes(p.read_bytes() + b"\n")
        with self.assertRaises(MetricsError) as cm:
            evaluate(self.ctx, "tiktok", self.as_of())
        self.assertEqual(cm.exception.code, "METRICS_STORE_TAMPERED")


# ------------------------------------------------------------------ dataset / point-in-time / slots

class TestDataset(Case):
    def test_allowed_slots_are_exactly_the_approved_waves(self):
        cfg = self.ctx.cfg
        self.assertEqual([s["slot"] for s in allowed_slots(cfg, "tiktok")],
                         ["europe@22:00", "europe@22:30", "europe@23:00", "europe@23:30",
                          "na_tiktok@05:00", "na_tiktok@05:30", "na_tiktok@06:00", "na_tiktok@06:30"])
        self.assertEqual(baseline_slot(cfg, "youtube_shorts"), "na_shorts@08:00")
        self.assertEqual(baseline_slot(cfg, "x"), "europe@22:00")

    def test_out_of_slot_posts_are_excluded(self):
        self.imp([row("tiktok", "o1", at_jst(START, "21:00")), row("tiktok", "o2", at_jst(START, "22:04")),
                  row("tiktok", "o3", at_jst(START, "22:06"))])
        ds = build_dataset(self.ctx, "tiktok", self.as_of())
        self.assertEqual([p["post_ref"] for p in ds["posts"]], ["o2"])       # within 5 min tolerance
        self.assertEqual(ds["excluded"]["out_of_allowed_slot"], 2)

    def test_horizon_snapshot_selection(self):
        pub = at_jst(START, "22:00")
        self.imp([row("tiktok", "h1", pub, observed_h=10, views=100), row("tiktok", "h1", pub, observed_h=30, views=900),
                  row("tiktok", "h1", pub, observed_h=45, views=1200), row("tiktok", "h2", pub, observed_h=60)])
        ds = build_dataset(self.ctx, "tiktok", self.as_of())
        self.assertEqual([(p["post_ref"], p["views"]) for p in ds["posts"]], [("h1", 900)])
        self.assertEqual(ds["excluded"]["no_horizon_snapshot"], 1)

    def test_point_in_time_no_lookahead(self):
        pub = at_jst(START, "22:00")
        self.imp([row("tiktok", "k1", pub, observed_h=30, views=1000)], at="2026-07-03T09:00:00+09:00")
        self.imp([row("tiktok", "k2", pub, observed_h=30, views=2000)], at="2026-07-05T09:00:00+09:00")
        t = parse_aware("2026-07-04T09:00:00+09:00")
        ds = build_dataset(self.ctx, "tiktok", t)
        self.assertEqual([p["post_ref"] for p in ds["posts"]], ["k1"])     # k2 observed before t but known after t
        early = build_dataset(self.ctx, "tiktok", parse_aware("2026-07-02T23:00:00+09:00"))
        self.assertEqual(early["posts"], [])                                 # not yet imported

    def test_dst_boundaries_keep_slot_and_move_audience_hour(self):
        rows = [row("tiktok", "d1", at_jst(date(2026, 10, 23), "22:00")),
                row("tiktok", "d2", at_jst(date(2026, 10, 26), "22:00")),
                row("tiktok", "d3", at_jst(date(2026, 10, 30), "05:00")),
                row("tiktok", "d4", at_jst(date(2026, 11, 2), "05:00")),
                row("tiktok", "d5", parse_aware("2026-10-27T14:00:00+01:00"))]  # = 22:00 JST, given in London time
        self.imp(rows, at="2026-11-10T00:00:00+09:00")
        ds = {p["post_ref"]: p for p in build_dataset(self.ctx, "tiktok", self.pit("2026-11-10T00:00:00+09:00"))["posts"]}
        self.assertEqual({k: v["slot"] for k, v in ds.items()},
                         {"d1": "europe@22:00", "d2": "europe@22:00", "d3": "na_tiktok@05:00",
                          "d4": "na_tiktok@05:00", "d5": "europe@22:00"})
        self.assertEqual((ds["d1"]["audience_local_hour"], ds["d2"]["audience_local_hour"]), (14, 13))   # BST -> GMT
        self.assertEqual((ds["d3"]["audience_local_hour"], ds["d4"]["audience_local_hour"]), (16, 15))   # EDT -> EST
        self.assertEqual(ds["d4"]["audience_weekday"], "Sun")

    def test_platforms_are_never_mixed(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "t"))
        self.imp(series("youtube_shorts", START, 3, "08:00", 50, "y"), platform="youtube_shorts")
        self.assertEqual(len(build_dataset(self.ctx, "youtube_shorts", self.as_of())["posts"]), 3)
        self.assertEqual(len(build_dataset(self.ctx, "tiktok", self.as_of())["posts"]), 20)

    def test_report_groups_and_unknown_cells(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START, 3, "23:00", 1000, "b"))
        rep = report(self.ctx, "tiktok", self.as_of())
        self.assertEqual(rep["by_slot"]["europe@22:00"]["metrics"]["views"]["status"], "OK")
        self.assertEqual(rep["by_slot"]["europe@23:00"]["metrics"]["views"], {"n": 3, "status": "UNKNOWN"})
        self.assertIn("completion_rate", rep["by_slot"]["europe@22:00"]["metrics"])
        self.assertIn("engagement_rate", rep["by_slot"]["europe@22:00"]["metrics"])
        self.assertTrue(set(rep["by_jst_weekday"]) <= {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"})
        self.assertFalse(rep["causal_claim"])


class TestSampleGate(Case):
    def gate_for(self, rows):
        self.imp(rows)
        return gate(self.ctx, build_dataset(self.ctx, "tiktok", self.as_of()))

    def test_29_posts_is_unknown(self):
        g = self.gate_for(series("tiktok", START, 29, "22:00", 1000, "a"))
        self.assertEqual((g["status"], g["posts"]), ("UNKNOWN", 29))

    def test_30_posts_on_30_days_is_ready(self):
        g = self.gate_for(series("tiktok", START, 30, "22:00", 1000, "a"))
        self.assertEqual((g["status"], g["posts"]), ("READY", 30))

    def test_13_days_is_unknown_even_with_many_posts(self):
        rows = []
        for hh in ("22:00", "22:30", "23:00"):
            rows += series("tiktok", START + timedelta(days=20), 13, hh, 1000, f"p{hh[:2]}{hh[3:]}")
        g = self.gate_for(rows)
        self.assertEqual((g["status"], g["days"], g["posts"]), ("UNKNOWN", 13, 39))

    def test_14_days_and_30_posts_is_ready(self):
        d0 = START + timedelta(days=20)
        rows = series("tiktok", d0, 14, "22:00", 1000, "a") + series("tiktok", d0, 14, "23:00", 1000, "b") + \
            series("tiktok", d0, 2, "23:30", 1000, "c")
        g = self.gate_for(rows)
        self.assertEqual((g["status"], g["days"], g["posts"]), ("READY", 14, 30))

    def test_stale_data_is_unknown(self):
        self.imp(series("tiktok", START, 30, "22:00", 1000, "a"))
        g = gate(self.ctx, build_dataset(self.ctx, "tiktok", self.pit("2026-09-30T00:00:00+09:00")))
        self.assertEqual(g["status"], "UNKNOWN")
        self.assertIn("stale", " ".join(g["reasons"]))

    def test_floors_cannot_be_loosened(self):
        for over in ({"min_days": 7}, {"min_posts": 10}, {"max_exploration": 0.3}):
            with self.assertRaises(ValidationError, msg=over):
                load_config(overrides={"optimizer": over})


# ------------------------------------------------------------------ proposals

class TestProposals(Case):
    def strong(self):
        """Fixed slot europe@22:00 ~1000 views; europe@23:00 ~3000 views, same completion."""
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START + timedelta(days=5), 20,
                                                                          "23:00", 3000, "b"))

    def test_unknown_generates_no_proposal(self):
        self.imp(series("tiktok", START, 10, "22:00", 1000, "a"))
        res = propose(self.ctx, "tiktok", self.as_of())
        self.assertEqual((res["status"], res["recommended_slot"], res["exploration"], res["proposal_id"]),
                         ("UNKNOWN", None, {}, None))
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM slot_proposals").fetchone()[0], 0)
        self.assertEqual(self.ctx.conn.execute(
            "SELECT action FROM audit_log WHERE entity_type='slot_proposal'").fetchone()[0], "proposal_withheld")

    def test_baseline_without_data_is_unknown(self):
        self.imp(series("tiktok", START, 30, "23:00", 1000, "b"))
        self.assertEqual(evaluate(self.ctx, "tiktok", self.as_of())["status"], "UNKNOWN")

    def test_only_baseline_data_confirms_baseline_with_bounded_exploration(self):
        self.imp(series("tiktok", START, 30, "22:00", 1000, "a"))
        res = propose(self.ctx, "tiktok", self.as_of())
        self.assertEqual(res["status"], "BASELINE_CONFIRMED")
        self.assertIsNone(res["recommended_slot"])
        self.assertLessEqual(sum(res["exploration"].values()), 0.2)
        self.assertTrue(set(res["exploration"]) <= set(res["allowed_slots"]) - {"europe@22:00"})
        self.assertEqual(len(res["exploration"]), 7)

    def test_clear_winner_is_proposed_with_full_record(self):
        self.strong()
        res = propose(self.ctx, "tiktok", self.as_of())
        self.assertEqual((res["status"], res["recommended_slot"]), ("PROPOSED", "europe@23:00"))
        self.assertFalse(res["applies_automatically"])
        self.assertFalse(res["causal_claim"])
        self.assertEqual(res["algorithm_version"], "slot_ts_normal.v1")
        self.assertEqual(len(res["input_sha256"]), 64)
        self.assertEqual((res["data"]["posts"], res["data"]["days"]), (40, 25))
        self.assertTrue(res["data"]["first_published_utc"] and res["data"]["last_published_utc"])
        self.assertGreaterEqual(res["decision"]["p_best"], 0.9)
        self.assertTrue(all(g["ok"] for g in res["decision"]["guardrails"]))
        self.assertLessEqual(sum(res["exploration"].values()), 0.2)
        self.assertNotIn("europe@23:00", res["exploration"])
        self.assertTrue(set(res["exploration"]) <= set(res["allowed_slots"]))
        self.assertIn(res["recommended_slot"], res["allowed_slots"])
        stored = load_proposal(self.ctx, res["proposal_id"])
        self.assertEqual(stored["proposal_sha256"], res["proposal_sha256"])

    def test_guardrail_failure_is_inconclusive(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a", completion=0.6)
                 + series("tiktok", START + timedelta(days=5), 20, "23:00", 3000, "b", completion=0.3))
        res = evaluate(self.ctx, "tiktok", self.as_of())
        self.assertEqual(res["status"], "INCONCLUSIVE")
        self.assertEqual(res["exploration"], {})
        self.assertIsNone(res["recommended_slot"])

    def test_missing_guardrail_metric_is_inconclusive(self):
        rows = series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START + timedelta(days=5), 20,
                                                                          "23:00", 3000, "b")
        for r in rows:
            r["completion_rate"] = ""
        self.imp(rows)
        res = evaluate(self.ctx, "tiktok", self.as_of())
        self.assertEqual(res["status"], "INCONCLUSIVE")
        self.assertEqual(res["decision"]["guardrails"][0]["status"], "UNKNOWN")

    def test_tie_is_never_proposed(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START + timedelta(days=5), 20,
                                                                          "23:00", 1000, "b"))
        self.assertIn(evaluate(self.ctx, "tiktok", self.as_of())["status"], {"INCONCLUSIVE", "BASELINE_CONFIRMED"})

    def test_same_input_same_proposal(self):
        self.strong()
        a, b = evaluate(self.ctx, "tiktok", self.as_of()), evaluate(self.ctx, "tiktok", self.as_of())
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        p1 = propose(self.ctx, "tiktok", self.as_of())
        p2 = propose(self.ctx, "tiktok", self.as_of())
        self.assertEqual((p2["noop"], p2["proposal_id"], p2["proposal_sha256"]),
                         (True, p1["proposal_id"], p1["proposal_sha256"]))

    def test_independent_databases_give_identical_proposals(self):
        rows = series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START + timedelta(days=5), 20,
                                                                          "23:00", 3000, "b")
        shas = []
        for name in ("one", "two"):
            ctx = make_ctx(self.root / name, IMPORT_AT)
            try:
                import_csv(ctx, "tiktok", write_csv(self.root / f"{name}.csv", rows))
                ctx.clock.set(parse_aware(EVAL_AT))
                shas.append(propose(ctx, "tiktok", parse_aware(AS_OF))["proposal_sha256"])
            finally:
                ctx.conn.close()
        self.assertEqual(shas[0], shas[1])

    def test_later_data_never_changes_a_past_proposal(self):
        self.strong()
        first = propose(self.ctx, "tiktok", self.as_of())
        # new data arrives later, including posts published *before* the proposal date
        self.imp(series("tiktok", START + timedelta(days=2), 20, "22:30", 9000, "late"),
                 at="2026-09-01T12:00:00+09:00")
        again = propose(self.ctx, "tiktok", self.as_of())                   # re-run for the same as_of
        self.assertEqual((again["proposal_sha256"], again["noop"]), (first["proposal_sha256"], True))
        now = evaluate(self.ctx, "tiktok", self.pit("2026-09-01T12:00:00+09:00"))
        self.assertNotEqual(now["input_sha256"], first["input_sha256"])      # the new knowledge is used only later

    def test_proposals_are_immutable(self):
        self.strong()
        propose(self.ctx, "tiktok", self.as_of())
        with self.assertRaises(sqlite3.IntegrityError):
            self.ctx.conn.execute("UPDATE slot_proposals SET status='PROPOSED'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.ctx.conn.execute("DELETE FROM slot_proposals")


class TestPointInTimeM2(Case):
    """M2: as_of must be strictly in the past; one proposal per (platform, as_of, algorithm), never rewritten."""

    def strong(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START + timedelta(days=5), 20,
                                                                          "23:00", 3000, "b"))

    def test_future_or_current_as_of_is_refused_everywhere(self):
        self.strong()
        self.ctx.clock.set(parse_aware(EVAL_AT))
        future = parse_aware("2026-08-16T00:00:00+09:00")
        now = self.ctx.clock.now()
        for fn in (lambda t: report(self.ctx, "tiktok", t), lambda t: evaluate(self.ctx, "tiktok", t),
                   lambda t: propose(self.ctx, "tiktok", t), lambda t: build_dataset(self.ctx, "tiktok", t)):
            for t in (future, now, now + timedelta(milliseconds=400)):
                with self.assertRaises(ValidationError) as cm:
                    fn(t)
                self.assertEqual(cm.exception.code, "AS_OF_NOT_IN_PAST")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM slot_proposals").fetchone()[0], 0)
        p = propose(self.ctx, "tiktok", parse_aware(AS_OF))
        with self.assertRaises(ValidationError) as cm:
            shadow(self.ctx, p["proposal_id"], future)
        self.assertEqual(cm.exception.code, "AS_OF_NOT_IN_PAST")

    def test_default_as_of_is_the_previous_second(self):
        from auto_publish.app.metrics.dataset import parse_as_of
        self.ctx.clock.set(parse_aware("2026-08-15T13:00:00.700000+09:00"))
        self.assertEqual(parse_as_of(None, self.ctx), parse_aware("2026-08-15T12:59:59+09:00"))

    def test_import_after_proposal_cannot_change_it(self):
        self.strong()
        self.ctx.clock.set(parse_aware(EVAL_AT))
        first = propose(self.ctx, "tiktok", parse_aware(AS_OF))
        # new data arrives in the very same second as the evaluation, incl. posts published before as_of
        self.imp(series("tiktok", START + timedelta(days=2), 20, "22:30", 9000, "late"))
        known = self.ctx.conn.execute("SELECT MAX(known_at_utc) FROM post_metrics").fetchone()[0]
        self.assertGreater(known, first["as_of_utc"])
        again = propose(self.ctx, "tiktok", parse_aware(AS_OF))
        self.assertEqual((again["noop"], again["proposal_id"], again["proposal_sha256"], again["input_sha256"]),
                         (True, first["proposal_id"], first["proposal_sha256"], first["input_sha256"]))
        self.assertEqual(load_proposal(self.ctx, first["proposal_id"])["proposal_sha256"], first["proposal_sha256"])

    def test_conflicting_reevaluation_for_same_as_of_is_refused_not_stored(self):
        self.strong()
        self.ctx.clock.set(parse_aware(EVAL_AT))
        first = propose(self.ctx, "tiktok", parse_aware(AS_OF))
        # knowledge time forged into the past (possible only with an injected clock) -> different input
        self.imp(series("tiktok", START + timedelta(days=2), 10, "22:30", 9000, "forged"), at=IMPORT_AT)
        self.ctx.clock.set(parse_aware(EVAL_AT))
        with self.assertRaises(ValidationError) as cm:
            propose(self.ctx, "tiktok", parse_aware(AS_OF))
        self.assertEqual(cm.exception.code, "PROPOSAL_AS_OF_CONFLICT")
        self.ctx.cfg["optimizer"]["min_arm_samples"] = 6            # a changed config is a different input too
        with self.assertRaises(ValidationError):
            propose(self.ctx, "tiktok", parse_aware(AS_OF))
        rows = self.ctx.conn.execute("SELECT proposal_id, proposal_sha256 FROM slot_proposals").fetchall()
        self.assertEqual([tuple(r) for r in rows], [(first["proposal_id"], first["proposal_sha256"])])

    def test_db_allows_one_proposal_per_platform_as_of(self):
        self.strong()
        self.ctx.clock.set(parse_aware(EVAL_AT))
        p = propose(self.ctx, "tiktok", parse_aware(AS_OF))
        with self.assertRaises(sqlite3.IntegrityError):
            self.ctx.conn.execute(
                "INSERT INTO slot_proposals(platform, as_of_utc, status, algorithm_version, input_sha256, proposal_json,"
                " proposal_sha256, created_at_utc) VALUES ('tiktok', ?, 'INCONCLUSIVE', 'slot_ts_normal.v1', 'x', '{}',"
                " 'y', 'z')", (p["as_of_utc"],))


class TestShadow(Case):
    def test_fixed_vs_proposed_after_the_proposal(self):
        self.imp(series("tiktok", START, 20, "22:00", 1000, "a") + series("tiktok", START + timedelta(days=5), 20,
                                                                          "23:00", 3000, "b"))
        p = propose(self.ctx, "tiktok", self.as_of())
        with self.assertRaises(ValidationError):
            shadow(self.ctx, p["proposal_id"], self.as_of())                 # empty window
        later = START + timedelta(days=46)                                    # after the proposal's as_of
        self.imp(series("tiktok", later, 6, "22:00", 1100, "fa") + series("tiktok", later, 2, "23:00", 2500, "fb"),
                 at="2026-08-25T00:00:00+09:00")
        s1 = shadow(self.ctx, p["proposal_id"], self.pit("2026-08-25T00:00:00+09:00"))
        self.assertEqual(s1["fixed"]["posts"], 6)
        self.assertEqual(s1["comparisons"][0]["proposed"]["posts"], 2)
        self.assertEqual(s1["comparisons"][0]["by_metric"]["views"]["status"], "UNKNOWN")   # 2 < 5 samples
        self.imp(series("tiktok", later + timedelta(days=6), 4, "23:00", 2500, "fc"), at="2026-09-02T00:00:00+09:00")
        s2 = shadow(self.ctx, p["proposal_id"], self.pit("2026-09-02T00:00:00+09:00"))
        v = s2["comparisons"][0]["by_metric"]["views"]
        self.assertEqual(v["status"], "OK")
        self.assertGreater(v["proposed_minus_fixed_mean"], 0)
        self.assertIn("completion_rate", s2["comparisons"][0]["by_metric"])
        self.assertFalse(s2["causal_claim"])
        again = shadow(self.ctx, p["proposal_id"], self.pit("2026-09-02T00:00:00+09:00"))
        self.assertEqual((again["noop"], again["result_sha256"]), (True, s2["result_sha256"]))
        self.assertEqual(s1["window"]["posts"], 8)                           # the earlier evaluation is kept
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM shadow_evaluations").fetchone()[0], 2)


class TestNeverChangesSchedules(unittest.TestCase):
    def test_scheduler_and_pipeline_do_not_read_optimizer_output(self):
        for rel in ("app/pipeline.py", "app/scheduler/slots.py", "app/dispatch/simulator.py",
                    "app/publishers/dry_run.py"):
            src = (PKG / rel).read_text(encoding="utf-8")
            import re
            self.assertIsNone(re.search(r"from \.+metrics|app\.metrics|import optimizer|slot_proposals|"
                                        r"post_metrics|propose\(", src), rel)

    def test_proposal_does_not_move_the_scheduled_slot(self):
        from auto_publish.app.pipeline import approve, build_drafts, schedule
        from auto_publish.app.ingest.ingest import ingest, validate
        from auto_publish.tests.helpers import SESSION, FakeRenderer, copy_fixture
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ctx = make_ctx(root, IMPORT_AT)
            try:
                import_csv(ctx, "tiktok", write_csv(root / "m.csv", series("tiktok", START, 20, "22:00", 1000, "a")
                                                     + series("tiktok", START + timedelta(days=5), 20, "23:00", 3000, "b")))
                ctx.clock.set(parse_aware(EVAL_AT))
                self.assertEqual(propose(ctx, "tiktok", parse_aware(AS_OF))["recommended_slot"],
                                 "europe@23:00")
                ctx.clock.set(parse_aware("2026-09-24T17:00:00+09:00"))
                ingest(ctx, copy_fixture(root))
                validate(ctx, SESSION)
                sid = build_drafts(ctx, SESSION, FakeRenderer())[0]["story_id"]
                approve(ctx, sid, "yusuke")
                tik = [s for s in schedule(ctx, sid)["schedules"] if s["platform"] == "tiktok"][0]
                self.assertEqual(tik["publish_at_jst"], "2026-09-24T22:00:00+09:00")      # fixed slot kept
            finally:
                ctx.conn.close()
                for dp, _d, fs in os.walk(root):
                    for f in fs:
                        os.chmod(os.path.join(dp, f), 0o644)


class TestCli(unittest.TestCase):
    def test_cli_flow(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d)
            p = write_csv(root / "tiktok_export.csv", series("tiktok", START, 30, "22:00", 1000, "a"))
            env = {**os.environ, "AUTO_PUBLISH_HOME": str(root / "home"), "PYTHONPATH": str(REPO)}

            def cli(*args, expect=0, now=AS_OF):
                out = subprocess.run([sys.executable, "-m", "auto_publish.cli", *(["--now", now] if now else []),
                                      *args],
                                     capture_output=True, text=True, encoding="utf-8", env=env, cwd=REPO, timeout=300)
                self.assertEqual(out.returncode, expect, out.stdout + out.stderr)
                return json.loads(out.stdout)
            cli("sandbox-init", now=None)
            self.assertEqual(cli("metrics-import", "--platform", "tiktok", "--csv", str(p), now=IMPORT_AT)
                             ["result"]["rows_new"], 30)
            self.assertEqual(cli("metrics-report", "--platform", "tiktok")["result"]["gate"]["status"], "READY")
            self.assertEqual(cli("propose-slots", "--platform", "tiktok")["result"]["status"], "BASELINE_CONFIRMED")
            self.assertEqual(len(cli("proposals")["result"]["proposals"]), 1)
            self.assertEqual(cli("metrics-import", "--platform", "x", "--csv", str(p), expect=2)["error"]["code"],
                             "METRICS_CSV_INVALID")
            for dp, _d, fs in os.walk(root):
                for f in fs:
                    os.chmod(os.path.join(dp, f), 0o644)


if __name__ == "__main__":
    unittest.main()
