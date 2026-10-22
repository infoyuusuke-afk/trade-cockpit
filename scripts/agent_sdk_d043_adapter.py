"""D-043 supply/SQ adapter for the existing *pinned* Agents SDK pilot.

Off by default. No network, broker, V10, or ChatGPT scheduled-task changes.
The original agent_sdk_coordination_pilot.py and Brain envelope schemas are not
edited: this wrapper injects the exact checklist before an isolated call and
independently audits all ten answers outside the signed research envelope.
D-041 freezes new paid runs unconditionally, including this adapter.
"""
from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path


def _neighbor(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("MODULE_UNAVAILABLE")
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


pilot = _neighbor("agent_sdk_coordination_pilot")
checks = _neighbor("supply_sq_checklist_d043")
PAID_CAP_BYTES = 24_000


class AdapterBlocked(ValueError):
    """No partially trusted specialist result may be promoted."""


def approved_checklist(path: Path | None = None) -> dict:
    canonical = (Path(__file__).resolve().parents[1] / checks.RELATIVE_PATH)
    return checks.load(canonical if path is None else Path(path))


def _preflight(doc, now, checklist, feedback):
    source = pilot.validate_snapshot(doc, now)
    if checklist.get("checklist_version") != checks.VERSION or not checklist.get("full_text"):
        raise AdapterBlocked("D043_CHECKLIST_VERSION_OR_TEXT_INVALID")
    # The runtime file is pinned by exact SHA in approved_checklist(); this
    # helper also serves independent synthetic tests with a test-only fixture.
    total = len(json.dumps(source, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    total += len(json.dumps(checklist, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    total += sum(len(s.encode("utf-8")) for s in pilot.ROLE_GOALS.values())
    total += 4096  # conservative role+coordinator instruction/JSON overhead
    if feedback:
        total += len(json.dumps(feedback, ensure_ascii=False, default=str).encode("utf-8"))
    if total > PAID_CAP_BYTES:
        raise AdapterBlocked("D036_FULL_ASSEMBLED_INPUT_TOO_LARGE_NO_CALL")
    return source


async def coordinate_with_checklist(doc, provider, *, now: datetime, checklist: dict,
                                    feedback: dict | None = None, billable: bool = False):
    """D-043 research: returns (unchanged signed contract payload, separate audit).

    Passing billable=True ALWAYS fails under D-041; there is no env override.
    Only an independently approved future code change may remove that gate.
    """
    if billable:
        raise AdapterBlocked("D041_PAID_API_FROZEN_NO_CALL")
    validated = _preflight(doc, now, checklist, feedback)
    audit_rows = []

    async def wrapper(role, prompt):
        if role != "supply_sq":
            return await provider(role, prompt)
        request = json.loads(prompt)
        if request.get("role") != "supply_sq":
            raise AdapterBlocked("D043_ROLE_MISMATCH")
        request["mandatory_checklist"] = checklist
        request["mandatory_audit_contract"] = {
            "items": list(checks.IDS),
            "statuses": sorted(checks.STATES),
            "reply_fields": ["checklist_statuses", "checklist_reasons"],
            "each_item_needs_reason": True,
            "no_market_number_inference": True,
            "vwap_r2_separate_from_credit_supply": True,
            "trade_instruction": False,
        }
        complete = json.dumps(request, ensure_ascii=False, sort_keys=True)
        if len(complete.encode("utf-8")) > PAID_CAP_BYTES:
            raise AdapterBlocked("D036_ROLE_INPUT_TOO_LARGE_NO_CALL")
        raw = await provider(role, complete)
        if type(raw) is not dict:
            raise AdapterBlocked("D043_ROLE_OUTPUT_INVALID")
        evidence = raw.get("evidence_ids")
        if type(evidence) is not list:
            raise AdapterBlocked("D043_EVIDENCE_NOT_LIST")
        audit = checks.audit(raw.get("checklist_statuses"), raw.get("checklist_reasons"),
                             evidence_ids=evidence)
        audit_rows.append(audit)
        # Preserve the existing signed report format; output audit is out-of-band.
        return {k: v for k, v in raw.items()
                if k not in ("checklist_statuses", "checklist_reasons")}

    result = await pilot.coordinate(validated, wrapper, now=now, feedback=feedback)
    supply = next((r for r in result["specialists"] if r["role"] == "supply_sq"), None)
    if supply is None:
        raise AdapterBlocked("D043_SUPPLY_REPORT_MISSING")
    if supply["status"] == "NO_DATA":
        audit_rows.append(checks.no_source_audit())
    if supply["status"] == "UNAVAILABLE" or len(audit_rows) != 1:
        raise AdapterBlocked("D043_CHECKLIST_AUDIT_NOT_COMPLETED")
    attestation = {
        "run_id": validated["run_id"], "role": "supply_sq",
        "checklist_version": checklist["checklist_version"],
        "checklist_sha256": checklist["checklist_sha256"],
        "audit": audit_rows[0], "real_submit_allowed": False,
        "api_egress": False,
        "brain_delivery_verified": False,
    }
    return result, attestation


async def run_offline(doc, provider, *, now: datetime, checklist_path: Path):
    """Production entry for licensed-source checks without sending any paid API call."""
    return await coordinate_with_checklist(
        doc, provider, now=now, checklist=approved_checklist(checklist_path),
        billable=False)
