"""NEXT score v1.

The score looks for ignition before a large extension. A finished spike
scores below a smaller move that is still accelerating. Missing inputs are
unavailable. They are not zeroes and they are not "normal" baselines.
"""

from __future__ import annotations

from scripts.next_foundation.config import MARKET_FEATURES, OR_FEATURES, OR_UNOBSERVED_STATES

OR_COMPONENT = {"ABOVE": 0.88, "INSIDE": 0.48, "BELOW": 0.12}

REASON_BY_FEATURE = {
    "price_change_15s": "PRICE_CHANGE_15S",
    "price_accel_45s": "PRICE_ACCEL_45S",
    "volume_surge_ratio": "VOLUME_SURGE",
    "turnover_accel": "TURNOVER_ACCEL",
    "high_update_frequency": "HIGH_UPDATE",
    "vwap_position": "VWAP_SUPPORTIVE",
    "or5_state": None,
    "or15_state": None,
    "pullback_shallowness": "SHALLOW_PULLBACK",
    "relative_strength": "RELATIVE_STRENGTH",
    "liquidity": "LIQUIDITY_OK",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def component_price_change(pct: float | None) -> float | None:
    """Percent move over 15 seconds. Early lift outranks an extended spike."""

    if pct is None:
        return None
    if pct < 0:
        return _clamp(0.15 + pct / 2.0)
    if pct <= 0.35:
        return 0.35 + (pct / 0.35) * 0.55
    if pct <= 0.80:
        return 0.90 - ((pct - 0.35) / 0.45) * 0.15
    return max(0.35, 0.75 - (pct - 0.80) * 0.22)


def component_accel(pct: float | None) -> float | None:
    if pct is None:
        return None
    if pct <= 0:
        return _clamp(0.20 + pct * 0.5, 0.0, 0.20)
    return _clamp(0.20 + (pct / 0.40) * 0.80)


def _ratio_component(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0:
        return None
    if value <= 1:
        return 0.12 + 0.10 * value
    if value <= 3:
        return _clamp(0.22 + ((value - 1) / 2) * 0.70)
    return _clamp(0.92 + (value - 3) * 0.04)


def component_volume(value: float | None) -> float | None:
    return _ratio_component(value)


def component_turnover(value: float | None) -> float | None:
    return _ratio_component(value)


def component_high_update(per_minute: float | None) -> float | None:
    if per_minute is None:
        return None
    if per_minute < 0:
        return None
    if per_minute == 0:
        return 0.10
    return _clamp(0.10 + per_minute * 0.22)


def component_vwap(distance_pct: float | None) -> float | None:
    """Percent distance of price above VWAP. Just-above scores highest."""

    if distance_pct is None:
        return None
    if distance_pct < -0.80:
        return 0.12
    if distance_pct < 0:
        return 0.45 + ((distance_pct + 0.80) / 0.80) * 0.25
    if distance_pct <= 0.45:
        return 0.72 + (distance_pct / 0.45) * 0.28
    if distance_pct <= 1.20:
        return 1.0 - ((distance_pct - 0.45) / 0.75) * 0.40
    return max(0.30, 0.60 - (distance_pct - 1.20) * 0.12)


def component_or(state: str | None) -> float | None:
    if state is None:
        return None
    return OR_COMPONENT.get(state)


def component_pullback(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0 or value > 1:
        return None
    return float(value)


def component_relative_strength(pct: float | None) -> float | None:
    if pct is None:
        return None
    if pct < 0:
        return _clamp(0.30 + pct * 0.25)
    return _clamp(0.30 + pct * 0.70)


def component_liquidity(yen: float | None, curve: list) -> float | None:
    if yen is None:
        return None
    if yen < 0:
        return None
    floor, mid, high = (float(x) for x in curve)
    if yen < floor:
        return _clamp(0.15 + 0.25 * (yen / floor))
    if yen < mid:
        return 0.40 + 0.30 * ((yen - floor) / (mid - floor))
    if yen < high:
        return 0.70 + 0.30 * ((yen - mid) / (high - mid))
    return 1.0


def component_rank_velocity(ranks_per_minute: float | None) -> float | None:
    if ranks_per_minute is None:
        return None
    if ranks_per_minute <= 0:
        return _clamp(0.25 + ranks_per_minute * 0.05, 0.0, 0.25)
    return _clamp(0.25 + (ranks_per_minute / 6.0) * 0.75)


_COMPONENT = {
    "price_change_15s": component_price_change,
    "price_accel_45s": component_accel,
    "volume_surge_ratio": component_volume,
    "turnover_accel": component_turnover,
    "high_update_frequency": component_high_update,
    "vwap_position": component_vwap,
    "or5_state": component_or,
    "or15_state": component_or,
    "pullback_shallowness": component_pullback,
    "relative_strength": component_relative_strength,
}


def market_components(features: dict, config: dict) -> dict:
    """Return component scores. Unavailable features stay None."""

    components = {}
    invalid = []
    for name in MARKET_FEATURES:
        if name == "liquidity":
            value = component_liquidity(features.get(name), config["liquidity_curve_yen"])
            raw = features.get(name)
            if raw is not None and value is None:
                invalid.append(name)
            components[name] = value
            continue
        raw = features.get(name)
        if name in OR_FEATURES and raw in OR_UNOBSERVED_STATES:
            components[name] = None
            continue
        value = _COMPONENT[name](raw)
        if raw is not None and value is None:
            invalid.append(name)
        components[name] = value
    return {"components": components, "invalid_features": invalid}


def _or_reason(prefix: str, state: str | None, component: float | None, minimum: float) -> str | None:
    if component is None or component < minimum or state is None:
        return None
    if state == "ABOVE":
        return f"{prefix}_ABOVE"
    if state == "INSIDE":
        return f"{prefix}_INSIDE"
    return None


def score_market(features: dict, invalid_features: list[str], config: dict) -> dict:
    built = market_components(features, config)
    components = built["components"]
    invalid = list(dict.fromkeys([*invalid_features, *built["invalid_features"]]))
    weights = config["weights"]
    if invalid:
        return {
            "market_score": None,
            "score_status": "FAIL_CLOSED",
            "fail_closed": True,
            "reason_codes": ["FAIL_CLOSED", "INVALID_FEATURE", *sorted(set(invalid))],
            "components": components,
            "coverage": 0.0,
            "missing_features": [name for name, value in components.items() if value is None],
        }

    available_weight = 0.0
    weighted = 0.0
    missing = []
    for name in MARKET_FEATURES:
        component = components[name]
        weight = float(weights[name])
        if component is None:
            missing.append(name)
            continue
        available_weight += weight
        weighted += weight * component
    coverage = available_weight / 1.0
    required = [name for name in config.get("required_features") or [] if components.get(name) is None]
    if required or coverage < float(config["min_coverage"]):
        reasons = ["FAIL_CLOSED"]
        if required:
            reasons.append("MISSING_REQUIRED_FEATURE")
            reasons.extend(required)
        if coverage < float(config["min_coverage"]):
            reasons.append("INSUFFICIENT_FEATURE_COVERAGE")
        return {
            "market_score": None,
            "score_status": "FAIL_CLOSED",
            "fail_closed": True,
            "reason_codes": reasons,
            "components": components,
            "coverage": round(coverage, 6),
            "missing_features": missing,
        }

    market_score = round((weighted / available_weight) * 100, 4)
    minimum = float(config["reason_component_min"])
    reasons = []
    for name, code in REASON_BY_FEATURE.items():
        component = components[name]
        if code and component is not None and component >= minimum:
            reasons.append(code)
    for prefix, feature in (("OR5", "or5_state"), ("OR15", "or15_state")):
        code = _or_reason(prefix, features.get(feature), components[feature], minimum)
        if code:
            reasons.append(code)
    return {
        "market_score": market_score,
        "score_status": "PARTIAL",
        "fail_closed": False,
        "reason_codes": reasons,
        "components": components,
        "coverage": round(coverage, 6),
        "missing_features": missing,
    }


def apply_velocity(scored: dict, rank_velocity: float | None, config: dict) -> dict:
    """Blend rank velocity into the published NEXT score when it was observed."""

    if scored["fail_closed"]:
        scored["score"] = None
        scored["rank_velocity_component"] = None
        return scored
    component = component_rank_velocity(rank_velocity)
    scored["rank_velocity_component"] = component
    if component is None:
        scored["score"] = scored["market_score"]
        scored["score_status"] = "PARTIAL"
        return scored
    velocity_weight = float(config["velocity_weight"])
    blended = scored["market_score"] * (1 - velocity_weight) + (component * 100) * velocity_weight
    scored["score"] = round(blended, 4)
    scored["score_status"] = "COMPLETE"
    if component >= float(config["reason_component_min"]):
        scored["reason_codes"] = list(dict.fromkeys([*scored["reason_codes"], "RANK_VELOCITY_UP"]))
    return scored


def selection_value(score: float, velocity_component: float, score_weight: float, velocity_weight: float) -> float:
    return score_weight * (score / 100.0) + velocity_weight * velocity_component
