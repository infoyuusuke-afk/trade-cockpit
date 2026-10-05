"""Correlation and lead-lag design. This module does not store a coefficient.

A pair can be measured later only when both series share a session clock,
each point has available_at, and at least 30 clean observations overlap.
Market totals are not a symbol lead. Fixtures are excluded.
"""
from __future__ import annotations

MIN_OBSERVATIONS = 30
UNIVERSE_SCOPE = "LIMITED / PRECISION_WATCH_ONLY"
NOT_AVAILABLE = "NOT AVAILABLE"


def design_status() -> dict:
    return {
        "status": "DESIGN_ONLY",
        "measured_pairs": 0,
        "correlation": NOT_AVAILABLE,
        "lead_lag": NOT_AVAILABLE,
        "universe_scope": UNIVERSE_SCOPE,
        "min_observations": MIN_OBSERVATIONS,
        "same_session_clock_required": True,
        "available_at_required": True,
        "market_totals_are_symbol_leads": False,
        "fixtures_excluded": True,
        "trading_adoption": False,
        "real_submit_allowed": False,
        "counts_as_live_sample": False,
        "reason": "NOT_MEASURED",
    }


def _clean_sessions(series) -> set[str] | None:
    if not isinstance(series, list):
        return None
    sessions = []
    for row in series:
        if not isinstance(row, dict):
            return None
        if row.get("fixture") is True or row.get("acceptance_class") == "synthetic":
            return None
        if row.get("source_stage") in {"SYNTHETIC/REPLAY", "SYNTHETIC"}:
            return None
        session = row.get("session_date")
        available = row.get("available_at")
        if not isinstance(session, str) or len(session) != 10 or not isinstance(available, str) or "T" not in available:
            return None
        if row.get("value") is None or isinstance(row.get("value"), bool):
            return None
        sessions.append(session)
    if len(sessions) != len(set(sessions)):
        return None
    return set(sessions)


def evaluate_pair(left, right) -> dict:
    """Apply the measurement gate and still withhold the coefficient."""
    status = design_status()
    left_sessions = _clean_sessions(left)
    right_sessions = _clean_sessions(right)
    overlap = 0
    if left_sessions is not None and right_sessions is not None:
        overlap = len(left_sessions & right_sessions)
    if overlap < MIN_OBSERVATIONS:
        status["reason"] = "INSUFFICIENT_OR_UNALIGNED"
        return status
    status["reason"] = "GATE_OPEN_NOT_COMPUTED"
    status["measured_pairs"] = 0
    status["correlation"] = NOT_AVAILABLE
    status["lead_lag"] = NOT_AVAILABLE
    return status
