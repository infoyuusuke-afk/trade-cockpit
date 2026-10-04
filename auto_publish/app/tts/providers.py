"""Built-in offline providers: ``silent`` and the test-only ``fake_tone``."""
from __future__ import annotations

import hashlib
import struct

from ..text.wrap import display_width
from .base import AudioClip

FAKE_TONE_VERSION = "fake_tone/1"
MS_PER_CELL = 65          # ~15 Latin chars/s, ~7.7 full-width chars/s
MIN_CLIP_MS = 300
AMPLITUDE = 6000


class SilentProvider:
    name = "silent"
    narrates = False
    test_only = False

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def synthesize(self, text: str, lang: str, voice: str | None) -> AudioClip:
        return AudioClip(b"", self.sample_rate, self.name, voice, "silent/1")


class FakeToneProvider:
    """Deterministic stand-in for a speech engine (CI / tests).

    Length follows the text's display width so timelines behave like real
    narration; pitch comes from SHA256(lang|voice|text). Integer-only triangle
    wave => identical bytes on every OS/CPU (no libm).
    """

    name = "fake_tone"
    narrates = True
    test_only = True

    def __init__(self, sample_rate: int):
        self.sample_rate = sample_rate

    def duration_ms(self, text: str) -> int:
        ms = max(MIN_CLIP_MS, MS_PER_CELL * display_width(text))
        return -(-ms // 10) * 10

    def synthesize(self, text: str, lang: str, voice: str | None) -> AudioClip:
        h = hashlib.sha256(f"{lang}|{voice or ''}|{text}".encode("utf-8")).digest()
        freq = 220 + int.from_bytes(h[:2], "big") % 440
        rate = self.sample_rate
        n = self.duration_ms(text) * rate // 1000
        a = AMPLITUDE
        vals = []
        for i in range(n):
            v = 4 * a * ((i * freq) % rate) // rate          # 0 .. 4a-1
            vals.append(v if v < a else (2 * a - v if v < 3 * a else v - 4 * a))
        return AudioClip(struct.pack(f"<{n}h", *vals), rate, self.name, voice, FAKE_TONE_VERSION)
