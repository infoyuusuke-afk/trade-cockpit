"""OFFLINE ONLY: audit existing Collector's critical-path risks and model safe policy.

No PowerShell execution, broker/Excel/RSS I/O, network, private data reads or
writes. This does NOT change live Collector behavior or prove bounded latency.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA_VERSION = "ms2-collector-fault-boundary-offline-v1"
RAW_CSV_SINKS = ("tickCsv", "conditionCsv", "supplyCsv", "snapshotCsv")
MISSING_ZERO_FIELDS = (
    "volume", "vwap", "bid", "ask", "bidQty", "askQty",
    "marketSell", "marketBuy", "over", "under",
)
WRITER_STATES = frozenset({
    "PERSISTED_VERIFIED", "PERSISTENCE_CLAIM", "QUEUED",
    "PRE_QUEUE_DROP", "POST_QUEUE_REJECT", "UNKNOWN",
})


def inspect_collector_source(source: Any) -> dict:
    """Static risk inventory, NOT a complete PowerShell parser or attestation."""
    out = {
        "schema_version": SCHEMA_VERSION,
        "status": "NOT_VERIFIED",
        "risk_counts": {},
        "observed_inline_sink_classes": 0,
        "monitoring_isolation_proven": False,
        "writer_nonblocking_proven": False,
        "q2_source_authenticated": False,
        "q3_pit_eligible": False,
        "ready_for_live_patch": False,
    }
    if not isinstance(source, str) or not source.strip():
        out["risk_counts"] = {"SOURCE_UNAVAILABLE": 1}
        return out
    sinks = []
    for sink in RAW_CSV_SINKS:
        if re.search(r"\bAdd-Content\b[^\r\n]*-Path\s+\$" + sink + r"\b", source):
            sinks.append(sink)
    risks: dict[str, int] = {}
    if sinks:
        risks["SYNC_FILE_WRITES_IN_COLLECTOR_LOOP"] = len(sinks)
    out["observed_inline_sink_classes"] = len(sinks)
    zero_count = sum(
        bool(re.search(
            r"\$null\s+-eq\s+\$" + f + r"\)\s*\{\s*\$" + f + r"\s*=\s*0\s*\}",
            source, re.IGNORECASE,
        ))
        for f in MISSING_ZERO_FIELDS
    )
    if zero_count:
        risks["MISSING_AS_ZERO_IN_MARKET_FIELDS"] = zero_count
    # A matching subsequent render path is a *source-level risk*, not a
    # measurement of actual outage probability or PowerShell error semantics.
    first_sink = source.find("Add-Content -Encoding UTF8 -Path $tickCsv")
    results_append = source.find("$results += [pscustomobject]@{")
    if first_sink >= 0 and results_append > first_sink:
        risks["TICK_WRITE_PRECEDES_RESULT_ASSEMBLY"] = 1
    for sink in ("conditionCsv", "supplyCsv", "snapshotCsv"):
        if re.search(r"\bAdd-Content\b[^\r\n]*-Path\s+\$" + sink + r"\b", source):
            pass
    if all(s in sinks for s in ("conditionCsv", "supplyCsv", "snapshotCsv")):
        risks["SEQUENTIAL_NONATOMIC_TRIPLET_WRITES"] = 1
    if re.search(r"(?m)^\s*Ensure-Csv\s+\$tickCsv\b", source):
        risks["CSV_HEADER_CHECK_IN_MAIN_LOOP"] = 1
    out["risk_counts"] = dict(sorted(risks.items()))
    out["status"] = "RISK_PRESENT" if risks else "UNKNOWN_REQUIRES_NEW_REVIEW"
    return out


def model_failure_boundary(
    *,
    price: Any,
    volume: Any,
    quote_age_ms: Any,
    ttl_ms: Any,
    writer_state: Any,
    health_state: Any = "HEALTHY",
    source_proven: Any = False,
    available_at_proven: Any = False,
) -> dict:
    """Deterministic *proposed* fail-closed policy with synthetic inputs.

    Informational monitoring/risk/kill remain logically enabled; this does NOT
    make actual Collector IO nonblocking. No trade permission ever returned.
    """
    reasons: list[str] = []
    if not isinstance(writer_state, str) or writer_state not in WRITER_STATES:
        reasons.append("WRITER_STATE_INVALID")
    elif writer_state != "PERSISTED_VERIFIED":
        reasons.append("PERSISTENCE_NOT_VERIFIED")
    if health_state != "HEALTHY":
        reasons.append("SOURCE_HEALTH_NOT_READY")
    if type(price) not in (int, float) or not (0 < price < 1e10):
        reasons.append("PRICE_INVALID_OR_MISSING")
    if type(volume) not in (int, float) or not (0 <= volume < 1e14):
        reasons.append("VOLUME_INVALID_OR_MISSING")
    if (
        type(quote_age_ms) not in (int, float)
        or type(ttl_ms) not in (int, float)
        or not (0 <= quote_age_ms <= ttl_ms < 1e9)
    ):
        reasons.append("QUOTE_STALE_OR_TIME_UNKNOWN")
    if source_proven is not True:
        reasons.append("SOURCE_AUTHENTICITY_NOT_PROVEN")
    if available_at_proven is not True:
        reasons.append("AVAILABLE_AT_NOT_PROVEN")

    # These are MODEL commitments; real monitor continuity must be proven on
    # Windows PowerShell + Excel under real process and IO faults.
    reasons = sorted(set(reasons))
    return {
        "schema_version": SCHEMA_VERSION,
        "policy": "OFFLINE_SYNTHETIC_PROPOSAL_ONLY",
        "status": "RESEARCH_CANDIDATE_ONLY" if not reasons else "BLOCKED",
        "reason_codes": reasons,
        "market_monitor_should_continue": True,
        "risk_monitor_should_continue": True,
        "kill_switch_should_remain_available": True,
        "actionable_signal_allowed": False,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
        "observed_fill_evidence": False,
        "eligible_observed_n": 0,
        "monitor_continuity_measured": False,
        "worst_case_latency_proven": False,
        "writer_durability_proven_by_model": False,
    }
