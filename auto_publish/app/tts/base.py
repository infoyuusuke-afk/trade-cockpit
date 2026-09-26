"""TTS provider interface, audio clip type, WAV encoding and the provider registry.

Audio format everywhere: mono, signed 16-bit little-endian PCM at
``tts.sample_rate`` (default 24 kHz, a multiple of 1000 so every millisecond is
a whole number of samples). A provider returns raw PCM; WAV headers are written
by :func:`wav_bytes` so the bytes are identical on every platform.

Provider policy (fail-closed, enforced again at config load):
* ``silent``     -- no narration; R1 fixed-length layout. Always available.
* ``fake_tone``  -- test-only; deterministic integer-math tone whose length is
                    derived from the text. Refused for non-fixture data.
* ``windows_sapi`` / ``espeak_ng`` -- designed, implemented on the owner PC
                    phase; selecting them here fails closed (TTS_PROVIDER_UNAVAILABLE).
* anything else (cloud / paid / network TTS) -- TTS_PROVIDER_NOT_ALLOWED.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Protocol

from ..errors import RenderError, ValidationError
from ..hashing import sha256_bytes

IMPLEMENTED_PROVIDERS = ("silent", "fake_tone")
DEFERRED_PROVIDERS = ("windows_sapi", "espeak_ng")   # owner-PC phase
KNOWN_PROVIDERS = IMPLEMENTED_PROVIDERS + DEFERRED_PROVIDERS


class TtsError(RenderError):
    code = "TTS_FAILED"


class NarrationLengthError(ValidationError):
    """Narration does not fit the allowed total length. Never auto-shortened."""

    code = "NARRATION_TOO_LONG"


@dataclass(frozen=True)
class AudioClip:
    pcm: bytes
    sample_rate: int
    provider: str
    voice: str | None
    engine_version: str

    @property
    def samples(self) -> int:
        return len(self.pcm) // 2

    @property
    def duration_ms(self) -> int:
        return -(-self.samples * 1000 // self.sample_rate)  # ceil

    @property
    def sha256(self) -> str:
        return sha256_bytes(self.pcm)


class TtsProvider(Protocol):
    name: str
    narrates: bool      # False => no audio; the fixed R1 timeline is used
    test_only: bool

    def synthesize(self, text: str, lang: str, voice: str | None) -> AudioClip: ...


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Canonical RIFF/WAVE (PCM, mono, 16-bit). No optional chunks, no metadata."""
    if len(pcm) % 2:
        raise TtsError("PCM length must be a whole number of 16-bit samples", code="TTS_BAD_AUDIO")
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    return header + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm


def get_provider(name: str, sample_rate: int) -> TtsProvider:
    from .providers import FakeToneProvider, SilentProvider
    if name == "silent":
        return SilentProvider(sample_rate)
    if name == "fake_tone":
        return FakeToneProvider(sample_rate)
    if name in DEFERRED_PROVIDERS:
        raise TtsError(f"TTS provider {name!r} is not available in this build (owner-PC phase)",
                       code="TTS_PROVIDER_UNAVAILABLE", details={"provider": name})
    raise ValidationError(f"TTS provider {name!r} is not allowed (offline providers only; cloud TTS needs owner"
                          " approval)", code="TTS_PROVIDER_NOT_ALLOWED", details={"provider": name})
