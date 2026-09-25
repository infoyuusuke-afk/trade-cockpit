"""Opportunity Radar condition_log.csv importer + synthetic end-to-end.

Fixture ``fixtures/cockpit_synthetic/2026-09-24`` is SYNTHETIC (tickers TST1-TST4),
in the exact on-disk format of the MS2 collector (UTF-8 BOM, quoted values).
Real and synthetic inputs can never be mixed in one export (DATA_CLASS_MIXED).
"""
import hashlib
import json
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from auto_publish.app.errors import EvidenceError, ValidationError
from auto_publish.app.explain import explain
from auto_publish.app.export import radar_import as ri
from auto_publish.app.export.cockpit_export import export_session
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.pipeline import approve, build_drafts, schedule, story_dir
from auto_publish.tests.helpers import TESTS_DIR, FakeRenderer, make_ctx

SYN = TESTS_DIR / "fixtures" / "cockpit_synthetic" / "2026-09-24"
REAL = TESTS_DIR / "fixtures" / "cockpit_export" / "2026-09-25"
SESSION = "2026-09-24"
NOW = "2026-09-24T21:30:00+09:00"
INTERNAL_KEYS = {"ema9", "ema20", "flow_bias", "bar_burst", "or5_high", "or5_low", "or15_high", "or15_low",
                 "whipsaw", "chase_guard", "strategy", "signal", "trend_long", "trend_short"}
INTERNAL_VALUES = ["初動買い候補", "空売りサイン", "押し目待ち", "買いサイン"]


def _keys(obj) -> set:
    if isinstance(obj, dict):
        return set(obj) | set().union(*(_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_keys(v) for v in obj)) if obj else set()
    return set()


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ap_radar_", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.inp = self.root / "ms2_day"          # stands in for an arbitrary local path
        shutil.copytree(SYN, self.inp)
        self.csv = self.inp / "condition_log.csv"
        self.out = self.root / "content_drop"

    def tearDown(self):
        for dp, _d, fs in os.walk(self.root):
            for f in fs:
                try:
                    os.chmod(os.path.join(dp, f), 0o644)
                except OSError:
                    pass
        self._tmp.cleanup()

    def parse(self):
        return ri.parse_condition_log(self.csv.read_bytes(), SESSION)

    def lines(self):
        return self.csv.read_bytes().decode("utf-8-sig").split("\r\n")

    def write_lines(self, lines):
        self.csv.write_bytes(("﻿" + "\r\n".join(lines)).encode("utf-8"))

    def export(self, **kw):
        return export_session(SESSION, self.inp / "data.json", self.inp / "paper_trade_history.json", self.out,
                              condition_log=self.csv, data_class="fixture", **kw)


class TestParse(Base):
    def test_events_are_first_occurrence_and_deduplicated(self):
        r = self.parse()
        self.assertEqual((r["rows"], r["duplicate_rows"]), (10, 1))
        got = [(e["ticker"], e["time_jst"], e["event"], e["direction"]) for e in r["public"]]
        self.assertEqual(got, [("TST1.T", "09:07", "or5_breakout", "up"),
                               ("TST1.T", "09:16", "or15_breakout", "up"),
                               ("TST2.T", "09:18", "or15_breakdown", "down"),
                               ("TST3.T", "09:30", "or15_breakout", "up"),
                               ("TST1.T", "10:05", "or15_retest_hold", "up")])
        self.assertEqual(len({e["event_id"] for e in r["public"]}), 5)

    def test_event_ids_are_stable(self):
        a = [e["event_id"] for e in self.parse()["public"]]
        b = [e["event_id"] for e in self.parse()["public"]]
        self.assertEqual(a, b)
        self.assertTrue(all(i.startswith("rv_") and len(i) == 19 for i in a))

    def test_public_and_internal_are_separated(self):
        r = self.parse()
        for e in r["public"]:
            self.assertLessEqual(set(e), ri.PUBLIC_EVENT_KEYS)
            self.assertEqual(_keys(e) & INTERNAL_KEYS, set())
            self.assertNotIn("vwap", e)  # only the relation is public
        for i in r["internal"]:
            self.assertEqual(i["visibility"], "internal")
            self.assertEqual(set(i["values"]), set(ri.INTERNAL_FIELDS))

    def test_source_ref_traces_to_exact_csv_row_and_file_hash(self):
        raw = self.csv.read_bytes()
        lines = raw.decode("utf-8-sig").splitlines()
        for e in self.parse()["public"]:
            ref = e["source_ref"]
            self.assertEqual(ref["sha256"], hashlib.sha256(raw).hexdigest())
            line = lines[ref["row"] - 1]
            self.assertEqual(ref["row_sha256"], hashlib.sha256(line.encode()).hexdigest())
            cells = next(__import__("csv").reader([line]))
            row = dict(zip(ri.EXPECTED_HEADER, cells))
            self.assertEqual((row["ticker"], row[ref["flag"]]), (e["ticker"], "True"))

    def test_append_only_growth_is_tolerated_but_rewrite_is_not(self):
        snap = self.csv.read_bytes()
        with open(self.csv, "ab") as fh:
            fh.write(b'"2026-09-24 15:45:00","TST1.T","x","1","1","1","1","False","False","1","1","1","1","1","0",'
                     b'"False","False","False","False","False","False","False","False","","\r\n')
        ri.verify_prefix_unchanged(self.csv, snap)  # appended rows after our snapshot: fine
        self.csv.write_bytes(snap.replace(b"2290", b"2999"))
        with self.assertRaises(EvidenceError) as cm:
            ri.verify_prefix_unchanged(self.csv, snap)
        self.assertEqual(cm.exception.code, "EVIDENCE_CHANGED_DURING_INGEST")


