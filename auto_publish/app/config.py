"""Configuration loading + fail-closed validation."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from .errors import ValidationError

PACKAGE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PACKAGE_DIR / "config" / "default.json"
DEFAULT_HOME = PACKAGE_DIR / "var"
ALLOWED_ADAPTERS_R1 = frozenset({"dry_run"})
# Offline TTS only. Cloud / paid TTS is not selectable without an owner decision (and a code change).
ALLOWED_TTS_PROVIDERS = frozenset({"silent", "fake_tone", "windows_sapi", "espeak_ng"})
ALLOWED_RENDER_VARIANTS = ("en_primary", "ja_primary")


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "auto_publish.db"

    @property
    def evidence_store(self) -> Path:
        return self.home / "evidence_store"

    @property
    def artifacts(self) -> Path:
        return self.home / "artifacts"

    @property
    def logs(self) -> Path:
        return self.home / "logs"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | os.PathLike | None = None, overrides: dict | None = None) -> dict:
    cfg = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if path:
        cfg = _deep_merge(cfg, json.loads(Path(path).read_text(encoding="utf-8")))
    if overrides:
        cfg = _deep_merge(cfg, overrides)
    validate_config(cfg)
    return cfg


def _hhmm(value: str) -> int:
    h, m = value.split(":")
    minutes = int(h) * 60 + int(m)
    if not (0 <= minutes <= 24 * 60) or int(m) >= 60:
        raise ValueError(value)
    return minutes


def validate_config(cfg: dict) -> None:
    if cfg.get("release_gate") != "R1":
        raise ValidationError("this build only supports release_gate R1 (DRY-RUN)")
    ZoneInfo(cfg["market_timezone"])
    for name, wave in cfg["waves"].items():
        ZoneInfo(wave["audience_tz"])
        if _hhmm(wave["start_jst"]) >= _hhmm(wave["end_jst"]):
            raise ValidationError(f"wave {name}: start must be before end")
    for name, p in cfg["platforms"].items():
        if p["adapter"] not in ALLOWED_ADAPTERS_R1:
            raise ValidationError(
                f"platform {name}: adapter {p['adapter']!r} is not allowed in R1 (dry_run only)",
                code="ADAPTER_NOT_ALLOWED",
            )
        for w in p["waves"]:
            if w not in cfg["waves"]:
                raise ValidationError(f"platform {name}: unknown wave {w}")
    if int(cfg["max_attempts"]) < 1:
        raise ValidationError("max_attempts must be >= 1")
    variants = cfg["render"].get("variants", ["en_primary"])
    if not variants or variants[0] != "en_primary" or len(set(variants)) != len(variants) \
            or any(v not in ALLOWED_RENDER_VARIANTS for v in variants):
        raise ValidationError(f"render.variants must start with en_primary and use {ALLOWED_RENDER_VARIANTS}",
                              code="RENDER_VARIANT_INVALID")
    _validate_tts(cfg["tts"])
    d = cfg["dispatch"]
    if int(d["lease_seconds"]) < 30 or not 0 <= int(d["max_lateness_minutes"]) <= 180:
        raise ValidationError("dispatch.lease_seconds >= 30 and 0 <= dispatch.max_lateness_minutes <= 180",
                              code="DISPATCH_CONFIG_INVALID")


def _validate_tts(t: dict) -> None:
    for lang, v in t.get("voices", {}).items():
        if v.get("provider") not in ALLOWED_TTS_PROVIDERS:
            raise ValidationError(f"tts.voices.{lang}: provider {v.get('provider')!r} is not allowed"
                                  f" (offline only: {sorted(ALLOWED_TTS_PROVIDERS)})", code="TTS_PROVIDER_NOT_ALLOWED")
    rate = int(t["sample_rate"])
    if rate % 1000 or not 8000 <= rate <= 48000:
        raise ValidationError("tts.sample_rate must be a multiple of 1000 in 8000..48000", code="TTS_CONFIG_INVALID")
    lo, hi = float(t["min_total_seconds"]), float(t["max_total_seconds"])
    if not (0 < float(t["min_segment_seconds"]) and 0 <= float(t["segment_padding_seconds"]) and 0 < lo < hi <= 60):
        raise ValidationError("tts timing limits are inconsistent", code="TTS_CONFIG_INVALID")


def resolve_home(home: str | os.PathLike | None) -> Paths:
    if home:
        return Paths(Path(home).resolve())
    env = os.environ.get("AUTO_PUBLISH_HOME")
    return Paths(Path(env).resolve() if env else DEFAULT_HOME)
