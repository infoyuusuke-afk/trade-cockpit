"""D-043 mandatory market-wide supply checklist contract (offline / no network).

This module does not fetch market data, invoke a model, or touch trading gates.
The SHA is the OWNER-approved checklist's exact UTF-8 bytes, not a chat summary.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

APPROVED_SHA256 = "3c7a366853b2451cc6401a05ac477a34801adc9439e2c39869745c974caf264d"
VERSION = "D-043/v1.0"
RELATIVE_PATH = "docs/analysts/SUPPLY_SQ_REQUIRED_CHECKLIST_V1.md"
IDS = tuple("C%02d" % i for i in range(1, 11))
STATES = frozenset(("VERIFIED", "UNVERIFIED", "STALE", "NOT_APPLICABLE"))
MAX_BYTES = 10_000


class ChecklistBlocked(ValueError):
    """Fail closed before any API call or paid ledger reservation."""


def load(path: Path, *, expected_sha: str = APPROVED_SHA256) -> dict:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ChecklistBlocked("D043_CHECKLIST_MISSING_OR_LINK_NO_CALL")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_BYTES:
        raise ChecklistBlocked("D043_CHECKLIST_SIZE_INVALID_NO_CALL")
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha:
        raise ChecklistBlocked("D043_CHECKLIST_HASH_MISMATCH_NO_CALL")
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ChecklistBlocked("D043_CHECKLIST_UTF8_INVALID_NO_CALL") from exc
    found = re.findall(r"(?m)^- \*\*(C\d{2})｜", content)
    if tuple(found) != IDS:
        raise ChecklistBlocked("D043_CHECKLIST_IDS_MISSING_OR_REORDERED_NO_CALL")
    return {"checklist_version": VERSION, "checklist_sha256": digest,
            "full_text": content}


def audit(statuses: dict, reasons: dict, *, evidence_ids: list[str]) -> dict:
    """Validate all 10 model answers. UNKNOWN is never implicitly VERIFIED."""
    if type(statuses) is not dict or type(reasons) is not dict:
        raise ChecklistBlocked("D043_COVERAGE_MISSING")
    if set(statuses) != set(IDS) or set(reasons) != set(IDS):
        raise ChecklistBlocked("D043_COVERAGE_INCOMPLETE")
    for item in IDS:
        status, why = statuses[item], reasons[item]
        if status not in STATES or type(why) is not str or not 2 <= len(why) <= 220:
            raise ChecklistBlocked("D043_COVERAGE_STATUS_OR_REASON_INVALID")
        if status == "VERIFIED" and not evidence_ids:
            raise ChecklistBlocked("D043_VERIFIED_WITHOUT_EVIDENCE")
    missing = [item for item in IDS if statuses[item] in ("UNVERIFIED", "STALE")]
    return {"checklist_version": VERSION, "answered": 10,
            "verified": sum(statuses[i] == "VERIFIED" for i in IDS),
            "missing_ids": missing,
            "quality": "QUALITY_INCOMPLETE" if missing else "QUALITY_COMPLETE",
            "statuses": {i: statuses[i] for i in IDS}}


def no_source_audit() -> dict:
    statuses = {i: "UNVERIFIED" for i in IDS}
    reasons = {i: "No eligible dated source in this run" for i in IDS}
    return audit(statuses, reasons, evidence_ids=[])