class TestParseFailClosed(Base):
    def expect(self, code):
        with self.assertRaises(ValidationError) as cm:
            self.parse()
        self.assertEqual(cm.exception.code, code)

    def mutate_row(self, idx, col, value):
        lines = self.lines()
        header = lines[0].split(",")
        cells = [c.strip('"') for c in lines[idx].split('","')]
        cells[header.index(col)] = value
        lines[idx] = ",".join(f'"{c}"' for c in cells)
        self.write_lines(lines)

    def test_header_change(self):
        lines = self.lines()
        lines[0] = lines[0].replace(",strategy", ",strategy_v2")
        self.write_lines(lines)
        self.expect("SCHEMA_INVALID")

    def test_row_from_another_date(self):
        self.mutate_row(3, "captured_at", "2026-09-23 09:07:10")
        self.expect("DATE_MISMATCH")

    def test_time_going_backwards(self):
        self.mutate_row(6, "captured_at", "2026-09-24 09:01:00")
        self.expect("LOG_NOT_MONOTONIC")

    def test_bad_timestamp(self):
        self.mutate_row(3, "captured_at", "2026-09-24 25:07:10")
        self.expect("SCHEMA_INVALID")

    def test_bad_ticker(self):
        self.mutate_row(3, "ticker", "TST1")
        self.expect("SCHEMA_INVALID")

    def test_bad_boolean(self):
        self.mutate_row(3, "or5_long", "yes")
        self.expect("INVALID_VALUE")

    def test_non_finite_number(self):
        self.mutate_row(3, "price", "NaN")
        self.expect("INVALID_VALUE")

    def test_flag_outside_session(self):
        self.mutate_row(10, "or15_long", "True")
        self.expect("INVALID_VALUE")

    def test_direction_contradicts_vwap(self):
        self.mutate_row(3, "vwap", "2999")  # or5_long but price below VWAP
        self.expect("INVALID_VALUE")

    def test_column_count(self):
        lines = self.lines()
        lines[3] = lines[3] + ',"extra"'
        self.write_lines(lines)
        self.expect("SCHEMA_INVALID")

    def test_empty_and_non_utf8(self):
        self.csv.write_bytes(b"")
        self.expect("SCHEMA_INVALID")
        self.csv.write_bytes("captured_at".encode("utf-16"))
        self.expect("SCHEMA_INVALID")


