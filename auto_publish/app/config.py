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


def resolve_home(home: str | os.PathLike | None) -> Paths:
    if home:
        return Paths(Path(home).resolve())
    env = os.environ.get("AUTO_PUBLISH_HOME")
    return Paths(Path(env).resolve() if env else DEFAULT_HOME)
