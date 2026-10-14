"""Existing native PS5.1 Bridge/Writer with repeated anonymized timing cohorts.

Only synthetic input. No OWNER data, Collector, MS2/Excel, canonical/hash change.
Never equate a synthetic release-evidence test with an executable live gate.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

from scripts.ms2_native_release_evidence_gate import classify
from tests.ms2_concurrent_pipeline import run


def _metrics(value):
    """Select only timing statistics; never return raw fixture or source keys."""
    if not isinstance(value, dict):
        return {"status": "NOT_VERIFIED"}
    allowed = ("N", "p50_ms", "p95_ms", "p99_ms", "max_ms")
    return {key: value[key] for key in allowed if key in value}


def _cohorts(report):
    c = report.get("cohorts", {})
    b = c.get("steady_ACCEPTED", {}) if isinstance(c, dict) else {}
    first = c.get("first_submit", {}) if isinstance(c, dict) else {}
    return {
        "cold_start": _metrics(report.get("cold_start")),
        "first_warmup": _metrics(report.get("first_warmup")),
        "first_submit": {k: _metrics(first.get(k)) for k in
                         ("capture_ms", "packing_ms", "submit_ms", "full_ms")},
        "steady_ACCEPTED": {k: _metrics(b.get(k)) for k in
                            ("capture_ms", "packing_ms", "submit_ms", "full_ms")},
        "writer_fsync": _metrics(report.get("Writer_fsync")),
        "independent_readback": _metrics(report.get("verified_readback")),
        "receipt_to_verified_readback_upper_bound": _metrics(
            report.get("receipt_to_verified_readback_upper_bound")),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int)
    parser.add_argument("--attempts", type=int)
    args = parser.parse_args(argv)
    native = os.name == "nt"
    repeats = args.runs if args.runs is not None else (3 if native else 1)
    n = args.attempts if args.attempts is not None else (48 if native else 24)
    if not 1 <= repeats <= 4 or not 16 <= n <= 100:
        print(json.dumps({"status": "ARGUMENTS_REFUSED", "real_submit_allowed": False}))
        return 2
    statuses = []
    for iteration in range(1, repeats + 1):
        try:
            report = run(mode="normal", n=n, native=native)
        except Exception as exc:
            # Never emit an exception's raw str(): synthetic payloads, temp
            # paths, hashes or private paths could be included in failures.
            # Restrict traceback to a known public fixture's final frame.
            frames = traceback.extract_tb(exc.__traceback__)
            safe = next((item for item in reversed(frames)
                         if item.filename.replace("\\\\", "/").endswith(
                             "/tests/ms2_concurrent_pipeline.py")), None)
            print(json.dumps({
                "status": "SYNTHETIC_RUN_FAILED",
                "iteration": iteration,
                "error_type": type(exc).__name__,
                "fixture_line": safe.lineno if safe else None,
                "fixture_function": safe.name if safe else "UNKNOWN",
                "release_eligible": False,
                "real_submit_allowed": False,
            }, sort_keys=True))
            return 1
        gate = classify(report)
        result = {
            "iteration": iteration,
            "run_kind": "Native_PS5.1" if native else "Linux_protocol_fixture",
            "gate": gate,
            "timing_cohorts": _cohorts(report),
            "measured_os_worst_case": False,
            "proven_source_authenticity": False,
            "real_submit_allowed": False,
        }
        print(json.dumps(result, ensure_ascii=True, sort_keys=True), flush=True)
        statuses.append(gate)
        if gate["release_eligible"] or gate["real_submit_allowed"]:
            return 1
        if native:
            if gate["status"] != "SYNTHETIC_EVIDENCE_CLASSIFIED_ONLY":
                return 1
            if gate["counts"]["persisted_readback"] != gate["counts"]["queued"]:
                return 1
            if gate["counts"]["queued"] is None or gate["counts"]["queued"] < 1:
                return 1
        else:
            if "NATIVE_PROCESS_UNVERIFIED" not in gate["reasons"]:
                return 1
    print(json.dumps({
        "status": "REPEATED_SYNTHETIC_DIAGNOSTIC_ONLY",
        "runs": len(statuses),
        "no_drop_all_runs": all(x["normal_no_drop"] for x in statuses),
        "max_five_ms_all_runs": all(x["max_five_ms_observed"] for x in statuses),
        "readback_count_consistent_all_runs": all(
            x["readback_count_consistent"] for x in statuses),
        "production": "P0_BLOCKED",
        "release_eligible": False,
        "real_submit_allowed": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
