"""Narration track + audio-driven timeline + tts_manifest (evidence).

The text spoken for a segment is *exactly* the approved segment text (no
rewriting; a pronunciation lexicon, when added, will only change the TTS input
and both hashes are recorded).

Timing
------
* ``silent`` provider: the R1 fixed layout (``render.segment_seconds`` each).
* narrating provider: segment = max(min_segment_seconds, clip + padding); the
  clip starts at the segment start and the rest is silence. Subtitles use the
  same boundaries, so captions and narration can never drift apart.
* total outside [min_total_seconds, max_total_seconds] => fail-closed
  (NARRATION_TOO_LONG / NARRATION_TOO_SHORT). Text is never shortened automatically.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..errors import EvidenceError, ValidationError
from ..hashing import sha256_bytes, sha256_file, sha256_text
from .base import NarrationLengthError, TtsError, get_provider, wav_bytes

SCHEMA = "auto_publish.tts_manifest.v1"
TTS_MANIFEST = "tts_manifest.json"


def narration_file(lang: str) -> str:
    return f"narration_{lang}.wav"


def _sec(ms: int) -> int | float:
    """Seconds as JSON number: int when whole (keeps the R1 timeline byte-identical)."""
    return ms // 1000 if ms % 1000 == 0 else ms / 1000


@dataclass
class Narration:
    lang: str
    timeline: list[dict]
    wav: bytes | None
    manifest: dict

    @property
    def file(self) -> str | None:
        return narration_file(self.lang) if self.wav is not None else None


def voice_cfg(tts_cfg: dict, lang: str) -> tuple[str, str | None]:
    v = tts_cfg.get("voices", {}).get(lang, {})
    return v.get("provider", "silent"), v.get("voice")


def narrate(post: dict, tts_cfg: dict, segment_seconds: int) -> Narration:
    lang = post["lang"]
    pname, voice = voice_cfg(tts_cfg, lang)
    rate = int(tts_cfg["sample_rate"])
    provider = get_provider(pname, rate)
    if provider.test_only and not post.get("fixture"):
        raise ValidationError(f"TTS provider {pname!r} is test-only and refuses non-fixture data",
                              code="TTS_TEST_PROVIDER_ON_REAL_DATA", details={"lang": lang})
    segs = post["segments"]
    clips = [provider.synthesize(s["text"], lang, voice) for s in segs]

    if not provider.narrates:
        durations = [int(segment_seconds) * 1000] * len(segs)
    else:
        min_ms = round(float(tts_cfg["min_segment_seconds"]) * 1000)
        pad_ms = round(float(tts_cfg["segment_padding_seconds"]) * 1000)
        durations = []
        for s, c in zip(segs, clips):
            if c.sample_rate != rate:
                raise TtsError(f"{pname}: sample rate {c.sample_rate} != {rate}", code="TTS_BAD_AUDIO")
            if c.samples == 0 and s["text"].strip():
                raise TtsError(f"{pname}: empty audio for segment {s['id']}", code="TTS_EMPTY_AUDIO",
                               details={"lang": lang, "segment": s["id"]})
            durations.append(max(min_ms, c.duration_ms + pad_ms))

    total_ms = sum(durations)
    lo = round(float(tts_cfg["min_total_seconds"]) * 1000)
    hi = round(float(tts_cfg["max_total_seconds"]) * 1000)
    if total_ms > hi or total_ms < lo:
        raise NarrationLengthError(
            f"{lang} narration is {total_ms / 1000:.2f}s; allowed {lo / 1000:g}-{hi / 1000:g}s (not auto-shortened)",
            code="NARRATION_TOO_LONG" if total_ms > hi else "NARRATION_TOO_SHORT",
            details={"lang": lang, "total_seconds": total_ms / 1000,
                     "segments": {s["id"]: d / 1000 for s, d in zip(segs, durations)}})

    timeline, entries, start = [], [], 0
    for s, c, d in zip(segs, clips, durations):
        timeline.append({"id": s["id"], "type": s["type"], "start": _sec(start), "end": _sec(start + d),
                         "text": s["text"]})
        entries.append({"id": s["id"], "text_sha256": sha256_text(s["text"]),
                        "tts_input_sha256": sha256_text(s["text"]),
                        "audio_sha256": c.sha256 if provider.narrates else None,
                        "audio_ms": c.duration_ms if provider.narrates else 0,
                        "start": _sec(start), "end": _sec(start + d)})
        start += d

    wav = None
    if provider.narrates:
        track = bytearray(total_ms * rate // 1000 * 2)
        pos = 0
        for c, d in zip(clips, durations):
            off = pos * rate // 1000 * 2
            track[off:off + len(c.pcm)] = c.pcm
            pos += d
        wav = wav_bytes(bytes(track), rate)

    manifest = {
        "lang": lang, "provider": provider.name, "voice": voice, "test_only": provider.test_only,
        "engine_version": clips[0].engine_version if clips else None,
        "timing": "audio_driven" if provider.narrates else "fixed_segment_seconds",
        "sample_rate": rate, "total_seconds": _sec(total_ms),
        "narration_file": narration_file(lang) if wav is not None else None,
        "narration_sha256": sha256_bytes(wav) if wav is not None else None,
        "lexicon": None, "segments": entries,
    }
    return Narration(lang, timeline, wav, manifest)


def build_manifest(story_id: str, narrations: list[Narration]) -> dict:
    return {"schema": SCHEMA, "story_id": story_id, "network": "none",
            "langs": {n.lang: n.manifest for n in narrations}}


def verify(story_dir: Path, posts: list[dict]) -> None:
    """Approval/schedule-time check: the narration is for exactly the approved text
    and the audio on disk is the audio that was recorded. Absent manifest => legacy R1 story."""
    p = story_dir / TTS_MANIFEST
    if not p.is_file():
        return
    m = json.loads(p.read_text(encoding="utf-8"))
    for post in posts:
        entry = m["langs"].get(post["lang"])
        if entry is None:
            raise EvidenceError(f"tts_manifest has no {post['lang']} entry", code="TTS_MANIFEST_INVALID")
        want = [(s["id"], sha256_text(s["text"])) for s in post["segments"]]
        got = [(s["id"], s["text_sha256"]) for s in entry["segments"]]
        if want != got:
            raise EvidenceError(f"{post['lang']}: narration text differs from the approved script",
                                code="TTS_TEXT_MISMATCH")
        if entry["narration_file"]:
            f = story_dir / entry["narration_file"]
            if not f.is_file() or sha256_file(f) != entry["narration_sha256"]:
                raise EvidenceError(f"{entry['narration_file']} does not match tts_manifest",
                                    code="NARRATION_MISMATCH")
