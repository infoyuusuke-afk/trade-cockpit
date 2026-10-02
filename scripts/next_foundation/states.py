"""Operational NEXT states, with a slot for the later life cycle.

Phase 1 states:
    WATCH, PRE_NEXT, IGNITION, CONFIRMED, COOLING

Reserved life cycle, not fully classified in this phase:
    PRE_IGNITION → IGNITION → EXPANSION → TREND → MATURE → EXHAUSTION

TREND and MATURE are never emitted here. COOLING and CONFIRMED use the
nearest reserved phase and are marked as aliases.
"""

from __future__ import annotations

OPERATIONAL_STATES = ("WATCH", "PRE_NEXT", "IGNITION", "CONFIRMED", "COOLING")
LIFECYCLE_PHASES = (
    "PRE_IGNITION",
    "IGNITION",
    "EXPANSION",
    "TREND",
    "MATURE",
    "EXHAUSTION",
)

_LIFECYCLE = {
    "WATCH": ("PRE_IGNITION", True),
    "PRE_NEXT": ("PRE_IGNITION", True),
    "IGNITION": ("IGNITION", False),
    "CONFIRMED": ("EXPANSION", True),
    "COOLING": ("EXHAUSTION", True),
}


def assign_state(row: dict, previous: dict | None, config: dict) -> dict:
    """Return state fields. Fail-closed rows are not given a trading state."""

    if row.get("fail_closed") or row.get("funnel") not in ("ACTIVE100", "NEXT20", "NEXT5"):
        return _empty_state()
    rules = config["states"]
    prev_state = (previous or {}).get("state")
    prev_consec = int((previous or {}).get("consecutive_ignition") or 0)
    peak = (previous or {}).get("peak_score")
    score = row.get("score")
    velocity = row.get("rank_velocity")
    accel = (row.get("features") or {}).get("price_accel_45s")
    reasons = set(row.get("reason_codes") or [])

    if prev_state in ("IGNITION", "CONFIRMED", "PRE_NEXT") and score is not None:
        dropped = peak is not None and (float(peak) - float(score)) >= float(rules["cooling_score_drop"])
        fading = velocity is not None and velocity <= float(rules["cooling_max_rank_velocity"])
        rolling_over = accel is not None and accel < 0 and prev_state in ("IGNITION", "CONFIRMED")
        if dropped or fading or rolling_over:
            return _pack("COOLING", 0, score, previous)

    triggers = reasons.intersection(set(rules["ignition_reasons"]))
    ignition = (
        score is not None
        and score >= float(rules["ignition_min_score"])
        and len(triggers) >= int(rules["ignition_min_trigger_reasons"])
    )
    if ignition:
        consec = prev_consec + 1 if prev_state in ("IGNITION", "CONFIRMED", "PRE_NEXT") else 1
        velocity_ok = velocity is not None and velocity >= float(rules["confirm_min_rank_velocity"])
        if (
            consec >= int(rules["confirm_min_consecutive"])
            and score >= float(rules["confirm_min_score"])
            and velocity_ok
        ):
            return _pack("CONFIRMED", consec, score, previous)
        return _pack("IGNITION", consec, score, previous)

    precursors = reasons.intersection(set(rules["precursor_reasons"]))
    if row.get("funnel") in ("NEXT20", "NEXT5") and score is not None and score >= float(rules["pre_next_min_score"]) and precursors:
        return _pack("PRE_NEXT", 0, score, previous)
    return _pack("WATCH", 0, score, previous, reset_peak=prev_state != "WATCH")


def _peak(score: float | None, previous: dict | None, reset: bool):
    if score is None:
        return None
    prior = None if not previous else previous.get("peak_score")
    if reset or prior is None:
        return score
    return max(float(prior), float(score))


def _pack(state: str, consecutive: int, score: float | None, previous: dict | None = None, reset_peak: bool = False) -> dict:
    lifecycle, alias = _LIFECYCLE[state]
    return {
        "state": state,
        "consecutive_ignition": consecutive,
        "peak_score": _peak(score, previous, reset_peak),
        "lifecycle_state": lifecycle,
        "lifecycle_alias": alias,
        "lifecycle_phases": list(LIFECYCLE_PHASES),
    }


def _empty_state() -> dict:
    return {
        "state": None,
        "consecutive_ignition": 0,
        "peak_score": None,
        "lifecycle_state": None,
        "lifecycle_alias": False,
        "lifecycle_phases": list(LIFECYCLE_PHASES),
    }
