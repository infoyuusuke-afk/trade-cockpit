"""Load and validate NEXT score weights.

Weights stay in config so a later trade-diary calibration can retune them
without editing the scoring code. A malformed weight file is rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "next_score_v1.json"

MARKET_FEATURES = (
    "price_change_15s",
    "price_accel_45s",
    "volume_surge_ratio",
    "turnover_accel",
    "high_update_frequency",
    "vwap_position",
    "or5_state",
    "or15_state",
    "pullback_shallowness",
    "relative_strength",
    "liquidity",
)

MEMBERSHIP_REASONS = ("SCHEDULED_RESELECT", "EMERGENCY_PROMOTION", "TOP_UNIVERSE_SCORE")


def load_config(path: Path | str | None = None) -> dict:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return validate_config(data)


def validate_config(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("next score config must be an object")
    weights = data.get("weights")
    if not isinstance(weights, dict):
        raise ValueError("next score config is missing weights")
    unknown = sorted(set(weights) - set(MARKET_FEATURES))
    missing = [name for name in MARKET_FEATURES if name not in weights]
    if unknown:
        raise ValueError("unknown next score weight: " + ",".join(unknown))
    if missing:
        raise ValueError("missing next score weight: " + ",".join(missing))
    total = 0.0
    for name in MARKET_FEATURES:
        value = weights[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"weight {name} must be a positive number")
        total += float(value)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"market feature weights must sum to 1, got {total}")
    velocity_weight = data.get("velocity_weight")
    if isinstance(velocity_weight, bool) or not isinstance(velocity_weight, (int, float)):
        raise ValueError("velocity_weight must be a number")
    if not 0 < float(velocity_weight) < 1:
        raise ValueError("velocity_weight must be between 0 and 1")
    coverage = data.get("min_coverage")
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not 0 < float(coverage) <= 1:
        raise ValueError("min_coverage must be in (0, 1]")
    funnel = data.get("funnel") or {}
    for key in ("active_size", "next20_size", "next5_size"):
        if not isinstance(funnel.get(key), int) or funnel[key] <= 0:
            raise ValueError(f"funnel.{key} must be a positive integer")
    if not funnel["next5_size"] <= funnel["next20_size"] <= funnel["active_size"]:
        raise ValueError("funnel sizes must satisfy next5 <= next20 <= active")
    return data
