"""Research/reference observation handoff contract.

Research cards describe evidence and what would be required to escalate into a
strategy lane. They never enable real orders directly.
"""
from __future__ import annotations

from typing import Iterable, Optional

SCHEMA_VERSION = "research-handoff-1.0"

VALID_DOMAINS = {
    "NEXT_THEME",
    "MACRO",
    "NEWS_IR",
    "EARNINGS",
    "PTS_CONTEXT",
    "SUPPLY_DEMAND",
    "PEERS_INDUSTRY",
}

VALID_TARGETS = {
    "event-hot",
    "ms2-live",
    "swing",
    "overnight",
    "scalp",
    "value",
    "kioxia-calendar",
}

VALID_HANDOFF_STATUS = {
    "RESEARCH_ONLY",
    "WAITING_CONDITIONS",
    "QUALIFIED",
    "BLOCKED",
    "STALE",
}


def build_observation(
    *,
    research_id: str,
    domain: str,
    detected_at: str,
    title: str,
    tickers: Optional[Iterable[str]] = None,
    evidence: Optional[Iterable[dict]] = None,
    evidence_status: str = "UNVERIFIED",
    candidate_strategy: Optional[str] = None,
    escalation_conditions: Optional[Iterable[str]] = None,
    met_conditions: Optional[Iterable[str]] = None,
    stale: bool = False,
    fail_closed: bool = False,
) -> dict:
    if domain not in VALID_DOMAINS:
        raise ValueError(f"invalid domain: {domain}")
    if candidate_strategy is not None and candidate_strategy not in VALID_TARGETS:
        raise ValueError(f"invalid candidate_strategy: {candidate_strategy}")

    required = list(escalation_conditions or [])
    met = set(met_conditions or [])
    missing = [item for item in required if item not in met]

    if stale:
        status = "STALE"
    elif fail_closed:
        status = "BLOCKED"
    elif candidate_strategy is None:
        status = "RESEARCH_ONLY"
    elif missing:
        status = "WAITING_CONDITIONS"
    else:
        status = "QUALIFIED"

    handoff_target = candidate_strategy if status == "QUALIFIED" else None

    return {
        "research_id": research_id,
        "schema_version": SCHEMA_VERSION,
        "domain": domain,
        "detected_at": detected_at,
        "title": title,
        "tickers": list(tickers or []),
        "evidence": list(evidence or []),
        "evidence_status": evidence_status,
        "candidate_strategy": candidate_strategy,
        "escalation_conditions": required,
        "met_conditions": sorted(met),
        "missing_conditions": missing,
        "handoff_status": status,
        "handoff_target": handoff_target,
        "real_submit_allowed": False,
        "stale": bool(stale),
        "fail_closed": bool(fail_closed or stale),
    }


def build_report(observations: Iterable[dict], *, updated_at: Optional[str] = None) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": updated_at,
        "observations": list(observations),
        "real_submit_allowed": False,
    }
