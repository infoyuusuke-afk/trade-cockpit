"""Read-only adapter for existing V10 Gateway /health and Watcher JSON.

Never fabricates missing evidence for Brain or Collector. The existing
/health aggregates worker states but is not four independent receipts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from scripts.ms2_cross_source_evidence import evaluate_source_evidence

VALID_STATES = frozenset({"HEALTHY", "DEGRADED", "STOPPED", "UNKNOWN"})


def _stamp(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if d.tzinfo is None or d.utcoffset() is None:
            return None
        return d.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def source_receipt(name, raw, *, time_field="updated_at", state_field="state"):
    """Map explicit per-source timestamps, not local file mtimes or now."""
    if name not in {"collector", "watcher", "gateway", "brain"}:
        raise ValueError("UNKNOWN_SOURCE")
    if not isinstance(raw, dict):
        return None
    stamp = _stamp(raw.get(time_field))
    last = _stamp(raw.get("last_data_at"))
    state = raw.get(state_field)
    if not stamp or not last or state not in VALID_STATES:
        return None
    if raw.get("authenticated") is True:
        # Evidence claimed by an external source is not trusted as identity.
        return None
    return {
        "schema_version": "local-source-health-1.0",
        "source": name,
        "state": state,
        "observed_at": stamp,
        "last_data_at": last,
        "consecutive_failures": 0 if state == "HEALTHY" else 1,
        "reasons": [] if state == "HEALTHY" else ["SOURCE_NON_HEALTHY"],
    }


def evaluate_v10_runtime(gateway_health, independent, decision_at):
    """Require Gateway fail-closed health plus independent per-source receipts.

    Existing V10 Gateway exposes collector_status, watcher_status and a
    shadow update timestamp, but does NOT currently publish independent
    absolute observed/last_data timestamps for all four sources. Those
    status strings cannot be used to forge HEALTHY receipts.
    """
    receipts = []
    blockers = []
    if not isinstance(gateway_health, dict) or not isinstance(gateway_health.get("runtime"), dict):
        blockers.append("GATEWAY_HEALTH_MISSING")
        runtime = {}
    else:
        runtime = gateway_health["runtime"]
        if runtime.get("fail_closed") is not False:
            blockers.append("GATEWAY_FAIL_CLOSED")
        if runtime.get("data_conflict") is not False:
            blockers.append("DATA_CONFLICT_OR_UNKNOWN")
        if runtime.get("price_source_status") != "OK":
            blockers.append("PRICE_SOURCE_UNVERIFIED")
    if not isinstance(independent, dict):
        independent = {}
    for name in ("collector", "watcher", "gateway", "brain"):
        receipt = source_receipt(name, independent.get(name))
        if receipt is None:
            blockers.append("INDEPENDENT_RECEIPT_MISSING_" + name.upper())
        else:
            receipts.append(receipt)
    result = evaluate_source_evidence(receipts, decision_at)
    result["reasons"] = sorted(set(result["reasons"] + blockers))
    if blockers:
        result["status"] = "BLOCKED"
    result["adapter_version"] = "v10-local-health-adapter-1"
    result["gateway_health_aggregates_are_not_independent"] = True
    result["runtime_applied"] = False
    result["real_submit_allowed"] = False
    return result
