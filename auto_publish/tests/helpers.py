"""Shared test helpers. Tests never touch auto_publish/var or the network."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from auto_publish.app import logs
from auto_publish.app.clock import FixedClock, parse_aware
from auto_publish.app.config import Paths, load_config
from auto_publish.app.context import Ctx
from auto_publish.app.db import connect
from auto_publish.app.hashing import sha256_file, write_atomic
from auto_publish.app.ingest.ingest import ingest, validate
from auto_publish.app.render.ffmpeg_render import VARIANTS, legacy_plan

TESTS_DIR = Path(__file__).resolve().parent
FIXTURE_DROP = TESTS_DIR / "fixtures" / "content_drop"
GOLDEN_DIR = TESTS_DIR / "golden"
SESSION = "2026-09-24"
NOW = "2026-09-24T17:00:00+09:00"


def make_ctx(root: Path, now: str = NOW, overrides: dict | None = None) -> Ctx:
    cfg = load_config(overrides=overrides)
    paths = Paths(root / "home")
    clock = FixedClock(parse_aware(now))
    conn = connect(paths.db)
    logs.configure(paths.logs, clock)
    return Ctx(conn=conn, clock=clock, cfg=cfg, paths=paths, actor="test")


def copy_fixture(root: Path, session: str = SESSION) -> Path:
    dest = root / "drop" / session
    shutil.copytree(FIXTURE_DROP / session, dest)
    return dest


class FakeRenderer:
    """Stands in for FFmpeg in logic tests (real FFmpeg is exercised in test_render)."""

    def __init__(self, fail_times: int = 0, exc: Exception | None = None):
        self.fail_times = fail_times  # failures *per story* before succeeding
        self.exc = exc
        self.calls: dict[str, int] = {}

    def render(self, story_dir: Path, post_en: dict, plan: dict | None = None) -> dict:
        n = self.calls[post_en["story_id"]] = self.calls.get(post_en["story_id"], 0) + 1
        if n <= self.fail_times:
            raise self.exc
        plan = plan or legacy_plan(post_en, 6)
        outputs, variants = {}, {}
        for v in plan["variants"]:
            spec = VARIANTS[v]
            tl = plan["timelines"][spec["lang"]]
            audio = plan["narration"].get(spec["lang"])
            # the fake "video" embeds what it would contain, so audio/timeline changes change its hash
            body = f"{post_en['story_id']}|{v}|{tl[-1]['end']}|{audio}".encode()
            if audio:
                body += b"|" + sha256_file(story_dir / audio).encode()
            write_atomic(story_dir / spec["master"], b"FAKE-MP4:" + body)
            write_atomic(story_dir / spec["cover"], b"FAKE-JPG:" + body)
            outs = {n: {"sha256": sha256_file(story_dir / n), "bytes": (story_dir / n).stat().st_size}
                    for n in (spec["master"], spec["cover"])}
            outputs.update(outs)
            variants[v] = {"lang": spec["lang"], "timeline": [{k: s[k] for k in ("id", "type", "start", "end")} for s in tl],
                           "audio": {"source": audio or "anullsrc"}, "outputs": outs}
        tl = plan["timelines"]["en-US"]
        return {
            "schema": "auto_publish.render_manifest.v1", "story_id": post_en["story_id"], "fake": True,
            "timeline": variants["en_primary"]["timeline"],
            "probe": {"video_codec": "h264", "width": 1080, "height": 1920, "audio_codec": "aac",
                      "duration": float(tl[-1]["end"])},
            "outputs": outputs, "variants": variants,
        }


class PipelineCase(unittest.TestCase):
    """Temp home + copied fixture + ctx per test."""

    now = NOW
    overrides: dict | None = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ap_test_")
        self.root = Path(self._tmp.name)
        self.drop = copy_fixture(self.root)
        self.ctx = make_ctx(self.root, self.now, self.overrides)

    def tearDown(self):
        self.ctx.conn.close()
        # evidence store copies are read-only; make them removable
        for dirpath, _dirs, files in os.walk(self.root):
            for f in files:
                try:
                    os.chmod(os.path.join(dirpath, f), 0o644)
                except OSError:
                    pass
        self._tmp.cleanup()

    def ingest_validate(self):
        ingest(self.ctx, self.drop)
        return validate(self.ctx, SESSION)

    def story_state(self, sid: str) -> str:
        return self.ctx.conn.execute("SELECT state FROM stories WHERE story_id = ?", (sid,)).fetchone()["state"]
