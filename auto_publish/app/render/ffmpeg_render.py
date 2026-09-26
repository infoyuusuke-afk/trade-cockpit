"""ASSET_RENDER: deterministic 9:16 1080x1920 H.264 masters via FFmpeg.

Layout (R1 silent: 30 s at 6 s/segment; with narration the segment boundaries
come from the audio-driven timeline, see app/tts/narration.py):
  hook .. disclaimer  header + hook title; bullets b1/b2/b3 appear at their segment start
  whole video         burned-in caption of the current narration segment
  disclaimer segment  end disclaimer card
Captions/subtitles come from the final approved script (post_en / post_ja),
never from a separate model draft.

Variants (``render.variants``):
  en_primary  master_1080x1920.mp4 / cover.jpg      English text + en narration (R1 default)
  ja_primary  master_ja_1080x1920.mp4 / cover_ja.jpg Japanese text + ja narration (opt-in)
Each language has its own font list; a missing font fails closed (FONT_MISSING).

Determinism: all text goes through textfiles written by us, the font is copied
into the working dir (hash recorded), x264 runs single-threaded, and bitexact
flags strip encoder/version metadata. ``build_command`` is a pure function so
the exact argv is testable without FFmpeg.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from ..errors import RenderError, TransientError
from ..hashing import sha256_file, sha256_text, write_atomic
from ..text.wrap import is_cjk_lang, wrap_text

BG = "0x0B0F14"
MASTER = "master_1080x1920.mp4"
COVER = "cover.jpg"
CAPTIONS = "captions.srt"
INPUTS_DIR = "render_inputs"

VARIANTS = {
    "en_primary": {"lang": "en-US", "master": MASTER, "cover": COVER, "inputs": INPUTS_DIR},
    "ja_primary": {"lang": "ja-JP", "master": "master_ja_1080x1920.mp4", "cover": "cover_ja.jpg",
                   "inputs": "render_inputs_ja-JP"},
}

# Wrap widths: characters for Latin text (R1 values), display cells for CJK (full-width = 2).
WIDTHS = {
    "latin": {"srt": 42, "title": 24, "bullet": 34, "caption": 36, "disclaimer": 30},
    "cjk": {"srt": 32, "title": 28, "bullet": 34, "caption": 32, "disclaimer": 36},
}
LABELS = {
    "en-US": {"header": "JAPAN MARKET CLOSE  |  {date}", "fixture": "TEST FIXTURE - NOT REAL MARKET DATA",
              "bullet": "- "},
    "ja-JP": {"header": "東京市場 大引け  |  {date}", "fixture": "テスト用サンプル・実際の市場データではありません",
              "bullet": "・"},
}


def captions_file(lang: str) -> str:
    return f"captions_{lang}.srt"


def _widths(lang: str) -> dict:
    return WIDTHS["cjk" if is_cjk_lang(lang) else "latin"]


def wrap(text: str, width: int, lang: str = "en-US") -> str:
    return wrap_text(text, width, lang)


def timeline(post_en: dict, seg_seconds: int) -> list[dict]:
    return [{"id": s["id"], "type": s["type"], "start": i * seg_seconds, "end": (i + 1) * seg_seconds, "text": s["text"]}
            for i, s in enumerate(post_en["segments"])]


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(tl: list[dict], lang: str = "en-US") -> str:
    width = _widths(lang)["srt"]
    cues = []
    for n, seg in enumerate(tl, start=1):
        cues.append(f"{n}\n{_ts(seg['start'])} --> {_ts(seg['end'])}\n{wrap(seg['text'], width, lang)}\n")
    return "\n".join(cues)


def text_inputs(post: dict, tl: list[dict], session_date: str, lang: str = "en-US") -> dict[str, str]:
    """Every string that will be drawn, keyed by the textfile name FFmpeg reads."""
    w, lab = _widths(lang), LABELS[lang]
    files = {
        "t_header.txt": lab["header"].format(date=session_date),
        "t_title.txt": wrap(post["title"], w["title"], lang),
    }
    if post.get("fixture"):
        files["t_fixture.txt"] = lab["fixture"]
    for seg in tl:
        if seg["type"] not in ("hook", "disclaimer"):
            files[f"t_{seg['id']}.txt"] = wrap(lab["bullet"] + seg["text"], w["bullet"], lang)
        files[f"c_{seg['id']}.txt"] = wrap(seg["text"], w["caption"], lang)
    disc = next(s for s in tl if s["type"] == "disclaimer")
    files["t_disclaimer.txt"] = wrap(disc["text"], w["disclaimer"], lang)
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
                  preset: str = "medium", audio: str | None = None, master: str = MASTER) -> list[str]:
    """``audio`` None => silent track (R1, argv unchanged); else a narration WAV next to the master."""
    duration = tl[-1]["end"]
    audio_in = (["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"] if audio is None
                else ["-i", f"../{audio}"])
    audio_out = [] if audio is None else ["-ar", "48000", "-ac", "2"]
    return [
        "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={BG}:s={width}x{height}:r={fps}:d={duration}",
        *audio_in,
        "-t", str(duration),
        "-vf", build_filter(tl, fixture),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", preset, "-crf", "23", "-pix_fmt", "yuv420p", "-threads", "1",
        "-c:a", "aac", "-b:a", "128k", *audio_out,
        "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-movflags", "+faststart",
        f"../{master}",
    ]


def build_cover_command(at_second: int | float, master: str = MASTER, cover: str = COVER) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", str(at_second),
            "-i", f"../{master}", "-frames:v", "1", "-q:v", "3", "-map_metadata", "-1",
            "-fflags", "+bitexact", "-flags:v", "+bitexact", f"../{cover}"]


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


def legacy_plan(post_en: dict, seg_seconds: int) -> dict:
    """R1 plan: English only, fixed segments, silent audio."""
    return {"variants": ["en_primary"], "posts": {"en-US": post_en},
            "timelines": {"en-US": timeline(post_en, seg_seconds)}, "narration": {"en-US": None}}


def variant_outputs(variants: list[str]) -> list[str]:
    return [n for v in variants for n in (VARIANTS[v]["master"], VARIANTS[v]["cover"])]


class FfmpegRenderer:
    def __init__(self, cfg: dict):
        self.cfg = cfg["render"]
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")

    def font_candidates(self, lang: str) -> list[str]:
        fonts = self.cfg.get("fonts", {})
        if lang in fonts:
            return list(fonts[lang])
        return list(self.cfg["font_candidates"]) if lang == "en-US" else []

    def _font(self, lang: str = "en-US") -> Path:
        for cand in self.font_candidates(lang):
            if Path(cand).is_file():
                return Path(cand)
        raise RenderError(f"no usable {lang} font found (install fonts-dejavu-core / fonts-noto-cjk, or set"
                          f" render.fonts.{lang})", code="FONT_MISSING",
                          details={"lang": lang, "candidates": self.font_candidates(lang)})

    def _run(self, argv: list[str], cwd: Path) -> None:
        try:
            out = subprocess.run([self.ffmpeg, *argv[1:]], cwd=cwd, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace",
                                 timeout=int(self.cfg["timeout_seconds"]), check=False)
        except subprocess.TimeoutExpired as exc:
            raise TransientError(f"ffmpeg timed out after {exc.timeout}s", code="RENDER_TIMEOUT") from exc
        if out.returncode != 0:
            raise RenderError(f"ffmpeg exited {out.returncode}: {out.stderr.strip()[-600:]}", code="FFMPEG_FAILED")

    def version(self) -> str:
        out = subprocess.run([self.ffmpeg, "-version"], capture_output=True, text=True, timeout=30, check=False)
        return out.stdout.splitlines()[0] if out.stdout else "unknown"

    def _render_variant(self, story_dir: Path, variant: str, post: dict, tl: list[dict],
                        audio: str | None, font_src: Path) -> dict:
        spec = VARIANTS[variant]
        lang = spec["lang"]
        work = story_dir / spec["inputs"]
        work.mkdir(parents=True, exist_ok=True)
        inputs = text_inputs(post, tl, post["session_date"], lang)
        for name, text in inputs.items():
            write_atomic(work / name, text.encode("utf-8"))
        shutil.copyfile(font_src, work / "font.ttf")
        cmd = build_command(tl, bool(post.get("fixture")), width=int(self.cfg["width"]),
                            height=int(self.cfg["height"]), fps=int(self.cfg["fps"]),
                            preset=str(self.cfg.get("x264_preset", "medium")), audio=audio, master=spec["master"])
        cover_cmd = build_cover_command(max(0, tl[-1]["start"] - 2), spec["master"], spec["cover"])
        try:
            self._run(cmd, work)
            self._run(cover_cmd, work)
        finally:
            font_sha = sha256_file(work / "font.ttf")
            (work / "font.ttf").unlink(missing_ok=True)  # not redistributed; hash recorded instead

        pr = probe(story_dir / spec["master"], self.ffprobe)
        expected_dur = float(tl[-1]["end"])
        if (pr["width"], pr["height"]) != (int(self.cfg["width"]), int(self.cfg["height"])) \
                or pr["video_codec"] != "h264" or pr["audio_codec"] != "aac" \
                or abs(pr["duration"] - expected_dur) > 0.5:
            raise RenderError(f"rendered asset failed probe: {pr}", code="ASSET_INVALID",
                              details={"variant": variant})
        return {
            "lang": lang,
            "command": cmd,
            "cover_command": cover_cmd,
            "cwd": spec["inputs"],
            "font": {"source": font_src.name, "sha256": font_sha},
            "inputs": {name: sha256_text(t) for name, t in sorted(inputs.items())},
            "timeline": [{k: s[k] for k in ("id", "type", "start", "end")} for s in tl],
            "audio": {"source": audio or "anullsrc",
                      "sha256": sha256_file(story_dir / audio) if audio else None},
            "probe": pr,
            "outputs": {n: {"sha256": sha256_file(story_dir / n), "bytes": (story_dir / n).stat().st_size}
                        for n in (spec["master"], spec["cover"])},
        }

    def render(self, story_dir: Path, post_en: dict, plan: dict | None = None) -> dict:
        if not self.ffmpeg or not self.ffprobe:
            raise RenderError("ffmpeg/ffprobe not found on PATH; R1 requires FFmpeg (see README)",
                              code="FFMPEG_MISSING")
        plan = plan or legacy_plan(post_en, int(self.cfg["segment_seconds"]))
        variants = list(plan["variants"])
        if not variants or variants[0] != "en_primary" or any(v not in VARIANTS for v in variants):
            raise RenderError(f"invalid render variants {variants}", code="RENDER_VARIANT_INVALID")
        # resolve every font before encoding anything (fail-closed, no partial output)
        fonts = {v: self._font(VARIANTS[v]["lang"]) for v in variants}
        done = {}
        for v in variants:
            lang = VARIANTS[v]["lang"]
            post = plan["posts"]["en-US"] if lang == "en-US" else plan["posts"][lang]
            done[v] = self._render_variant(story_dir, v, post, plan["timelines"][lang],
                                           plan["narration"].get(lang), fonts[v])
        en = done["en_primary"]
        manifest = {
            "schema": "auto_publish.render_manifest.v1",
            "story_id": post_en["story_id"],
            "ffmpeg_version": self.version(),
            **{k: en[k] for k in ("command", "cover_command", "cwd", "font", "inputs", "timeline", "probe")},
            "captions_sha256": sha256_text(build_srt(plan["timelines"]["en-US"])),
            "outputs": dict(en["outputs"]),
            "network": "none",
        }
        if len(variants) > 1 or en["audio"]["source"] != "anullsrc":
            manifest["variants"] = done
        return manifest
