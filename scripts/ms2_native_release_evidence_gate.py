"""Offline release-cut gate for native MS2 Bridge/Writer synthetic aggregates.

Never authorizes a real Collector, trading, or Q2/Q3 PIT. All output contains
anonymous summary counts, durations, status and fixed reason codes only.
"""
from __future__ import annotations
import math
from typing import Any

VERSION = "ms2-native-release-evidence-gate-0.1"
TARGET_MAX_MS = 5.0
MIN_ATTEMPTS = 16


def _nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _finite_nonnegative(value: Any) -> bool:
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def classify(report: Any) -> dict:
    """Conservatively review an existing actual-Writer synthetic pipeline report."""
    counts = dict(attempts=None, queued=None, drops=None, persisted_readback=None)
    out = {
        "schema_version": VERSION,
        "status": "EVIDENCE_INVALID",
        "boundary": "SYNTHETIC_NATIVE_PIPELINE_ONLY",
        "counts": counts,
        "full_boundary": {"n": None, "p99_ms": None, "max_ms": None},
        "latency_anatomy": {"status": "UNVERIFIED", "n": None, "over_5ms_count": None,
                            "slowest_full_ms": None, "slowest_components_ms": None,
                            "largest_measured_component_at_peak": "UNKNOWN"},
        "reasons": [],
        "readback_count_consistent": False,
        "normal_no_drop": False,
        "max_five_ms_observed": False,
        "source_authenticated": False,
        "pit_research_eligible": False,
        "shadow_forward_eligible": False,
        "release_eligible": False,
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
    }
    if not isinstance(report, dict):
        out["reasons"] = ["REPORT_INVALID"]
        return out
    reasons = []
    if report.get("mode") != "normal":
        reasons.append("NORMAL_COHORT_REQUIRED")
    if report.get("producer") != "Native_PS5.1" or not str(report.get("ps", "")).startswith("5.1."):
        reasons.append("NATIVE_PROCESS_UNVERIFIED")
    if report.get("production") != "P0_BLOCKED":
        reasons.append("PRODUCTION_STATE_UNAUTHORIZED")
    if report.get("five_ms") != "NOT_MET":
        reasons.append("PERFORMANCE_STATE_UNAUTHORIZED")
    if report.get("close_state") != "NOT_CLOSED" or report.get("receipt_tail") != "NOT_CLOSED":
        reasons.append("EVIDENCE_CLOSURE_STATE_UNAUTHORIZED")
    if report.get("concurrent_completion_observed") is not True:
        reasons.append("ACTUAL_WRITER_OVERLAP_NOT_OBSERVED")
    if report.get("restart_new_generation_no_replay") is not True:
        reasons.append("RESTART_NO_REPLAY_UNVERIFIED")
    for name in counts:
        value = report.get(name) if name != "persisted_readback" else (
            report.get("states", {}).get("PERSISTED_VERIFIED") if isinstance(report.get("states"), dict) else None
        )
        if not _nonnegative_int(value):
            reasons.append("COUNT_INVALID_" + name.upper())
        else:
            counts[name] = value
    if all(v is not None for v in counts.values()):
        if counts["queued"] + counts["drops"] != counts["attempts"]:
            reasons.append("ATTEMPTS_NOT_ACCOUNTED")
        out["readback_count_consistent"] = counts["queued"] == counts["persisted_readback"]
        if not out["readback_count_consistent"]:
            reasons.append("ACCEPTED_VS_READBACK_CONFLICT")
        if counts["attempts"] < MIN_ATTEMPTS:
            reasons.append("SYNTHETIC_COHORT_TOO_SMALL")
        out["normal_no_drop"] = counts["attempts"] >= MIN_ATTEMPTS and counts["drops"] == 0
        if counts["drops"] != 0:
            reasons.append("NORMAL_DROP_DETECTED")
        if counts["queued"] == 0:
            reasons.append("NO_QUEUED_RECORDS")
    cohorts = report.get("cohorts")
    steady = cohorts.get("steady_ACCEPTED") if isinstance(cohorts, dict) else None
    metric = steady.get("full_ms") if isinstance(steady, dict) else None
    if isinstance(metric, dict) and all(
        _nonnegative_int(metric.get("N")) if key == "N" else _finite_nonnegative(metric.get(key))
        for key in ("N", "p99_ms", "max_ms")
    ) and metric["p99_ms"] <= metric["max_ms"]:
        out["full_boundary"] = dict(n=metric["N"], p99_ms=metric["p99_ms"], max_ms=metric["max_ms"])
        if metric["N"] < MIN_ATTEMPTS - 1:
            reasons.append("STEADY_SAMPLES_INSUFFICIENT")
        out["max_five_ms_observed"] = metric["N"] >= MIN_ATTEMPTS - 1 and metric["max_ms"] <= TARGET_MAX_MS
        if metric["max_ms"] > TARGET_MAX_MS:
            reasons.append("MAX_FIVE_MS_FAILED")
    else:
        reasons.append("LATENCY_EVIDENCE_MISSING_OR_INVALID")
    anatomy = report.get("latency_anatomy")
    if (
        isinstance(anatomy, dict)
        and anatomy.get("status") == "SYNTHETIC_SEGMENTS_REPORTED_ONLY"
        and _nonnegative_int(anatomy.get("n"))
        and _nonnegative_int(anatomy.get("over_5ms_count"))
        and _finite_nonnegative(anatomy.get("slowest_full_ms"))
        and isinstance(anatomy.get("slowest_components_ms"), dict)
        and anatomy.get("os_root_cause_proven") is False
        and anatomy.get("production_latency_bound_proven") is False
    ):
        components = anatomy["slowest_components_ms"]
        fields = ("capture_ms", "packing_ms", "submit_ms", "unattributed_ms")
        if (
            all(_finite_nonnegative(components.get(k)) for k in fields)
            and anatomy.get("largest_measured_component_at_peak") in fields
            and anatomy["over_5ms_count"] <= anatomy["n"]
            and anatomy["n"] == out["full_boundary"]["n"]
            and out["full_boundary"]["max_ms"] is not None
            and abs(anatomy["slowest_full_ms"] - out["full_boundary"]["max_ms"]) <= 0.001
            and abs(sum(components[k] for k in fields) - anatomy["slowest_full_ms"]) <= 0.051
        ):
            out["latency_anatomy"] = {
                "status": "SYNTHETIC_CORRELATED_TIMING_ONLY",
                "n": anatomy["n"],
                "over_5ms_count": anatomy["over_5ms_count"],
                "slowest_full_ms": anatomy["slowest_full_ms"],
                "slowest_components_ms": {k: components[k] for k in fields},
                "largest_measured_component_at_peak": anatomy["largest_measured_component_at_peak"],
            }
        else:
            reasons.append("CORRELATED_STAGE_EVIDENCE_INCONSISTENT")
    else:
        reasons.append("CORRELATED_STAGE_EVIDENCE_MISSING")
    for name in ("Writer_fsync", "verified_readback", "receipt_to_verified_readback_upper_bound"):
        item = report.get(name)
        if not isinstance(item, dict) or not _nonnegative_int(item.get("N")) or item["N"] == 0:
            reasons.append("MISSING_WRITER_EVIDENCE_" + name.upper())
    # Source authenticity, accurate available-at, private W1-W4 and true fills
    # are never attested by a synthetic Writer, even when counts/latency agree.
    reasons.extend((
        "REAL_COLLECTOR_NOT_CONNECTED", "SOURCE_AUTHENTICITY_UNPROVEN",
        "POINT_IN_TIME_UNPROVEN", "SAME_USER_AUTH_UNVERIFIED",
        "POWER_LOSS_RECOVERY_UNVERIFIED", "REAL_TRADING_NOT_AUTHORIZED",
    ))
    hard = {"NORMAL_COHORT_REQUIRED", "NATIVE_PROCESS_UNVERIFIED", "PRODUCTION_STATE_UNAUTHORIZED",
            "PERFORMANCE_STATE_UNAUTHORIZED", "EVIDENCE_CLOSURE_STATE_UNAUTHORIZED",
            "ACTUAL_WRITER_OVERLAP_NOT_OBSERVED", "RESTART_NO_REPLAY_UNVERIFIED",
            "ATTEMPTS_NOT_ACCOUNTED", "ACCEPTED_VS_READBACK_CONFLICT",
            "LATENCY_EVIDENCE_MISSING_OR_INVALID",
            "CORRELATED_STAGE_EVIDENCE_INCONSISTENT", "CORRELATED_STAGE_EVIDENCE_MISSING"}
    if hard.isdisjoint(reasons) and not any(reason.startswith("COUNT_INVALID_") for reason in reasons):
        out["status"] = "SYNTHETIC_EVIDENCE_CLASSIFIED_ONLY"
    out["reasons"] = sorted(set(reasons))
    return out