class TestExportWithRadar(Base):
    def test_export_adds_public_events_and_internal_file(self):
        res = self.export()
        self.assertEqual(res["radar_events"], 4)  # TST3 excluded: quote not verified
        d = self.out / SESSION
        summary = json.loads((d / "daily_summary.json").read_text(encoding="utf-8"))
        self.assertEqual((summary["source"], summary["data_class"]), ("TEST_FIXTURE", "fixture"))
        self.assertEqual(_keys(summary) & INTERNAL_KEYS, set())
        text = (d / "daily_summary.json").read_text(encoding="utf-8")
        for v in INTERNAL_VALUES:
            self.assertNotIn(v, text)
        internal = json.loads((d / "internal" / "radar_internal.json").read_text(encoding="utf-8"))
        self.assertEqual(internal["visibility"], "internal")
        self.assertEqual({e["event_id"] for e in internal["events"]},
                         {e["event_id"] for e in summary["radar_events"]})
        manifest = json.loads((d / "export_manifest.json").read_text(encoding="utf-8"))
        csv_in = next(i for i in manifest["inputs"] if i["file"] == "condition_log.csv")
        self.assertEqual(csv_in["sha256"], hashlib.sha256(self.csv.read_bytes()).hexdigest())
        excl = [r for r in manifest["excluded_records"] if r["kind"] == "radar_event"]
        self.assertEqual([(r["ticker"], r["reason"]) for r in excl], [("TST3.T", "no verified quote for this ticker")])

    def test_inputs_untouched_and_reexport_idempotent(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.inp.iterdir()}
        self.assertFalse(self.export()["noop"])
        self.assertTrue(self.export()["noop"])
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.inp.iterdir()}
        self.assertEqual(before, after)

    def test_fixture_and_real_never_mix(self):
        # synthetic radar log against the REAL data.json
        with self.assertRaises(ValidationError) as cm:
            export_session("2026-09-25", REAL / "data.json", REAL / "paper_trade_history.json", self.out,
                           condition_log=self.csv)
        self.assertIn(cm.exception.code, {"DATE_MISMATCH", "DATA_CLASS_MIXED"})
        # synthetic snapshot exported as if it were real
        with self.assertRaises(ValidationError) as cm:
            export_session(SESSION, self.inp / "data.json", self.inp / "paper_trade_history.json", self.out,
                           condition_log=self.csv, data_class="real")
        self.assertEqual(cm.exception.code, "DATA_CLASS_MIXED")


class TestRadarEndToEnd(Base):
    def run_all(self):
        self.export()
        ctx = make_ctx(self.root, NOW)
        self.addCleanup(ctx.conn.close)
        ingest(ctx, self.out / SESSION)
        self.assertTrue(validate(ctx, SESSION)["fixture"])
        results = build_drafts(ctx, SESSION, FakeRenderer())
        for r in results:
            self.assertEqual(r["state"], "AWAITING_APPROVAL", r)
            approve(ctx, r["story_id"], "yusuke")
            schedule(ctx, r["story_id"])
        return ctx, results

    def test_radar_bullet_flows_to_dry_run_without_internal_data(self):
        def boom(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(socket, "getaddrinfo", boom):
            ctx, results = self.run_all()
        topics = {}
        for r in results:
            sdir = story_dir(ctx, {"story_id": r["story_id"], "session_date": SESSION})
            post = json.loads((sdir / "post_en.json").read_text(encoding="utf-8"))
            topics[post["story_id"]] = [s["text"] for s in post["segments"]]
            for f in sdir.rglob("*"):
                if f.is_file() and f.suffix in {".json", ".srt", ".txt"}:
                    txt = f.read_text(encoding="utf-8")
                    for v in INTERNAL_VALUES:
                        self.assertNotIn(v, txt, f"internal value leaked into {f.name}")
                    if f.suffix == ".json":
                        self.assertEqual(_keys(json.loads(txt)) & INTERNAL_KEYS, set(), f.name)
        all_text = " ".join(t for ts in topics.values() for t in ts)
        self.assertIn("At 09:07 JST, the radar flagged a break above the 5-minute opening range, with price above VWAP.",
                      all_text)
        self.assertIn("a break below the 15-minute opening range, with price below VWAP", all_text)
        self.assertIn("TEST FIXTURE", all_text)

    def test_explain_traces_event_id_to_csv_hash_and_internal_record(self):
        ctx, results = self.run_all()
        csv_sha = hashlib.sha256(self.csv.read_bytes()).hexdigest()
        found = False
        for r in results:
            ex = explain(ctx, r["story_id"])
            self.assertIn("breakdown", ex["why_selected"])
            self.assertIn(r["story_id"], ex["why_selected"]["session_selection"]["selected"])
            for seg in ex["segments"]:
                for f in seg["facts"]:
                    self.assertEqual(len(f["content_drop"]["sha256"]), 64)
                    if f["kind"] == "radar_event":
                        found = True
                        self.assertTrue(f["event_id"].startswith("rv_"))
                        self.assertEqual(f["original_source"]["file"], "condition_log.csv")
                        self.assertEqual(f["original_source"]["sha256"], csv_sha)
                        rec = f["INTERNAL_never_published"]
                        self.assertEqual(rec["event_id"], f["event_id"])
                        self.assertEqual(rec["row"], f["original_source"]["row"])
                        self.assertIn("flow_bias", rec["values"])
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
