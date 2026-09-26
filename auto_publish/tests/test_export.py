"""Read-only exporter: AI Cockpit exports -> daily_summary.v1, and the real-data E2E.

Fixture ``fixtures/cockpit_export/2026-09-25`` is REAL data (a trimmed copy of files
already public in this repository, see PROVENANCE.json) -- not synthetic.
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
from auto_publish.app.evidence.store import resolve_pointer
from auto_publish.app.export.cockpit_export import DENY_KEYS, _deny_scan, build_export, export_session
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.pipeline import approve, build_drafts, schedule, story_dir
from auto_publish.tests.helpers import TESTS_DIR, FakeRenderer, make_ctx

REAL_SRC = TESTS_DIR / "fixtures" / "cockpit_export" / "2026-09-25"
SESSION = "2026-09-25"
NOW = "2026-09-25T21:30:00+09:00"
SENSITIVE = ["pnl_yen", "shares", "fees", "slippage", "simulated_fill", "turnover", "strategy_id", "stop",
             "target1", "entry_limit", "MFE", "MAE", "secondary_source", "quote_status", "market_supply_score"]


def _keys(obj) -> set:
    """All object keys at any depth (values are not keys)."""
    if isinstance(obj, dict):
        return set(obj) | set().union(*(_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_keys(v) for v in obj)) if obj else set()
    return set()


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class ExportCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ap_export_", ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.inputs = self.root / "cockpit"
        shutil.copytree(REAL_SRC, self.inputs)
        self.data = self.inputs / "data.json"
        self.paper = self.inputs / "paper_trade_history.json"
        self.out = self.root / "content_drop"

    def tearDown(self):
        for dp, _d, fs in os.walk(self.root):
            for f in fs:
                try:
                    os.chmod(os.path.join(dp, f), 0o644)
                except OSError:
                    pass
        self._tmp.cleanup()

    def export(self):
        return export_session(SESSION, self.data, self.paper, self.out)

    def edit(self, path: Path, fn):
        doc = json.loads(path.read_text(encoding="utf-8"))
        fn(doc)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def expect(self, code, exc=ValidationError):
        with self.assertRaises(exc) as cm:
            self.export()
        self.assertEqual(cm.exception.code, code)
        self.assertFalse((self.out / SESSION).exists(), "nothing may be written on failure")


class TestAllowlistAndProvenance(ExportCase):
    def test_export_writes_summary_trades_and_manifest(self):
        res = self.export()
        self.assertFalse(res["noop"])
        d = self.out / SESSION
        self.assertEqual(sorted(p.name for p in d.iterdir()),
                         ["daily_summary.json", "export_manifest.json", "paper_trade_history.json"])
        summary = json.loads((d / "daily_summary.json").read_text(encoding="utf-8"))
        self.assertEqual((summary["source"], summary["data_class"]), ("ai_cockpit_export", "real"))
        self.assertEqual(summary["generated_at"], "2026-09-25T21:03:29+09:00")
        self.assertEqual({m["ticker"] for m in summary["movers"]},
                         {"6861.T", "6481.T", "6504.T", "285A.T", "6594.T", "8035.T"})

    def test_only_allowlisted_fields_and_no_sensitive_fields(self):
        self.export()
        d = self.out / SESSION
        for name in ("daily_summary.json", "paper_trade_history.json"):
            doc = json.loads((d / name).read_text(encoding="utf-8"))
            leaked = _keys(doc) & set(SENSITIVE)
            self.assertEqual(leaked, set(), f"leaked into {name}")
            self.assertEqual(_deny_scan(doc), [])
        summary = json.loads((d / "daily_summary.json").read_text(encoding="utf-8"))
        for m in summary["movers"]:
            self.assertLessEqual(set(m), {"ticker", "name_en", "name_ja", "name_en_source", "close", "change_pct",
                                          "volume_ratio", "source_ref"})
        manifest = json.loads((d / "export_manifest.json").read_text(encoding="utf-8"))
        dropped = manifest["dropped_fields"]
        for key in ("pnl_yen", "shares", "fees", "slippage", "strategy_id", "MFE"):
            self.assertIn(key, dropped["paper_trade_history.json/*"])
        for key in ("turnover", "secondary_source", "quote_status", "chart"):
            self.assertIn(key, dropped["data.json/stocks/*"])

    def test_deny_scan_catches_leaks(self):
        self.assertEqual(_deny_scan({"a": [{"x": 1, "PNL_YEN": 2}]}), ["/a/0/PNL_YEN"])
        self.assertIn("shares", DENY_KEYS)

    def test_inputs_are_never_modified(self):
        before = {p.name: (_sha(p), p.stat().st_mtime_ns) for p in self.inputs.iterdir()}
        self.export()
        self.export()  # idempotent second run
        after = {p.name: (_sha(p), p.stat().st_mtime_ns) for p in self.inputs.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual(sorted(p.name for p in self.inputs.iterdir()), ["data.json", "paper_trade_history.json"])

    def test_every_record_traces_to_original_bytes(self):
        self.export()
        d = self.out / SESSION
        summary = json.loads((d / "daily_summary.json").read_text(encoding="utf-8"))
        trades = json.loads((d / "paper_trade_history.json").read_text(encoding="utf-8"))
        manifest = json.loads((d / "export_manifest.json").read_text(encoding="utf-8"))
        originals = {"data.json": self.data, "paper_trade_history.json": self.paper}
        for inp in manifest["inputs"]:
            self.assertEqual(inp["sha256"], _sha(originals[inp["file"]]))
        for m in summary["movers"]:
            ref = m["source_ref"]
            self.assertEqual(ref["sha256"], _sha(originals[ref["file"]]))
            src = resolve_pointer(json.loads(originals[ref["file"]].read_text(encoding="utf-8")), ref["pointer"])
            self.assertEqual(m["close"], src["price"])
            self.assertEqual(m["change_pct"], src["change_pct"])
            if "volume_ratio" in m:
                self.assertEqual(m["volume_ratio"], src["rvol"])
            self.assertEqual(src["ticker"], m["ticker"])
        for t in trades:
            ref = t["source_ref"]
            self.assertEqual(ref["sha256"], _sha(self.paper))
            src = resolve_pointer(json.loads(self.paper.read_text(encoding="utf-8")), ref["pointer"])
            self.assertEqual((src["ticker"], src["date"], src["entry"]), (t["ticker"], t["date"], t["entry"]))
            if t["closed"]:
                self.assertEqual(src["r"], t["r"])
        self.assertEqual(manifest["outputs"]["daily_summary.json"], _sha(d / "daily_summary.json"))

    def test_open_trades_carry_no_result_and_closed_trades_do(self):
        self.export()
        trades = {t["ticker"]: t for t in json.loads(
            (self.out / SESSION / "paper_trade_history.json").read_text(encoding="utf-8"))}
        self.assertEqual((trades["6504.T"]["closed"], trades["6504.T"]["outcome"], trades["6504.T"]["r"]),
                         (True, "target1", 1.52))
        self.assertEqual((trades["285A.T"]["closed"], trades["285A.T"]["outcome"], trades["285A.T"]["r"]),
                         (False, "open_mark", None))
        self.assertTrue(all(t["basis"] == "paper" for t in trades.values()))

    def test_untriggered_ambiguous_and_unverified_are_excluded_with_reason(self):
        def mark(doc):
            for t in doc:
                if t["result"] == "順序不明（成績除外）":
                    t["date"] = SESSION
                    t["ticker"] = "6504.T"
        self.edit(self.paper, mark)
        self.edit(self.data, lambda d: d["stocks"]["東京エレクトロン（8035）"].update(quote_verified=False))
        self.export()
        manifest = json.loads((self.out / SESSION / "export_manifest.json").read_text(encoding="utf-8"))
        reasons = [(r["kind"], r.get("ticker"), r["reason"]) for r in manifest["excluded_records"]]
        self.assertIn(("paper_trade", "6504.T", "result '順序不明（成績除外）' is not publishable"), reasons)
        self.assertIn(("stock", "8035.T", "quote or identity not verified"), reasons)
        self.assertTrue(any(k == "stock" and "ok != true" in why for k, _t, why in reasons))

    def test_reexport_is_idempotent_and_changed_input_is_refused(self):
        self.assertFalse(self.export()["noop"])
        self.assertTrue(self.export()["noop"])
        self.edit(self.data, lambda d: d["stocks"]["THK（6481）"].update(rvol=9.9))
        with self.assertRaises(EvidenceError) as cm:
            self.export()
        self.assertEqual(cm.exception.code, "EXPORT_CHANGED")

    def test_output_may_not_overlap_inputs(self):
        # out_root/<date> must never be the inputs' own directory
        link = self.root / "same"
        link.mkdir()
        (link / SESSION).mkdir()
        shutil.copy(self.data, link / SESSION / "data.json")
        shutil.copy(self.paper, link / SESSION / "paper_trade_history.json")
        with self.assertRaises(ValidationError) as cm:
            export_session(SESSION, link / SESSION / "data.json", link / SESSION / "paper_trade_history.json", link)
        self.assertEqual(cm.exception.code, "OUTPUT_OVERLAPS_INPUT")


class TestFailClosed(ExportCase):
    def test_snapshot_date_mismatch(self):
        # The situation observed on main (data_date one day behind) must never export.
        self.edit(self.data, lambda d: d["stocks"]["THK（6481）"].update(data_date="2026-09-24"))
        self.expect("DATE_MISMATCH")

    def test_no_verified_quotes(self):
        def unverify(d):
            for s in d["stocks"].values():
                s["quote_verified"] = False
        self.edit(self.data, unverify)
        self.expect("NO_VERIFIED_QUOTES")

    def test_stale_and_premature_snapshot(self):
        self.edit(self.data, lambda d: d.update(updated_at="2026-09-26 12:00:00 JST"))
        self.expect("EVIDENCE_STALE")
        self.edit(self.data, lambda d: d.update(updated_at="2026-09-25 11:00:00 JST"))
        self.expect("EVIDENCE_PREMATURE")
        self.edit(self.data, lambda d: d.update(updated_at="2026-09-25T21:03:29"))
        self.expect("SCHEMA_INVALID")

    def test_invalid_numbers(self):
        self.edit(self.data, lambda d: d["stocks"]["THK（6481）"].update(price=-1))
        self.expect("INVALID_VALUE")

    def test_inconsistent_change_pct(self):
        self.edit(self.data, lambda d: d["stocks"]["THK（6481）"].update(change_pct=9.99))
        self.expect("INVALID_VALUE")

    def test_unknown_trade_result(self):
        self.edit(self.paper, lambda d: d[0].update(result="謎の結果"))
        self.expect("UNKNOWN_RESULT")

    def test_triggered_contradiction(self):
        self.edit(self.paper, lambda d: d[0].update(triggered=False))
        self.expect("INVALID_VALUE")

    def test_closed_trade_without_r(self):
        self.edit(self.paper, lambda d: d[0].update(r=None))
        self.expect("INVALID_VALUE")

    def test_unknown_source_and_side(self):
        self.edit(self.paper, lambda d: d[0].update(source="live_account"))
        self.expect("INVALID_VALUE")
        shutil.copy(REAL_SRC / "paper_trade_history.json", self.paper)
        self.edit(self.paper, lambda d: d[0].update(side="BUY"))
        self.expect("INVALID_VALUE")

    def test_missing_or_broken_input(self):
        self.paper.write_text("{not json", encoding="utf-8")
        self.expect("SCHEMA_INVALID")
        self.paper.unlink()
        self.expect("EXPORT_INPUT_MISSING", EvidenceError)

    def test_weekend(self):
        with self.assertRaises(ValidationError) as cm:
            build_export("2026-09-26", self.data, self.paper)
        self.assertEqual(cm.exception.code, "NOT_TRADING_DAY")


class TestRealDataEndToEnd(ExportCase):
    """real export -> daily_summary.v1 -> ingest/validate -> drafts -> approval -> dry-run schedule."""

    def run_pipeline(self, renderer):
        export_session(SESSION, self.data, self.paper, self.out)
        ctx = make_ctx(self.root, NOW)
        self.addCleanup(ctx.conn.close)
        ingest(ctx, self.out / SESSION)
        v = validate(ctx, SESSION)
        self.assertFalse(v["fixture"])
        results = build_drafts(ctx, SESSION, renderer)
        self.assertTrue(results)
        for r in results:
            self.assertEqual(r["state"], "AWAITING_APPROVAL", r)
            approve(ctx, r["story_id"], "yusuke")
            self.assertEqual(schedule(ctx, r["story_id"])["state"], "SCHEDULED")
        return ctx, results

    def test_real_data_dry_run_with_network_disabled(self):
        def boom(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket.socket, "connect", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom):
            ctx, results = self.run_pipeline(FakeRenderer())
        for r in results:
            sdir = story_dir(ctx, {"story_id": r["story_id"], "session_date": SESSION})
            post = json.loads((sdir / "post_en.json").read_text(encoding="utf-8"))
            self.assertFalse(post["fixture"])
            text = " ".join(s["text"] for s in post["segments"])
            self.assertNotIn("TEST FIXTURE", text)
            self.assertIn("Paper trade (simulated, not real money)", text)
            for p in ("x", "tiktok", "youtube_shorts"):
                payload = json.loads((sdir / "dry_run" / f"{p}.json").read_text(encoding="utf-8"))
                self.assertEqual((payload["dry_run"], payload["network"], payload["data_class"]),
                                 (True, "none", "real"))
                self.assertEqual(_keys(payload) & set(SENSITIVE), set())
            # sentence -> fact -> exported record -> ORIGINAL cockpit file bytes
            evidence = json.loads((sdir / "evidence.json").read_text(encoding="utf-8"))
            for ref in evidence["source_refs"]:
                exported = ref["value"]
                orig = exported["source_ref"]
                src_path = self.data if orig["file"] == "data.json" else self.paper
                self.assertEqual(orig["sha256"], _sha(src_path))
                src = resolve_pointer(json.loads(src_path.read_text(encoding="utf-8")), orig["pointer"])
                self.assertEqual(src["ticker"], exported["ticker"])

    def test_open_paper_trade_is_never_described_as_closed(self):
        ctx, results = self.run_pipeline(FakeRenderer())
        for r in results:
            sdir = story_dir(ctx, {"story_id": r["story_id"], "session_date": SESSION})
            story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
            for seg in story["segments"]:
                if seg["type"] == "paper":
                    ref = next(x for x in story["source_refs"] if x["fact_id"] == seg["fact_ids"][0])
                    self.assertEqual(seg["data"]["result_closed"], ref["value"]["closed"])
                    if not ref["value"]["closed"]:
                        self.assertIsNone(seg["data"]["r"])


from auto_publish.tests.test_render_e2e import require_ffmpeg  # noqa: E402


@require_ffmpeg
class TestRealDataRealRender(ExportCase):
    def test_real_data_renders_vertical_master(self):
        from auto_publish.app.render.ffmpeg_render import FfmpegRenderer, probe
        export_session(SESSION, self.data, self.paper, self.out)
        ctx = make_ctx(self.root, NOW, overrides={"render": {"x264_preset": "ultrafast"}, "max_stories_per_session": 1})
        self.addCleanup(ctx.conn.close)
        ingest(ctx, self.out / SESSION)
        validate(ctx, SESSION)
        (res,) = build_drafts(ctx, SESSION, FfmpegRenderer(ctx.cfg))
        self.assertEqual(res["state"], "AWAITING_APPROVAL", res)
        sdir = story_dir(ctx, {"story_id": res["story_id"], "session_date": SESSION})
        pr = probe(sdir / "master_1080x1920.mp4")
        self.assertEqual((pr["width"], pr["height"], pr["video_codec"]), (1080, 1920, "h264"))
        self.assertNotIn("t_fixture.txt", json.loads((sdir / "render_manifest.json").read_text())["inputs"])


if __name__ == "__main__":
    unittest.main()
