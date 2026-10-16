"""MS2 synthetic/offline cross-file alignment diagnostic; NEVER a PIT attestation.

Only fixed local CSVs; no writes, network, raw rows, ticker labels or paths
in outputs. Q1 is a prerequisite. Equal keys are not poll IDs.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path

from scripts import ms2_records_quality as q1

INDEX_FILES = (
    "market_snapshots.csv",
    "condition_log.csv",
    "under_over.csv",
    "trade_signals.csv",
)
MAX_UNIQUE_KEYS = 300_000
SCHEMA_VERSION = "ms2-offline-candidate-join-v1"


class ProbeBlocked(Exception):
    def __init__(self, code: str):
        self.code = code


def _read_keys(root: Path, name: str) -> Counter:
    """Return ephemeral private local key counts; never emit ticker or time."""
    path = root / name
    try:
        if q1._link(path):
            raise ProbeBlocked("LINK_REFUSED")
        before = q1._stat_key(path.stat())
        counts = Counter()
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as f:
            file_before = q1._stat_key(os.fstat(f.fileno()))
            reader = csv.DictReader(f, restkey="__extra_columns__", strict=True)
            if tuple(reader.fieldnames or ()) != q1.HEADERS[name]:
                raise ProbeBlocked("HEADER_CONTRACT_MISMATCH")
            for number, row in enumerate(reader, start=1):
                if number > q1.MAX_ROWS:
                    raise ProbeBlocked("ROW_LIMIT_EXCEEDED")
                if "__extra_columns__" in row or any(v is None for v in row.values()):
                    raise ProbeBlocked("ROW_SHAPE_INVALID")
                key = (row["ticker"], row["captured_at"])
                counts[key] += 1
                if len(counts) > MAX_UNIQUE_KEYS:
                    raise ProbeBlocked("KEY_INDEX_CAPACITY_EXCEEDED")
            file_after = q1._stat_key(os.fstat(f.fileno()))
        after = q1._stat_key(path.stat())
        if (before != after or file_before != file_after or
            before[:3] != file_before[:3] or after[:3] != file_after[:3]):
            raise ProbeBlocked("SOURCE_CHANGED_DURING_READ")
        return counts
    except (OSError, UnicodeError, csv.Error, ValueError, OverflowError) as error:
        raise ProbeBlocked("CSV_READ_OR_PARSE_FAILED") from error


def inspect(day_dir: str | Path) -> dict:
    """Diagnostic counts only; never returns the ephemeral symbol-time join keys."""
    out = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED",
        "source_attribution": "UNVERIFIED_NO_EMBEDDED_PRODUCER_OR_SESSION_PROOF",
        "poll_join_proven": False,
        "decision_asof_proven": False,
        "future_leak_excluded": False,
        "pit_research_eligible": False,
        "shadow_forward_eligible": False,
        "performance_eligible": False,
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "reason_codes": [],
    }
    result = q1.audit(day_dir)
    if result["status"] != "Q1_PARSED_ONLY":
        out["reason_codes"].append("Q1_NOT_PASSED")
        out["q1_fail_files_count"] = sum(
            item["status"] != "Q1_PARSED_ONLY" for item in result["files"].values()
        )
        return out

    root = Path(day_dir)
    index = {}
    try:
        for name in INDEX_FILES:
            index[name] = _read_keys(root, name)
    except ProbeBlocked as error:
        out["reason_codes"].append(error.code)
        return out

    snapshots = index["market_snapshots.csv"]
    conditions = index["condition_log.csv"]
    orderflow = index["under_over.csv"]
    signals = index["trade_signals.csv"]
    all_keys = snapshots.keys() | conditions.keys() | orderflow.keys()
    triple_one = sum(
        snapshots[key] == conditions[key] == orderflow[key] == 1
        for key in all_keys
    )
    multiple = sum(
        max(snapshots[key], conditions[key], orderflow[key]) > 1
        for key in all_keys
    )
    incomplete = sum(
        not (snapshots[key] and conditions[key] and orderflow[key])
        for key in all_keys
    )
    max_missing = {
        label: sum(key not in mapping for key in all_keys)
        for label, mapping in [
            ("snapshot", snapshots), ("condition", conditions), ("under_over", orderflow)
        ]
    }
    signal_unique = sum(count for key, count in signals.items() if snapshots[key] == 1)
    signal_missing = sum(count for key, count in signals.items() if snapshots[key] == 0)
    signal_ambiguous = sum(count for key, count in signals.items() if snapshots[key] > 1)
    repeated_signals = sum(count - 1 for count in signals.values() if count > 1)

    out["diagnostics"] = {
        "snapshot_rows": sum(snapshots.values()),
        "condition_rows": sum(conditions.values()),
        "under_over_rows": sum(orderflow.values()),
        "signal_rows": sum(signals.values()),
        "triplet_unique_candidate_keys": triple_one,
        "triplet_multirow_ambiguous_keys": multiple,
        "triplet_incomplete_keys": incomplete,
        "missing_source_keys": max_missing,
        "signals_with_one_snapshot_key_candidate": signal_unique,
        "signals_with_no_snapshot_key_candidate": signal_missing,
        "signals_with_multiple_snapshot_key_candidates": signal_ambiguous,
        "repeated_signal_key_rows": repeated_signals,
    }
    if multiple or incomplete or signal_missing or signal_ambiguous or repeated_signals:
        out["reason_codes"].append("CROSS_FILE_KEY_INCOMPLETE_OR_AMBIGUOUS")
    out["reason_codes"].extend([
        "NO_SHARED_POLL_OR_SOURCE_SESSION_ID",
        "TIMESTAMPS_LOCAL_WITHOUT_PROVEN_AVAILABLE_AT",
        "SAME_KEY_NOT_PROOF_OF_CAUSAL_FEATURE_AVAILABILITY",
        "SIGNAL_ASOF_DEPENDENCIES_UNPROVEN",
    ])
    out["status"] = "CANDIDATE_DIAGNOSTIC_ONLY"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Private MS2 candidate join diagnostic, offline and read-only")
    parser.add_argument("--day-dir", required=True, help="Explicit day folder; path is not printed")
    args = parser.parse_args()
    result = inspect(args.day_dir)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    # Even complete candidate alignment cannot promote a source to PIT eligible.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
