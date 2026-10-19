"""Explicit read-only research sidecar for V10 Brain observer status.

Never modifies pinned V10 observer, Controller, source files, UI or trade path.
No source authentication, validated expectancy or order eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat

from scripts import v10_brain_research_consumer as consumer

SCHEMA = "v10-brain-research-optin-sidecar-1"
BRAIN_NAME = "ai_brain_observer_status_v1.json"
BRAIN_SCHEMA = "ai-brain-observer-1"
BRAIN_ROLE = "INDEPENDENT_BRAIN_OBSERVER_NOT_TRADE_ENGINE"
MAX_BRAIN_BYTES = 65_536
BRAIN_MAX_AGE = 30
QUOTE_MAX_AGE = 60
STAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
RESEARCH_KEYS = {
    "schema_version", "state", "reason", "research_decision",
    "virtual_sample_count", "data_lane",
} | set(consumer.FLAGS)
OBS_COUNTS = {"OR15_ABOVE_VWAP_WATCH", "OR15_BELOW_VWAP_WATCH"}


def _out(reason=None, *, decision="HOLD_RESEARCH", n=None):
    return {
        "schema_version": SCHEMA,
        "state": "BLOCKED" if reason else "RESEARCH_OBSERVATION_ONLY",
        "reason": reason,
        "research_decision": decision,
        "virtual_sample_count": n,
        "brain_observation_gate": "BLOCKED" if reason else "PASS",
        "research_context_gate": "BLOCKED" if reason else "PASS",
        "data_lane": "LOCAL_UNAUTHENTICATED_RESEARCH_NOT_EXECUTION",
        **{name: False for name in sorted(consumer.FLAGS)},
    }


def _fresh_timestamp(value, now, max_age):
    if type(value) is not str or not STAMP_RE.fullmatch(value):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            return False
        return 0 <= (now - stamp).total_seconds() <= max_age
    except (TypeError, ValueError, OverflowError):
        return False


def _load_brain_status(path, now):
    """Read exact owner-selected local Brain status with NTFS-safe identity checks."""
    path = Path(path)
    if path.name != BRAIN_NAME or not path.is_absolute():
        raise ValueError("BRAIN_PATH_INVALID")
    consumer._plain_local(path.parent)
    consumer._plain_local(path)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
            not 2 <= before.st_size <= MAX_BRAIN_BYTES):
        raise ValueError("BRAIN_FILE_INVALID")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if consumer._identity(before) != consumer._identity(opened):
            raise ValueError("BRAIN_FILE_CHANGED")
        raw = handle.read(MAX_BRAIN_BYTES + 1)
        closed = os.fstat(handle.fileno())
    consumer._plain_local(path)
    after = path.lstat()
    if (len(raw) != before.st_size or
            consumer._identity(opened, same_api=True) !=
            consumer._identity(closed, same_api=True) or
            consumer._identity(before, same_api=True) !=
            consumer._identity(after, same_api=True) or
            consumer._identity(before) != consumer._identity(closed) or
            consumer._identity(after) != consumer._identity(closed)):
        raise ValueError("BRAIN_FILE_CHANGED")
    mtime = datetime.fromtimestamp(before.st_mtime, timezone.utc)
    if not 0 <= (now - mtime).total_seconds() <= BRAIN_MAX_AGE:
        raise ValueError("BRAIN_FILE_STALE")
    body = json.loads(raw.decode("utf-8-sig"),
                      object_pairs_hook=consumer._pairs,
                      parse_constant=consumer._constant)
    if type(body) is not dict:
        raise ValueError("BRAIN_SCHEMA_INVALID")
    return body


def _brain_gate(brain, now):
    if (brain.get("schema_version") != BRAIN_SCHEMA or
            brain.get("component_role") != BRAIN_ROLE or
            brain.get("state") != "OBSERVATION_ONLY"):
        return False
    if (type(brain.get("engine_pid")) is not int or
            brain["engine_pid"] <= 0 or
            type(brain.get("observed_rows")) is not int or
            brain["observed_rows"] != 100):
        return False
    false_keys = (
        "real_submit_allowed", "tested_expectancy_available",
        "source_authenticated", "cross_source_join_allowed",
        "promotion_eligible", "exchange_tick_date_verified",
        "signal_provenance_verified",
    )
    if any(brain.get(key) is not False for key in false_keys):
        return False
    if (brain.get("last_market_data_at") is not None or
            type(brain.get("eligible_observed_n")) is not int or
            brain["eligible_observed_n"] != 0):
        return False
    if not (_fresh_timestamp(brain.get("updated_at"), now, BRAIN_MAX_AGE)
            and _fresh_timestamp(brain.get("source_publication_at"), now,
                                 QUOTE_MAX_AGE)):
        return False
    counts = brain.get("watch_counts")
    if (type(counts) is not dict or set(counts) != OBS_COUNTS or
            any(type(n) is not int or n < 0 for n in counts.values()) or
            sum(counts.values()) > 100):
        return False
    return True


def _research_gate(value):
    if type(value) is not dict or set(value) != RESEARCH_KEYS:
        return False
    if (value.get("schema_version") != consumer.SCHEMA or
            value.get("data_lane") !=
            "UNAUTHENTICATED_VIRTUAL_RESEARCH_NOT_EXECUTION" or
            any(value.get(key) is not False for key in consumer.FLAGS)):
        return False
    if (value.get("state") != "RESEARCH_OBSERVATION_ONLY" or
            value.get("reason") is not None or
            value.get("research_decision") not in (
                "COLLECT_MORE_VIRTUAL_SAMPLES",
                "REVIEW_CONTAMINATED_VIRTUAL_DATA",
                "REVIEW_VIRTUAL_RESEARCH_ONLY")):
        return False
    n = value.get("virtual_sample_count")
    return type(n) is int and 0 <= n <= 100_000


def run_once(*, brain_status_path, research_private_dir, now):
    """One explicit, read-only invocation. No persistent state or last-good."""
    try:
        if not isinstance(now, datetime) or now.utcoffset() is None:
            return _out("DECISION_CLOCK_UNVERIFIED")
        brain = _load_brain_status(brain_status_path, now)
        if not _brain_gate(brain, now):
            return _out("BRAIN_OBSERVER_UNVERIFIED")
        directory = Path(research_private_dir)
        context = consumer.consume_local(
            context_path=directory / consumer.STATUS_NAME,
            private_dir=directory, now=now)
        if not _research_gate(context):
            return _out("RESEARCH_CONTEXT_UNVERIFIED")
        return _out(None, decision=context["research_decision"],
                    n=context["virtual_sample_count"])
    except Exception:
        # Consumer/runtime failures may never promote research or reveal paths.
        return _out("LOCAL_RESEARCH_UNAVAILABLE")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only opt-in V10 Brain research sidecar, no orders")
    parser.add_argument("--brain-status", required=True)
    parser.add_argument("--research-private-dir", required=True)
    args = parser.parse_args(argv)
    result = run_once(brain_status_path=args.brain_status,
                      research_private_dir=args.research_private_dir,
                      now=datetime.now(timezone.utc))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["state"] == "RESEARCH_OBSERVATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
