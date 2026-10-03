"""Calibration helpers for the KIOXIA forecast-first redesign.

This module deliberately does not invent today's forecast. It only:
- summarizes evaluated forecast history,
- computes uncertainty around historical hit rate,
- validates externally produced scenario probabilities,
- enforces the rule that a confidence percentage is hidden when the
  effective sample is below a configured threshold.

The forecasting model itself remains a separate concern.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

DEFAULT_MIN_SAMPLE = 20
ALLOWED_SCENARIOS = {
    "YORITEN",
    "YORIZOKO",
    "GU_CONTINUATION",
    "GD_REBOUND",
    "RANGE",
    "SPECIAL_QUOTE_DELAY",
    "UNKNOWN",
}


def _num(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if not math.isfinite(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def wilson_interval(successes: int, total: int, *, z: float = 1.96) -> tuple[Optional[float], Optional[float]]:
    """Return the Wilson score interval as percentages."""
    if total <= 0 or successes < 0 or successes > total:
        return None, None

    p = successes / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denominator
    half = (
        z
        * math.sqrt((p * (1.0 - p) / total) + z2 / (4.0 * total * total))
        / denominator
    )
    return max(0.0, (center - half) * 100.0), min(100.0, (center + half) * 100.0)


def evaluated_records(records: Iterable[dict]) -> list[dict]:
    """Return only records that have an observed outcome.

    The current history file stores direction_hit and actual_close_ret after
    evaluation. Missing outcomes must not be silently treated as misses.
    """
    out = []
    for record in records:
        hit = record.get("direction_hit")
        actual = _num(record.get("actual_close_ret"))
        if isinstance(hit, bool) and actual is not None:
            out.append(record)
    return out


def summarize_history(records: Iterable[dict], *, min_sample: int = DEFAULT_MIN_SAMPLE) -> dict:
    rows = evaluated_records(records)
    sample = len(rows)
    hits = sum(1 for row in rows if row.get("direction_hit") is True)
    hit_rate = (hits / sample * 100.0) if sample else None
    wilson_low, wilson_high = wilson_interval(hits, sample)

    abs_errors = [_num(row.get("absolute_error")) for row in rows]
    abs_errors = [value for value in abs_errors if value is not None]

    path_fits = [_num(row.get("path_fit")) for row in rows]
    path_fits = [value for value in path_fits if value is not None]

    similarities = [_num(row.get("similarity")) for row in rows]
    similarities = [value for value in similarities if value is not None]

    return {
        "sample_n": sample,
        "direction_hits": hits,
        "direction_hit_rate_pct": hit_rate,
        "wilson_95_low_pct": wilson_low,
        "wilson_95_high_pct": wilson_high,
        "mean_absolute_error_pct": (
            sum(abs_errors) / len(abs_errors) if abs_errors else None
        ),
        "mean_path_fit": (
            sum(path_fits) / len(path_fits) if path_fits else None
        ),
        "mean_similarity": (
            sum(similarities) / len(similarities) if similarities else None
        ),
        "confidence_status": (
            "CALIBRATION_READY" if sample >= min_sample else "INSUFFICIENT_SAMPLE"
        ),
        "min_sample": min_sample,
    }


def validate_scenario_probabilities(items: Iterable[dict], *, tolerance: float = 0.5) -> dict:
    """Validate a scenario-probability list without renormalizing it.

    Silent renormalization can hide upstream bugs, so invalid inputs are
    rejected and the caller must fix them.
    """
    rows = list(items)
    if not rows:
        return {"valid": False, "reason": "EMPTY", "sum_pct": 0.0}

    seen = set()
    total = 0.0

    for row in rows:
        scenario = str(row.get("scenario") or "").strip()
        if scenario not in ALLOWED_SCENARIOS:
            return {
                "valid": False,
                "reason": "UNKNOWN_SCENARIO",
                "scenario": scenario,
                "sum_pct": total,
            }
        if scenario in seen:
            return {
                "valid": False,
                "reason": "DUPLICATE_SCENARIO",
                "scenario": scenario,
                "sum_pct": total,
            }
        seen.add(scenario)

        probability = _num(row.get("probability_pct"))
        if probability is None or probability < 0.0 or probability > 100.0:
            return {
                "valid": False,
                "reason": "INVALID_PROBABILITY",
                "scenario": scenario,
                "sum_pct": total,
            }
        total += probability

    if abs(total - 100.0) > tolerance:
        return {
            "valid": False,
            "reason": "SUM_NOT_100",
            "sum_pct": total,
        }

    return {"valid": True, "reason": "OK", "sum_pct": total}


def display_confidence(
    *,
    selected_scenario_probability_pct: Optional[float],
    history_summary: dict,
) -> dict:
    """Gate today's displayed confidence by calibration readiness.

    The selected scenario probability comes from the forecasting model.
    Historical hit rate is not substituted for it.
    """
    status = str(history_summary.get("confidence_status") or "")
    if status != "CALIBRATION_READY":
        return {
            "confidence_pct": None,
            "confidence_status": "INSUFFICIENT_SAMPLE",
            "sample_n": history_summary.get("sample_n"),
            "historical_hit_rate_pct": history_summary.get("direction_hit_rate_pct"),
            "wilson_95_low_pct": history_summary.get("wilson_95_low_pct"),
            "wilson_95_high_pct": history_summary.get("wilson_95_high_pct"),
        }

    probability = _num(selected_scenario_probability_pct)
    if probability is None or probability < 0.0 or probability > 100.0:
        return {
            "confidence_pct": None,
            "confidence_status": "INVALID_MODEL_OUTPUT",
            "sample_n": history_summary.get("sample_n"),
            "historical_hit_rate_pct": history_summary.get("direction_hit_rate_pct"),
            "wilson_95_low_pct": history_summary.get("wilson_95_low_pct"),
            "wilson_95_high_pct": history_summary.get("wilson_95_high_pct"),
        }

    return {
        "confidence_pct": probability,
        "confidence_status": "CALIBRATED",
        "sample_n": history_summary.get("sample_n"),
        "historical_hit_rate_pct": history_summary.get("direction_hit_rate_pct"),
        "wilson_95_low_pct": history_summary.get("wilson_95_low_pct"),
        "wilson_95_high_pct": history_summary.get("wilson_95_high_pct"),
    }
