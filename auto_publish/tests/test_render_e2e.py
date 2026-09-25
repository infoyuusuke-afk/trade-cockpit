"""Real FFmpeg render, determinism, CLI end-to-end and evidence trace.

FFmpeg is REQUIRED: these tests fail (not skip) when it is missing, unless the
operator explicitly sets AUTO_PUBLISH_ALLOW_NO_FFMPEG=1 (then they are reported
as skipped, never silently passed).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from auto_publish.app.evidence.store import resolve_pointer
from auto_publish.app.pipeline import ARTIFACT_FILES, approve, build_drafts, schedule
from auto_publish.app.render.ffmpeg_render import FfmpegRenderer, build_command, build_srt, probe, timeline
from auto_publish.tests.helpers import GOLDEN_DIR, NOW, SESSION, PipelineCase, copy_fixture

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
ALLOW_MISSING = os.environ.get("AUTO_PUBLISH_ALLOW_NO_FFMPEG") == "1"
FAST = {"render": {"x264_preset": "ultrafast"}, "max_stories_per_session": 1}
REPO = Path(__file__).resolve().parents[2]


def require_ffmpeg(cls):
    """Class decorator. Missing FFmpeg => every test in the class FAILS (never silently
    disappears); explicit opt-out via AUTO_PUBLISH_ALLOW_NO_FFMPEG=1 => reported as skipped."""
    if HAVE_FFMPEG:
        return cls
    if ALLOW_MISSING:
        return unittest.skip("FFmpeg missing and AUTO_PUBLISH_ALLOW_NO_FFMPEG=1")(cls)

    def setUp(self):
        self.fail("FFmpeg/ffprobe not on PATH. Install FFmpeg (see auto_publish/README.md); "
                  "R1 acceptance requires a real render.")

    def tearDown(self):
        pass

    cls.setUp = setUp
    cls.tearDown = tearDown
    return cls


def _post_en():
    return json.loads((GOLDEN_DIR / "TEST1_en-US.json").read_text(encoding="utf-8"))


class TestCommandBuilder(unittest.TestCase):
    """Pure functions: run everywhere, FFmpeg not needed."""

    def test_command_is_deterministic_and_bitexact(self):
        tl = timeline(_post_en(), 6)
        a = build_command(tl, True, width=1080, height=1920, fps=30)
        b = build_command(tl, True, width=1080, height=1920, fps=30)
        self.assertEqual(a, b)
        joined = " ".join(a)
        for flag in ("+bitexact", "-map_metadata -1", "-threads 1", "s=1080x1920", "libx264", "yuv420p"):
            self.assertIn(flag, joined)
        self.assertEqual(tl[-1]["end"], 30)
        self.assertIn("expansion=none", joined)  # text never interpreted by drawtext

    def test_srt_is_built_from_final_script(self):
        post = _post_en()
        srt = build_srt(timeline(post, 6))
        self.assertIn("00:00:24,000 --> 00:00:30,000", srt)
        for seg in post["segments"]:
            self.assertIn(seg["text"].split()[0], srt)


@require_ffmpeg
class TestRealRender(PipelineCase):
    overrides = FAST

    def test_render_produces_valid_vertical_master(self):
        self.ingest_validate()
        (res,) = build_drafts(self.ctx, SESSION, FfmpegRenderer(self.ctx.cfg))
        self.assertEqual(res["state"], "AWAITING_APPROVAL", res)
        sdir = self.ctx.paths.artifacts / SESSION / res["story_id"]
        for name in ARTIFACT_FILES:
            self.assertTrue((sdir / name).is_file(), name)
        pr = probe(sdir / "master_1080x1920.mp4")
        self.assertEqual((pr["width"], pr["height"], pr["video_codec"], pr["audio_codec"]), (1080, 1920, "h264", "aac"))
        self.assertAlmostEqual(pr["duration"], 30.0, delta=0.5)
        manifest = json.loads((sdir / "render_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["outputs"]["master_1080x1920.mp4"]["sha256"],
                         hashlib.sha256((sdir / "master_1080x1920.mp4").read_bytes()).hexdigest())
        self.assertEqual(len(manifest["font"]["sha256"]), 64)
        self.assertFalse((sdir / "render_inputs" / "font.ttf").exists(), "font must not be redistributed")

    def test_render_is_byte_deterministic(self):
        self.ingest_validate()
        (res,) = build_drafts(self.ctx, SESSION, FfmpegRenderer(self.ctx.cfg))
        first = self.ctx.paths.artifacts / SESSION / res["story_id"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as other:
            from auto_publish.tests.helpers import make_ctx
            from auto_publish.app.ingest.ingest import ingest, validate
            root = Path(other)
            ctx2 = make_ctx(root, overrides=FAST)
            ingest(ctx2, copy_fixture(root))
            validate(ctx2, SESSION)
            (res2,) = build_drafts(ctx2, SESSION, FfmpegRenderer(ctx2.cfg))
            second = ctx2.paths.artifacts / SESSION / res2["story_id"]
            self.assertEqual(res["story_id"], res2["story_id"])
            for name in ARTIFACT_FILES:
                self.assertEqual(hashlib.sha256((first / name).read_bytes()).hexdigest(),
                                 hashlib.sha256((second / name).read_bytes()).hexdigest(), name)
            ctx2.conn.close()
            for dp, _d, fs in os.walk(root):
                for f in fs:
                    os.chmod(os.path.join(dp, f), 0o644)

    def test_evidence_trace_from_published_text_to_source_bytes(self):
        """Every sentence -> fact_id -> evidence.json ref -> SHA256 of the ORIGINAL drop file -> value."""
        self.ingest_validate()
        (res,) = build_drafts(self.ctx, SESSION, FfmpegRenderer(self.ctx.cfg))
        sid = res["story_id"]
        approve(self.ctx, sid, "yusuke")
        schedule(self.ctx, sid)
        sdir = self.ctx.paths.artifacts / SESSION / sid
        evidence = json.loads((sdir / "evidence.json").read_text(encoding="utf-8"))
        refs = {r["fact_id"]: r for r in evidence["source_refs"]}
        for fname in ("post_en.json", "post_ja.json"):
            post = json.loads((sdir / fname).read_text(encoding="utf-8"))
            for seg in post["segments"]:
                if seg["type"] == "disclaimer":
                    continue
                self.assertTrue(seg["fact_ids"], seg)
                for fid in seg["fact_ids"]:
                    ref = refs[fid]
                    original = self.drop / ref["rel_path"]
                    self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), ref["sha256"])
                    doc = json.loads(original.read_text(encoding="utf-8"))
                    self.assertEqual(resolve_pointer(doc, ref["pointer"]), ref["value"])
        # the dry-run payload is bound to the exact approved content and evidence manifest
        payload = json.loads((sdir / "dry_run" / "youtube_shorts.json").read_text(encoding="utf-8"))
        session = self.ctx.conn.execute("SELECT manifest_sha256 FROM sessions").fetchone()[0]
        self.assertEqual(payload["evidence_manifest_sha256"], session)
        self.assertEqual(payload["evidence_manifest_sha256"], evidence["evidence_manifest_sha256"])
        story = self.ctx.conn.execute("SELECT approved_content_sha256 FROM stories WHERE story_id=?", (sid,)).fetchone()
        self.assertEqual(payload["content_sha256"], story[0])


@require_ffmpeg
class TestCliEndToEnd(unittest.TestCase):
    """Acceptance: one fixture -> complete artifact directory with drafts + schedule + render manifest."""

    def test_cli_dry_run(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            drop = copy_fixture(root)
            overlay = root / "overlay.json"
            overlay.write_text(json.dumps({"render": {"x264_preset": "ultrafast"}}), encoding="utf-8")
            env = {**os.environ, "AUTO_PUBLISH_HOME": str(root / "home"), "PYTHONPATH": str(REPO)}

            def cli(*args, expect=0):
                out = subprocess.run([sys.executable, "-m", "auto_publish.cli", "--config", str(overlay),
                                      "--now", NOW, "--actor", "ci", *args],
                                     capture_output=True, text=True, env=env, cwd=REPO, timeout=600)
                self.assertEqual(out.returncode, expect, out.stdout + out.stderr)
                return json.loads(out.stdout)

            cli("ingest", "--input", str(drop))
            stories = cli("build-drafts", "--date", SESSION)["result"]["stories"]
            self.assertEqual([s["state"] for s in stories], ["AWAITING_APPROVAL"] * 2)
            sid = stories[0]["story_id"]
            self.assertEqual(cli("schedule", sid, expect=2)["error"]["code"], "APPROVAL_REQUIRED")
            cli("approve", sid, "--by", "yusuke")
            cli("pause-all", "--reason", "drill")
            self.assertEqual(cli("schedule", sid, expect=2)["error"]["code"], "CONTROL_BLOCKED")
            cli("resume-all")
            sched = cli("schedule", sid)["result"]
            self.assertEqual(len(sched["schedules"]), 3)
            self.assertTrue(cli("schedule", sid)["result"]["noop"])
            shown = cli("show", sid)["result"]
            self.assertIn("Not investment advice", shown["drafts"]["en-US"]["script"][-1])
            self.assertTrue(cli("audit-verify")["result"]["ok"])
            q = cli("queue")["result"]
            self.assertEqual({s["state"] for s in q["stories"]}, {"SCHEDULED", "AWAITING_APPROVAL"})

            sdir = root / "home" / "artifacts" / SESSION / sid
            for name in (*ARTIFACT_FILES, "schedule.json", "dry_run/youtube_shorts.json", "dry_run/tiktok.json",
                         "dry_run/x.json"):
                self.assertTrue((sdir / name).is_file(), name)
            log = (root / "home" / "logs" / "auto_publish.jsonl").read_text(encoding="utf-8").splitlines()
            events = [json.loads(line)["event"] for line in log]
            self.assertIn("schedule.dry_run_written", events)
            self.assertIn("cli.refused", events)


if __name__ == "__main__":
    unittest.main()
