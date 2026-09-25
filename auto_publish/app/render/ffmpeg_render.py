"""ASSET_RENDER: deterministic 9:16 1080x1920 H.264 master via FFmpeg.

Layout (30 s at the default 6 s/segment):
  0-24 s  header + hook title; bullets b1/b2/b3 appear at 6/12/18 s
  0-30 s  burned-in English caption of the current narration segment
  24-30 s end disclaimer card
Captions/subtitles come from the final approved script (post_en), never from a
separate model draft.

Determinism: all text goes through textfiles written by us, the font is copied
into the working dir (hash recorded), x264 runs single-threaded, and bitexact
flags strip encoder/version metadata. ``build_command`` is a pure function so
the exact argv is testable without FFmpeg.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

from ..errors import RenderError, TransientError
from ..hashing import sha256_file, sha256_text, write_atomic

BG = "0x0B0F14"
MASTER = "master_1080x1920.mp4"
COVER = "cover.jpg"
CAPTIONS = "captions.srt"
INPUTS_DIR = "render_inputs"


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False)) or " "


def timeline(post_en: dict, seg_seconds: int) -> list[dict]:
    return [{"id": s["id"], "type": s["type"], "start": i * seg_seconds, "end": (i + 1) * seg_seconds, "text": s["text"]}
            for i, s in enumerate(post_en["segments"])]


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(tl: list[dict]) -> str:
    cues = []
    for n, seg in enumerate(tl, start=1):
        cues.append(f"{n}\n{_ts(seg['start'])} --> {_ts(seg['end'])}\n{wrap(seg['text'], 42)}\n")
    return "\n".join(cues)


def text_inputs(post_en: dict, tl: list[dict], session_date: str) -> dict[str, str]:
    """Every string that will be drawn, keyed by the textfile name FFmpeg reads."""
    files = {
        "t_header.txt": f"JAPAN MARKET CLOSE  |  {session_date}",
        "t_title.txt": wrap(post_en["title"], 24),
    }
    if post_en.get("fixture"):
        files["t_fixture.txt"] = "TEST FIXTURE - NOT REAL MARKET DATA"
    for seg in tl:
        if seg["type"] not in ("hook", "disclaimer"):
            files[f"t_{seg['id']}.txt"] = wrap("- " + seg["text"], 34)
        files[f"c_{seg['id']}.txt"] = wrap(seg["text"], 36)
    disc = next(s for s in tl if s["type"] == "disclaimer")
    files["t_disclaimer.txt"] = wrap(disc["text"], 30)
    return files


def _dt(textfile: str, *, size: int, y: str, color: str = "white", x: str = "(w-text_w)/2",
        enable: str | None = None, box: bool = False) -> str:
    parts = [f"drawtext=fontfile=font.ttf", f"textfile={textfile}", "expansion=none", f"fontsize={size}",
             f"fontcolor={color}", f"x={x}", f"y={y}", "line_spacing=14"]
    if box:
        parts += ["box=1", "boxcolor=black@0.62", "boxborderw=24"]
    if enable:
        parts.append(f"enable='{enable}'")
    return ":".join(parts)


def build_filter(tl: list[dict], fixture: bool) -> str:
    body_end = next(s["start"] for s in tl if s["type"] == "disclaimer")
    total = tl[-1]["end"]
    f = [
        _dt("t_header.txt", size=40, y="150", color="0x9FB3C8", enable=f"lt(t,{body_end})"),
        _dt("t_title.txt", size=66, y="250", enable=f"lt(t,{body_end})"),
    ]
    ys = {"b1": 720, "b2": 960, "b3": 1200}
    for seg in tl:
        if seg["id"] in ys:
            f.append(_dt(f"t_{seg['id']}.txt", size=46, y=str(ys[seg["id"]]), x="90", color="0xE6EDF3",
                         enable=f"between(t,{seg['start']},{body_end})"))
    for seg in tl:
        if seg["type"] == "disclaimer":
            continue
        f.append(_dt(f"c_{seg['id']}.txt", size=44, y="1560", box=True,
                     enable=f"gte(t,{seg['start']})*lt(t,{seg['end']})"))
    f.append(_dt("t_disclaimer.txt", size=52, y="(h-text_h)/2", enable=f"between(t,{body_end},{total})"))
    if fixture:
        f.append(_dt("t_fixture.txt", size=38, y="60", color="0xFF5C5C"))
    return ",".join(f)


def build_command(tl: list[dict], fixture: bool, *, width: int, height: int, fps: int,
                  preset: str = "medium") -> list[str]:
    duration = tl[-1]["end"]
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={BG}:s={width}x{height}:r={fps}:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(duration),
        "-vf", build_filter(tl, fixture),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", preset, "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "1",
        "-c:a", "aac", "-b:a", "128k",
        "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-movflags", "+faststart",
        f"../{MASTER}",
    ]


def build_cover_command(at_second: int) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", str(at_second),
            "-i", f"../{MASTER}", "-frames:v", "1", "-q:v", "3", "-map_metadata", "-1",
            "-fflags", "+bitexact", "-flags:v", "+bitexact", f"../{COVER}"]


def probe(path: Path, ffprobe: str = "ffprobe") -> dict:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height",
         "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if out.returncode != 0:
        raise RenderError(f"ffprobe failed: {out.stderr.strip()[-400:]}", code="PROBE_FAILED")
    data = json.loads(out.stdout)
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"video_codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height"),
            "audio_codec": a.get("codec_name"), "duration": round(float(data["format"]["duration"]), 1)}


class FfmpegRenderer:
    def __init__(self, cfg: dict):
        self.cfg = cfg["render"]
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")

    def _font(self) -> Path:
        for cand in self.cfg["font_candidates"]:
            if Path(cand).is_file():
                return Path(cand)
        raise RenderError("no usable font found (install fonts-dejavu-core or set render.font_candidates)",
                          code="FONT_MISSING")

    def _run(self, argv: list[str], cwd: Path) -> None:
        try:
            out = subprocess.run([self.ffmpeg, *argv[1:]], cwd=cwd, capture_output=True, text=True,
                                 timeout=int(self.cfg["timeout_seconds"]), check=False)
        except subprocess.TimeoutExpired as exc:
            raise TransientError(f"ffmpeg timed out after {exc.timeout}s", code="RENDER_TIMEOUT") from exc
        if out.returncode != 0:
            raise RenderError(f"ffmpeg exited {out.returncode}: {out.stderr.strip()[-600:]}", code="FFMPEG_FAILED")

    def version(self) -> str:
        out = subprocess.run([self.ffmpeg, "-version"], capture_output=True, text=True, timeout=30, check=False)
        return out.stdout.splitlines()[0] if out.stdout else "unknown"

    def render(self, story_dir: Path, post_en: dict) -> dict:
        if not self.ffmpeg or not self.ffprobe:
            raise RenderError("ffmpeg/ffprobe not found on PATH; R1 requires FFmpeg (see README)",
                              code="FFMPEG_MISSING")
        seg_s = int(self.cfg["segment_seconds"])
        tl = timeline(post_en, seg_s)
        work = story_dir / INPUTS_DIR
        work.mkdir(parents=True, exist_ok=True)
        inputs = text_inputs(post_en, tl, post_en["session_date"])
        for name, text in inputs.items():
            write_atomic(work / name, text.encode("utf-8"))
        font_src = self._font()
        shutil.copyfile(font_src, work / "font.ttf")
        srt = build_srt(tl)
        write_atomic(story_dir / CAPTIONS, srt.encode("utf-8"))

        cmd = build_command(tl, bool(post_en.get("fixture")), width=int(self.cfg["width"]),
                            height=int(self.cfg["height"]), fps=int(self.cfg["fps"]),
                            preset=str(self.cfg.get("x264_preset", "medium")))
        cover_cmd = build_cover_command(max(0, tl[-1]["start"] - 2))
        try:
            self._run(cmd, work)
            self._run(cover_cmd, work)
        finally:
            font_sha = sha256_file(work / "font.ttf")
            (work / "font.ttf").unlink(missing_ok=True)  # not redistributed; hash recorded instead

        pr = probe(story_dir / MASTER, self.ffprobe)
        expected_dur = float(tl[-1]["end"])
        if (pr["width"], pr["height"]) != (int(self.cfg["width"]), int(self.cfg["height"])) \
                or pr["video_codec"] != "h264" or abs(pr["duration"] - expected_dur) > 0.5:
            raise RenderError(f"rendered asset failed probe: {pr}", code="ASSET_INVALID")
        return {
            "schema": "auto_publish.render_manifest.v1",
            "story_id": post_en["story_id"],
            "ffmpeg_version": self.version(),
            "command": cmd,
            "cover_command": cover_cmd,
            "cwd": INPUTS_DIR,
            "font": {"source": font_src.name, "sha256": font_sha},
            "inputs": {name: sha256_text(t) for name, t in sorted(inputs.items())},
            "timeline": [{k: s[k] for k in ("id", "type", "start", "end")} for s in tl],
            "probe": pr,
            "captions_sha256": sha256_text(srt),
            "outputs": {
                MASTER: {"sha256": sha256_file(story_dir / MASTER), "bytes": (story_dir / MASTER).stat().st_size},
                COVER: {"sha256": sha256_file(story_dir / COVER), "bytes": (story_dir / COVER).stat().st_size},
            },
            "network": "none",
        }
