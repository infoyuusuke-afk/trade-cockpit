"""Opt-in Brain research judgment layer. Read-only, no runtime/order integration.

Consumes PR #461's private context as untrusted data, never instructions.
Only anonymous research-workflow decisions leave the layer. No last-good cache.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import stat

SOURCE_SCHEMA = "v10-brain-private-research-context-1"
SCHEMA = "v10-brain-research-judgment-1"
STATUS_NAME = "brain_research_context_v1.json"
MAX_BYTES = 65_536
MAX_AGE_SECONDS = 60
FLAGS = frozenset({
    "costs_verified", "broker_fills_verified", "tested_expectancy_available",
    "source_authenticated", "brain_trade_decision_eligible", "promotion_eligible",
    "real_submit_allowed",
})
KEYS = FLAGS | {
    "schema_version", "state", "reasons", "market_data_gate", "virtual_outcome_gate",
    "market_quote_at", "verified_board_row_count", "research_observation_counts",
    "strategy_statistics", "virtual_closed_clean_n", "virtual_closed_contaminated_n",
    "virtual_open_n", "data_lane",
}
STAT_KEYS = {
    "strategy_id", "virtual_n", "virtual_win_rate", "virtual_mean_r",
    "virtual_r_profit_factor", "research_sample_n_at_least_20",
}
COUNT_KEYS = {"OR15_ABOVE_VWAP_WATCH", "OR15_BELOW_VWAP_WATCH"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def _result(reason, *, decision="HOLD_RESEARCH", sample_count=None):
    return {
        "schema_version": SCHEMA,
        "state": "BLOCKED" if reason else "RESEARCH_OBSERVATION_ONLY",
        "reason": reason, "research_decision": decision,
        "virtual_sample_count": sample_count,
        "data_lane": "UNAUTHENTICATED_VIRTUAL_RESEARCH_NOT_EXECUTION",
        **{key: False for key in sorted(FLAGS)},
    }


def _count(value):
    return type(value) is int and 0 <= value <= 100_000


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def evaluate_context(context, *, now, file_modified_at):
    """Validate then choose only a research workflow, never a trade direction.

    >=20 is inherited sample bookkeeping, NOT statistical/EV validation.
    File timestamps and source self-claims cannot authenticate the source.
    """
    try:
        return _evaluate(context, now=now, file_modified_at=file_modified_at)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return _result("CONTEXT_INVALID")


def _evaluate(c, *, now, file_modified_at):
    if any(not isinstance(t, datetime) or t.utcoffset() is None
           for t in (now, file_modified_at)):
        return _result("CLOCK_UNVERIFIED")
    if type(c) is not dict or set(c) != KEYS:
        return _result("CONTEXT_SCHEMA_INVALID")
    if (c["schema_version"] != SOURCE_SCHEMA or
        c["state"] != "RESEARCH_OBSERVATION_ONLY" or c["reasons"] != [] or
        c["market_data_gate"] != "PASS" or c["virtual_outcome_gate"] != "PASS" or
        c["data_lane"] != "LOCAL_MS2_OBSERVATION_AND_VIRTUAL_RESEARCH" or
        any(c[key] is not False for key in FLAGS)):
        return _result("SOURCE_GATES_UNVERIFIED")
    quote = c["market_quote_at"]
    if type(quote) is not str or not ISO.fullmatch(quote):
        return _result("QUOTE_TIME_INVALID")
    quote_at = datetime.fromisoformat(quote.replace("Z", "+00:00"))
    # Fresh mtime never rescues a stale quote. No future-time tolerance.
    if any(not 0 <= (now - t).total_seconds() <= MAX_AGE_SECONDS
           for t in (quote_at, file_modified_at)) or quote_at > file_modified_at:
        return _result("CONTEXT_STALE_OR_FUTURE")
    if type(c["verified_board_row_count"]) is not int or c["verified_board_row_count"] != 100:
        return _result("BOARD_INCOMPLETE")
    counts = c["research_observation_counts"]
    if (type(counts) is not dict or set(counts) != COUNT_KEYS or
        any(not _count(v) for v in counts.values()) or sum(counts.values()) > 100):
        return _result("OBSERVATION_COUNTS_INVALID")
    totals = [c[k] for k in ("virtual_closed_clean_n", "virtual_closed_contaminated_n", "virtual_open_n")]
    if any(not _count(v) for v in totals) or sum(totals) > 100_000:
        return _result("OUTCOME_COUNTS_INVALID")
    rows = c["strategy_statistics"]
    if type(rows) is not list or len(rows) > 1000:
        return _result("STATISTICS_INVALID")
    names, total, small = set(), 0, False
    for row in rows:
        if type(row) is not dict or set(row) != STAT_KEYS:
            return _result("STATISTICS_INVALID")
        name, n = row["strategy_id"], row["virtual_n"]
        if (type(name) is not str or not 1 <= len(name) <= 100 or name != name.strip() or
            any(not ch.isprintable() or ch in "/\\" for ch in name) or name in names or
            not _count(n) or n == 0):
            return _result("STRATEGY_ID_OR_SAMPLE_INVALID")
        names.add(name)
        win, mean, pf = (row[k] for k in ("virtual_win_rate", "virtual_mean_r", "virtual_r_profit_factor"))
        if (not _number(win) or not 0 <= win <= 1 or not _number(mean) or
            (pf is not None and (not _number(pf) or pf < 0)) or
            row["research_sample_n_at_least_20"] is not (n >= 20)):
            return _result("STATISTIC_VALUE_INVALID")
        total += n
        small |= n < 20
    if total != c["virtual_closed_clean_n"]:
        return _result("SAMPLE_TOTAL_MISMATCH")
    if c["virtual_closed_contaminated_n"]:
        decision = "REVIEW_CONTAMINATED_VIRTUAL_DATA"
    elif not rows or small:
        decision = "COLLECT_MORE_VIRTUAL_SAMPLES"
    else:
        decision = "REVIEW_VIRTUAL_RESEARCH_ONLY"
    return _result(None, decision=decision, sample_count=total)


def _identity(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)


def _plain_local(path):
    # Reject UNC/device paths before any filesystem access, including on Windows.
    if not path.is_absolute() or str(path).startswith(("\\\\", "//")) or ".." in path.parts:
        raise ValueError("PATH")
    if os.name == "nt" and (path.drive.startswith("\\") or ":" in str(path)[2:]):
        raise ValueError("PATH")
    for p in (path, *path.parents):
        s = p.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
            raise ValueError("LINK_OR_REPARSE")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_KEY")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("NONFINITE_JSON")


def consume_local(*, context_path, private_dir, now):
    """Read one explicitly selected private file. Never write/cache raw context.

    Local directory is an explicit owner selection, not a privacy/authenticity
    attestation. No file discovery, remote paths, runtime startup or publication.
    """
    try:
        path, root = Path(context_path), Path(private_dir)
        if path.name != STATUS_NAME or path.parent != root:
            return _result("PRIVATE_PATH_BOUNDARY_INVALID")
        _plain_local(root)
        _plain_local(path)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 2 <= before.st_size <= MAX_BYTES:
            return _result("CONTEXT_FILE_INVALID")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _identity(before) != _identity(opened):
                return _result("CONTEXT_CHANGED_DURING_READ")
            raw = handle.read(MAX_BYTES + 1)
            closed = os.fstat(handle.fileno())
        _plain_local(path)
        after = path.lstat()
        if (len(raw) != before.st_size or _identity(before) != _identity(closed) or
            _identity(before) != _identity(after)):
            return _result("CONTEXT_CHANGED_DURING_READ")
        context = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant)
        return evaluate_context(context, now=now,
                                file_modified_at=datetime.fromtimestamp(before.st_mtime, timezone.utc))
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        return _result("LOCAL_CONTEXT_UNAVAILABLE_OR_INVALID")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Brain research judgment; no orders")
    parser.add_argument("--context", required=True)
    parser.add_argument("--private-dir", required=True)
    args = parser.parse_args(argv)
    result = consume_local(context_path=args.context, private_dir=args.private_dir,
                           now=datetime.now(timezone.utc))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 2 if result["state"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
