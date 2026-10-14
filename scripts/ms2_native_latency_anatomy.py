"""Offline synthetic-only stage correlation for Native PS5.1 Producer timing.

NEVER use aggregate maxima from different samples to attribute a slow poll.
The measured full boundary includes capture, packing and submit; any residual
is labelled UNATTRIBUTED, not necessarily an OS scheduler stall.
No source/ticker/timestamp/raw sample/identifier is returned.
"""
from __future__ import annotations
import math

VERSION = "ms2-native-latency-anatomy-0.1"
FIELDS = ("capture_ms", "packing_ms", "submit_ms", "full_ms")
TARGET_MS = 5.0


def diagnose(samples):
    out = {
        "schema_version": VERSION, "status": "EVIDENCE_INVALID",
        "cohort": "steady_ACCEPTED_SYNTHETIC_ONLY",
        "n": 0, "over_5ms_count": None,
        "slowest_full_ms": None,
        "slowest_components_ms": None,
        "largest_measured_component_at_peak": "UNKNOWN",
        "os_root_cause_proven": False,
        "production_latency_bound_proven": False,
        "reason_codes": [],
    }
    if not isinstance(samples, list) or len(samples) < 2:
        out["reason_codes"] = ["SAMPLES_MISSING_OR_TOO_FEW"]
        return out
    rows = []
    for row in samples[1:]:  # first submit is a distinct cold/warm cohort
        if not isinstance(row, dict) or row.get("state") != "ACCEPTED":
            continue
        if any(type(row.get(k)) not in (int, float) or
               not math.isfinite(row[k]) or row[k] < 0 for k in FIELDS):
            out["reason_codes"] = ["TIMING_SAMPLE_INVALID"]
            return out
        components = sum(row[k] for k in FIELDS[:3])
        # All segment stopwatches are sequential and in the full stopwatch.
        # Small differences (float/timer quantization) must not claim negative time.
        if components > row["full_ms"] + 0.05:
            out["reason_codes"] = ["TIMING_COMPONENTS_EXCEED_FULL"]
            return out
        rows.append(row)
    if not rows:
        out["reason_codes"] = ["NO_ACCEPTED_STEADY_SAMPLES"]
        return out
    peak = max(rows, key=lambda row: row["full_ms"])
    residue = max(0.0, peak["full_ms"] - sum(peak[k] for k in FIELDS[:3]))
    components = {
        "capture_ms": round(peak["capture_ms"], 6),
        "packing_ms": round(peak["packing_ms"], 6),
        "submit_ms": round(peak["submit_ms"], 6),
        "unattributed_ms": round(residue, 6),
    }
    dominant = max(components, key=components.get)
    out.update(
        status="SYNTHETIC_SEGMENTS_REPORTED_ONLY",
        n=len(rows),
        over_5ms_count=sum(row["full_ms"] > TARGET_MS for row in rows),
        slowest_full_ms=round(peak["full_ms"], 6),
        slowest_components_ms=components,
        largest_measured_component_at_peak=dominant,
        reason_codes=[
            "CORRELATION_DOES_NOT_PROVE_OS_ROOT_CAUSE",
            "PRODUCER_OBSERVATION_NOT_REAL_MS2",
            "UNMEASURED_SCHEDULING_AND_JITTER",
        ],
    )
    return out
