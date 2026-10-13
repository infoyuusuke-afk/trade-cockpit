"""Private journal for new virtual-signal observations.

``morning_review.py`` remains the legacy writer of ``paper_trade_history.json``.
This module does not import it, does not change that file, and is not
scheduled. A live morning-review row still has no evidence lane, no trade id,
no sample role, no evaluation window, no timezone-aware signal or exit time,
and placeholder fees/slippage of 0. Uppercase ``MFE`` / ``MAE`` are a full-day
range, not a post-entry path. Those aliases are not renamed into the ledger
contract. The row is stored as OBSERVED → BLOCKED.

A caller that already holds every field required by
``virtual_trade_evidence.ingest`` can move OBSERVED → VALIDATED → MEASURED.
Only that measured evidence is eligible for the expectancy ledger, and only
inside one VIRTUAL_SIGNAL cohort (one strategy id, one version, one of
TRAIN / TEST / SHADOW). ``statistical_edge_confirmed``, ``promotion_eligible``,
and ``real_submit_allowed`` stay false. N >= 30 satisfies the ledger's
measurement contract only.

The journal path must be set explicitly (argument or
``TRADE_COCKPIT_NEW_SIGNAL_JOURNAL``). The default is to write nothing. A
path inside this public repository is refused unless it is under
``data/private/``, which is gitignored. Writes are atomic. A truncated file
or a leftover partial is not repaired and is not merged back in.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

CONTRACT = "new-virtual-signal-journal-1"
ENV_PATH = "TRADE_COCKPIT_NEW_SIGNAL_JOURNAL"
PARTIAL_SUFFIX = ".partial"
LEGACY_HISTORY_NAME = "paper_trade_history.json"

ALIASES = (
    ("signal_time", "ALIAS_REFUSED_SIGNAL_TIME"),
    ("MFE", "ALIAS_REFUSED_MFE"),
    ("MAE", "ALIAS_REFUSED_MAE"),
    ("ticker", "ALIAS_REFUSED_TICKER"),
    ("date", "ALIAS_REFUSED_DATE"),
    ("strategy_key", "ALIAS_REFUSED_STRATEGY_KEY"),
)

# What the live morning-review producer actually emits. This is a gap map,
# not a list of values to invent. `available` means the contract field is
# present under its own name at signal or audit time.
PRODUCER_FIELDS = (
    {"field": "strategy_id", "available": True, "observed_on": "strategy_schema.tag_record via morning_review.morning_snapshot", "blocked_when": None},
    {"field": "strategy_version", "available": True, "observed_on": "STRATEGY_REGISTRY version when strategy_id is registered; unknown is not a measurement", "blocked_when": "STRATEGY_VERSION_UNKNOWN"},
    {"field": "symbol", "available": False, "observed_on": "ticker only", "blocked_when": "ALIAS_REFUSED_TICKER"},
    {"field": "side", "available": True, "observed_on": "candidate side", "blocked_when": None},
    {"field": "signal_known_at", "available": False, "observed_on": "signal_time display string with a JST suffix", "blocked_when": "ALIAS_REFUSED_SIGNAL_TIME"},
    {"field": "source", "available": True, "observed_on": "tag_record source", "blocked_when": None},
    {"field": "provenance", "available": False, "observed_on": "field_observed_at and inputs are not emitted", "blocked_when": "UNOBSERVED"},
    {"field": "sample_role", "available": False, "observed_on": "not emitted", "blocked_when": "UNOBSERVED"},
    {"field": "trade_id", "available": False, "observed_on": "not emitted", "blocked_when": "UNOBSERVED"},
    {"field": "universe_fixed_at", "available": False, "observed_on": "snapshot fixed_at is a display string and is not a trade-row field", "blocked_when": "UNOBSERVED"},
    {"field": "window_start", "available": False, "observed_on": "not emitted", "blocked_when": "UNOBSERVED"},
    {"field": "window_end", "available": False, "observed_on": "not emitted", "blocked_when": "UNOBSERVED"},
    {"field": "fees", "available": False, "observed_on": "audit_one writes placeholder 0 without a cost basis", "blocked_when": "FEES_UNVERIFIED_ZERO"},
    {"field": "slippage", "available": False, "observed_on": "audit_one writes placeholder 0 without a cost basis", "blocked_when": "SLIPPAGE_UNVERIFIED_ZERO"},
    {"field": "exit_known_at", "available": False, "observed_on": "not emitted", "blocked_when": "UNOBSERVED"},
    {"field": "mfe", "available": False, "observed_on": "uppercase MFE from the full daily range", "blocked_when": "EXCURSION_NOT_POINT_IN_TIME"},
    {"field": "mae", "available": False, "observed_on": "uppercase MAE from the full daily range", "blocked_when": "EXCURSION_NOT_POINT_IN_TIME"},
)

JOURNAL_REASONS = (
    "JOURNAL_PATH_UNCONFIGURED",
    "PUBLIC_PATH_REJECTED",
    "REFUSED_LEGACY_WRITE",
    "LEGACY_UNREADABLE",
    "LEGACY_MUTATED",
    "JOURNAL_UNREADABLE",
    "RECOVERY_REFUSED",
    "PARTIAL_WRITE",
    "JOURNAL_CHECKSUM_MISMATCH",
    "CORRUPT_JSON",
    "PRIVATE_DATA_REJECTED",
    "RECORD_NOT_SERIALIZABLE",
    "EMPTY_INPUT",
    "EVIDENCE_MISMATCH",
)


def _load_evidence():
    name = "virtual_trade_evidence"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).with_name("virtual_trade_evidence.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_EVIDENCE = _load_evidence()


def _order(reasons):
    priority = JOURNAL_REASONS + tuple(_EVIDENCE.REASON_PRIORITY)
    rank = {name: index for index, name in enumerate(priority)}
    return sorted(set(reasons), key=lambda item: (rank.get(item, len(priority)), item))


def _sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=None)


def _records_sha(records):
    return _sha256(_canonical(records).encode("utf-8"))


def _safety():
    return {
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
        "edge_confirmed_by_sample_size": False,
        "scheduled": False,
        "auto_record_armed": False,
    }


def inspect_producer():
    """Field-by-field availability of the live virtual-trade producer.

    Availability is not a license to copy aliases. The journal stays
    unwired because the missing fields cannot be measured yet.
    """
    unavailable = [item["field"] for item in PRODUCER_FIELDS if not item["available"]]
    return {
        "contract": CONTRACT,
        "producer": "morning_review.morning_snapshot + morning_review.audit_one",
        "acceptance": "CONDITIONAL",
        "producer_can_measure": False,
        "auto_record_armed": False,
        "morning_review_wired": False,
        "scheduled": False,
        "fields": list(PRODUCER_FIELDS),
        "unavailable_fields": unavailable,
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }


def _repo_root():
    return Path(__file__).resolve().parents[1]


def resolve_journal_path(journal_path=None, *, legacy_path=None):
    """Return ``(path, reason)``. Unset means do not write."""
    legacy = Path(legacy_path) if legacy_path is not None else _EVIDENCE.DEFAULT_LEGACY
    if journal_path is None or journal_path == "":
        journal_path = os.environ.get(ENV_PATH, "").strip()
    if not journal_path:
        return None, "JOURNAL_PATH_UNCONFIGURED"
    path = Path(journal_path).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    else:
        path = path.resolve()
    try:
        same_legacy = path == legacy.resolve()
    except OSError:
        same_legacy = False
    if path.name == LEGACY_HISTORY_NAME or same_legacy:
        return None, "REFUSED_LEGACY_WRITE"
    root = _repo_root()
    private_root = (root / "data" / "private").resolve()
    try:
        path.relative_to(private_root)
        inside_private = True
    except ValueError:
        inside_private = False
    try:
        path.relative_to(root)
        inside_repo = True
    except ValueError:
        inside_repo = False
    if inside_repo and not inside_private:
        return None, "PUBLIC_PATH_REJECTED"
    return path, None


def project_observation(observation):
    """Copy contract fields that are already present. Do not rename aliases."""
    if not isinstance(observation, dict):
        return None, [], ["RECORD_NOT_AN_OBJECT"]
    forwarded = {}
    withheld = []
    reasons = []
    for alias, reason in ALIASES:
        if alias in observation:
            withheld.append({"field": alias, "reason": reason, "forwarded": False})
            reasons.append(reason)
    if "MFE" in observation or "MAE" in observation:
        reasons.append("EXCURSION_NOT_POINT_IN_TIME")
    for key in _EVIDENCE.REQUIRED:
        if key not in observation or observation[key] is None:
            withheld.append({"field": key, "reason": "UNOBSERVED", "forwarded": False})
            reasons.append("UNOBSERVED")
            continue
        forwarded[key] = copy.deepcopy(observation[key])
    if "strategy_id" in forwarded and "strategy_key" in observation:
        forwarded["strategy_key"] = observation["strategy_key"]
    if "symbol" in forwarded and "ticker" in observation:
        forwarded["ticker"] = observation["ticker"]
    for flag in _EVIDENCE.SAFETY_FLAGS:
        if flag in observation:
            forwarded[flag] = observation[flag]
    for key in _EVIDENCE.PRIVATE_KEYS:
        if key in observation:
            reasons.append("PRIVATE_DATA_REJECTED")
    return forwarded, withheld, _order(reasons)


def _partial_path(path):
    return Path(str(path) + PARTIAL_SUFFIX)


def _blocked(reasons, *, missing=(), transition=("OBSERVED", "BLOCKED"), legacy_before=None, legacy_path=None):
    ordered = _order(reasons)
    out = {
        "contract": CONTRACT,
        "state": "BLOCKED",
        "transition": list(transition),
        "reason": ordered[0] if ordered else None,
        "reasons": ordered,
        "missing": list(missing),
        "accepted": False,
        "admissible": False,
        "evidence": None,
        "journal_written": False,
        "replayed": False,
        "partial_adopted": False,
        "measurement_contract_met": False,
        "expectancy_demonstrated": False,
        "metrics": None,
        "included_n": 0,
        "excluded_n": 0,
        "producer_admissible_n": 0,
        "synthetic_admissible_n": 0,
        "profitability_status": "UNKNOWN",
    }
    out.update(_safety())
    if legacy_before is not None and legacy_path is not None:
        _attach_legacy(out, legacy_before, legacy_path)
    return out


def _attach_legacy(out, before, legacy_path):
    try:
        after = Path(legacy_path).read_bytes()
    except OSError:
        out["legacy_bytes_unchanged"] = False
        out["legacy_sha256"] = _sha256(before) if before is not None else None
        out["reason"] = "LEGACY_UNREADABLE"
        out["reasons"] = _order(list(out.get("reasons") or []) + ["LEGACY_UNREADABLE"])
        out["state"] = "BLOCKED"
        out["accepted"] = False
        return out
    out["legacy_sha256"] = _sha256(before if before is not None else after)
    out["legacy_bytes_unchanged"] = before == after
    if before != after:
        out["state"] = "BLOCKED"
        out["reason"] = "LEGACY_MUTATED"
        out["reasons"] = _order(list(out.get("reasons") or []) + ["LEGACY_MUTATED"])
        out["accepted"] = False
        out["admissible"] = False
        out["metrics"] = None
        out["expectancy_demonstrated"] = False
        out["measurement_contract_met"] = False
        out.update(_safety())
    return out


def load_journal(path):
    """Read a committed journal. Partial and corrupt files are not repaired."""
    path = Path(path)
    partial = _partial_path(path)
    partial_exists = partial.exists()
    if not path.exists():
        if partial_exists:
            blocked = _blocked(["PARTIAL_WRITE"])
            blocked["records"] = None
            blocked["partial_detected"] = True
            blocked["partial_adopted"] = False
            return blocked
        empty = {
            "contract": CONTRACT,
            "state": "EMPTY",
            "transition": ["OBSERVED"],
            "reason": None,
            "reasons": [],
            "records": [],
            "partial_detected": False,
            "partial_adopted": False,
            "journal_written": False,
        }
        empty.update(_safety())
        return empty
    try:
        blob = path.read_bytes()
    except OSError:
        blocked = _blocked(["JOURNAL_UNREADABLE"])
        blocked["records"] = None
        blocked["partial_detected"] = partial_exists
        blocked["partial_adopted"] = False
        return blocked
    looks_closed = blob.endswith(b"\n") and blob.rstrip().endswith(b"}")
    try:
        text = blob.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError):
        reason = "CORRUPT_JSON" if looks_closed else "PARTIAL_WRITE"
        blocked = _blocked([reason])
        blocked["records"] = None
        blocked["partial_detected"] = True
        blocked["partial_adopted"] = False
        return blocked
    if (
        not isinstance(data, dict)
        or data.get("contract") != CONTRACT
        or not isinstance(data.get("records"), list)
        or not isinstance(data.get("sha256"), str)
        or any(not isinstance(row, dict) for row in data["records"])
    ):
        blocked = _blocked(["CORRUPT_JSON"])
        blocked["records"] = None
        blocked["partial_detected"] = partial_exists
        blocked["partial_adopted"] = False
        return blocked
    if data["sha256"] != _records_sha(data["records"]):
        blocked = _blocked(["JOURNAL_CHECKSUM_MISMATCH"])
        blocked["records"] = None
        blocked["partial_detected"] = partial_exists
        blocked["partial_adopted"] = False
        return blocked
    ready = {
        "contract": CONTRACT,
        "state": "EMPTY" if not data["records"] else "READY",
        "transition": ["OBSERVED"],
        "reason": None,
        "reasons": [],
        "records": data["records"],
        "sha256": data["sha256"],
        "partial_detected": partial_exists,
        "partial_adopted": False,
        "journal_written": False,
    }
    ready.update(_safety())
    if partial_exists:
        ready["partial_note"] = "PARTIAL_WRITE"
    return ready


def _atomic_write(path, records):
    path = Path(path)
    partial = _partial_path(path)
    if partial.exists() or (path.exists() and load_journal(path)["state"] == "BLOCKED"):
        return False
    document = {
        "contract": CONTRACT,
        "records": records,
        "sha256": _records_sha(records),
    }
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("wb") as handle:
        handle.write(text.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(partial, path)
    return True


def recover_journal(journal_path, *, legacy_path=None):
    """Remove an uncommitted partial only when the committed file is intact.

    The partial bytes are not read and are not copied into the journal.
    A truncated committed file is left unchanged.
    """
    legacy = Path(legacy_path) if legacy_path is not None else _EVIDENCE.DEFAULT_LEGACY
    try:
        before = legacy.read_bytes()
    except OSError:
        return _blocked(["LEGACY_UNREADABLE"])
    path, reason = resolve_journal_path(journal_path, legacy_path=legacy)
    if reason:
        return _blocked([reason], legacy_before=before, legacy_path=legacy)
    partial = _partial_path(path)
    if not partial.exists():
        loaded = load_journal(path)
        if loaded["state"] == "BLOCKED":
            blocked = _blocked(
                ["RECOVERY_REFUSED", loaded["reason"]],
                legacy_before=before,
                legacy_path=legacy,
            )
            blocked["partial_removed"] = False
            blocked["partial_adopted"] = False
            blocked["records"] = None
            return blocked
        loaded["recovered"] = False
        loaded["partial_removed"] = False
        _attach_legacy(loaded, before, legacy)
        return loaded
    if not path.exists():
        blocked = _blocked(["RECOVERY_REFUSED"], legacy_before=before, legacy_path=legacy)
        blocked["partial_detected"] = True
        blocked["partial_adopted"] = False
        blocked["partial_removed"] = False
        return blocked
    loaded = load_journal(path)
    if loaded["state"] == "BLOCKED":
        blocked = _blocked(["RECOVERY_REFUSED"], legacy_before=before, legacy_path=legacy)
        blocked["partial_detected"] = True
        blocked["partial_adopted"] = False
        blocked["partial_removed"] = False
        blocked["records"] = None
        return blocked
    partial_blob_ignored = True
    partial.unlink()
    reloaded = load_journal(path)
    reloaded["recovered"] = True
    reloaded["partial_removed"] = True
    reloaded["partial_adopted"] = False
    reloaded["partial_bytes_used"] = not partial_blob_ignored
    _attach_legacy(reloaded, before, legacy)
    return reloaded


def _observation_id(observation):
    try:
        blob = _canonical(observation)
    except (TypeError, ValueError):
        return None
    if blob is None:
        return None
    return _sha256(blob.encode("utf-8"))


def _stored_observation(observation):
    stored = copy.deepcopy(observation)
    for flag in _EVIDENCE.SAFETY_FLAGS:
        if flag in stored:
            stored[flag] = False
    for key in list(stored):
        if key in _EVIDENCE.PRIVATE_KEYS:
            stored.pop(key, None)
    return stored


def _known_trade_ids(records):
    known = []
    for record in records:
        trade_id = record.get("trade_id")
        if isinstance(trade_id, str) and trade_id:
            known.append(trade_id)
    return known


def _row_from_ingest(observation, origin, observation_id, forwarded, withheld, screen_reasons, ingest_row, cohort):
    ingest_transition = list(ingest_row.get("transition") or ["SOURCE", "BLOCKED"])
    ingest_state = ingest_row.get("state")
    evidence = None
    admissible = False
    if cohort.get("state") == "MEASURED":
        evidence = ingest_row.get("_assigned_evidence")
        admissible = isinstance(evidence, dict)
        transition = ["OBSERVED", "VALIDATED", "MEASURED"] if admissible else ["OBSERVED", "BLOCKED"]
        state = "MEASURED" if admissible else "BLOCKED"
    elif ingest_state == "VALIDATED" and ingest_row.get("_assigned_evidence") is not None:
        evidence = ingest_row.get("_assigned_evidence")
        admissible = True
        transition = ["OBSERVED", "VALIDATED", "BLOCKED"]
        state = "BLOCKED"
    elif "VALIDATED" in ingest_transition and ingest_state == "BLOCKED":
        transition = ["OBSERVED", "VALIDATED", "BLOCKED"]
        state = "BLOCKED"
    else:
        transition = ["OBSERVED", "BLOCKED"]
        state = "BLOCKED"
    reasons = _order(list(screen_reasons) + list(ingest_row.get("reasons") or []))
    if cohort.get("reason") and cohort.get("state") != "MEASURED":
        reasons = _order(reasons + [cohort["reason"]])
    reason = None if state == "MEASURED" else (reasons[0] if reasons else ingest_row.get("reason"))
    trade_id = forwarded.get("trade_id") if isinstance(forwarded.get("trade_id"), str) else None
    return {
        "contract": CONTRACT,
        "observation_id": observation_id,
        "origin": origin,
        "state": state,
        "transition": transition,
        "reason": reason,
        "reasons": [] if state == "MEASURED" else reasons,
        "missing": list(ingest_row.get("missing") or []),
        "withheld": withheld,
        "forwarded_fields": sorted(forwarded),
        "trade_id": trade_id,
        "admissible": admissible,
        "evidence": evidence,
        "cohort_state": cohort.get("state"),
        "cohort_reason": None if cohort.get("state") == "MEASURED" else cohort.get("reason"),
        "observation": _stored_observation(observation),
        "ingest_state": ingest_state,
        "measurement_contract_met": False,
        "expectancy_demonstrated": False,
        "statistical_edge_confirmed": False,
        "promotion_eligible": False,
        "real_submit_allowed": False,
    }


def _assign_evidence(ingest, forwarded_rows):
    """Attach measured evidence onto ingest rows without mutating inputs."""
    rows = [dict(row) for row in (ingest.get("rows") or [])]
    if ingest.get("state") == "MEASURED":
        evidence_records = list(ingest.get("evidence_records") or [])
        for index, row in enumerate(rows):
            row["_assigned_evidence"] = evidence_records[index] if index < len(evidence_records) else None
        return rows
    separated = ingest.get("separated") or {}
    measured_ids = {}
    for grouped in separated.values():
        for record in grouped.get("evidence_records") or []:
            if isinstance(record, dict) and isinstance(record.get("trade_id"), str):
                measured_ids[record["trade_id"]] = record
    for index, row in enumerate(rows):
        trade_id = None
        if index < len(forwarded_rows) and isinstance(forwarded_rows[index].get("trade_id"), str):
            trade_id = forwarded_rows[index]["trade_id"]
        row["_assigned_evidence"] = measured_ids.get(trade_id) if row.get("state") == "VALIDATED" else None
    return rows


def record_observations(observations, *, journal_path=None, legacy_path=None, origin="caller"):
    """Persist new observations. Eligible evidence is measured; gaps stay blocked."""
    legacy = Path(legacy_path) if legacy_path is not None else _EVIDENCE.DEFAULT_LEGACY
    try:
        before = legacy.read_bytes()
    except OSError:
        return _blocked(["LEGACY_UNREADABLE"])
    if origin not in {"caller", "producer", "synthetic"}:
        blocked = _blocked(["RECORD_NOT_AN_OBJECT"], legacy_before=before, legacy_path=legacy)
        return blocked
    if not isinstance(observations, list):
        return _blocked(["RECORDS_NOT_A_LIST"], legacy_before=before, legacy_path=legacy)
    if not observations:
        return _blocked(["EMPTY_INPUT"], legacy_before=before, legacy_path=legacy)
    path, path_reason = resolve_journal_path(journal_path, legacy_path=legacy)
    if path_reason:
        return _blocked([path_reason], legacy_before=before, legacy_path=legacy)

    loaded = load_journal(path) if path.exists() or _partial_path(path).exists() else load_journal(path)
    if loaded["state"] == "BLOCKED":
        loaded["journal_written"] = False
        loaded["admissible"] = False
        loaded["metrics"] = None
        loaded["partial_adopted"] = False
        _attach_legacy(loaded, before, legacy)
        return loaded
    if loaded.get("partial_detected"):
        blocked = _blocked(["PARTIAL_WRITE"], legacy_before=before, legacy_path=legacy)
        blocked["partial_detected"] = True
        blocked["partial_adopted"] = False
        blocked["records"] = None
        return blocked

    existing = list(loaded.get("records") or [])
    if any(not isinstance(item, dict) for item in observations):
        return _blocked(["RECORD_NOT_AN_OBJECT"], legacy_before=before, legacy_path=legacy)
    if any(any(key in item for key in _EVIDENCE.PRIVATE_KEYS) for item in observations):
        return _blocked(["PRIVATE_DATA_REJECTED"], legacy_before=before, legacy_path=legacy)

    prepared = []
    for observation in observations:
        observation_id = _observation_id(observation)
        if observation_id is None:
            return _blocked(["RECORD_NOT_SERIALIZABLE"], legacy_before=before, legacy_path=legacy)
        forwarded, withheld, screen = project_observation(observation)
        prepared.append({
            "observation": observation,
            "observation_id": observation_id,
            "forwarded": forwarded,
            "withheld": withheld,
            "screen": screen,
        })

    by_id = {record.get("observation_id"): record for record in existing}
    known = set(_known_trade_ids(existing))
    seen_ids = set()
    seen_trades = set()
    fresh = []
    for item in prepared:
        if item["observation_id"] in seen_ids:
            return _blocked(["DUPLICATE_TRADE_ID"], legacy_before=before, legacy_path=legacy)
        seen_ids.add(item["observation_id"])
        trade_id = item["forwarded"].get("trade_id")
        if isinstance(trade_id, str) and trade_id:
            if trade_id in seen_trades:
                return _blocked(["DUPLICATE_TRADE_ID"], legacy_before=before, legacy_path=legacy)
            seen_trades.add(trade_id)
            prior = by_id.get(item["observation_id"])
            if prior is None and trade_id in known:
                blocked = _blocked(["EVIDENCE_MISMATCH"], legacy_before=before, legacy_path=legacy)
                blocked["journal_unchanged"] = True
                return blocked
        fresh.append(item)

    replay_only = all(item["observation_id"] in by_id for item in prepared)
    if replay_only:
        rows = [by_id[item["observation_id"]] for item in prepared]
        return _finish(rows, existing, before, legacy, written=False, replayed=True, ingest=None)

    new_items = [item for item in prepared if item["observation_id"] not in by_id]
    ingest = _EVIDENCE.ingest_cohort(
        [item["forwarded"] for item in new_items],
        known_trade_ids=_known_trade_ids(existing),
    )
    assigned = _assign_evidence(ingest, [item["forwarded"] for item in new_items])
    if len(assigned) != len(new_items):
        blocked = _blocked(["LEDGER_REJECTED"], legacy_before=before, legacy_path=legacy)
        return blocked
    new_records = []
    for item, ingest_row in zip(new_items, assigned):
        new_records.append(_row_from_ingest(
            item["observation"],
            origin,
            item["observation_id"],
            item["forwarded"],
            item["withheld"],
            item["screen"],
            ingest_row,
            ingest,
        ))
    updated = existing + new_records
    if not _atomic_write(path, updated):
        blocked = _blocked(["PARTIAL_WRITE"], legacy_before=before, legacy_path=legacy)
        blocked["partial_adopted"] = False
        return blocked
    rows = []
    written_ids = {record["observation_id"]: record for record in new_records}
    for item in prepared:
        rows.append(written_ids.get(item["observation_id"]) or by_id[item["observation_id"]])
    return _finish(rows, updated, before, legacy, written=True, replayed=False, ingest=ingest)


def _finish(rows, records, before, legacy, *, written, replayed, ingest):
    measured = [row for row in rows if row.get("state") == "MEASURED"]
    cohort_state = ingest.get("state") if isinstance(ingest, dict) else ("MEASURED" if measured and len(measured) == len(rows) else rows[0].get("state"))
    if isinstance(ingest, dict):
        cohort_state = ingest.get("state")
        cohort_reason = None if cohort_state == "MEASURED" else ingest.get("reason")
        measurement = bool(ingest.get("expectancy_demonstrated")) if cohort_state == "MEASURED" else False
        metrics = ingest.get("metrics") if cohort_state == "MEASURED" else None
        included = ingest.get("included_n") if cohort_state == "MEASURED" else 0
        excluded = ingest.get("excluded_n") if cohort_state == "MEASURED" else len(rows)
    elif measured and len(measured) == len(rows):
        cohort_state = "MEASURED"
        cohort_reason = None
        measurement = False
        metrics = None
        included = len(measured)
        excluded = 0
    else:
        cohort_state = "BLOCKED"
        cohort_reason = rows[0].get("reason") if rows else "EMPTY_INPUT"
        measurement = False
        metrics = None
        included = 0
        excluded = len(rows)
    reasons = []
    missing = []
    for row in rows:
        reasons.extend(row.get("reasons") or [])
        missing.extend(row.get("missing") or [])
    if cohort_reason:
        reasons.append(cohort_reason)
    ordered = _order(reasons)
    out = {
        "contract": CONTRACT,
        "state": "MEASURED" if cohort_state == "MEASURED" else "BLOCKED",
        "transition": ["OBSERVED", "VALIDATED", "MEASURED"] if cohort_state == "MEASURED" else ["OBSERVED", "BLOCKED"],
        "reason": None if cohort_state == "MEASURED" else (ordered[0] if ordered else cohort_reason),
        "reasons": [] if cohort_state == "MEASURED" else ordered,
        "missing": sorted(set(missing)),
        "accepted": cohort_state == "MEASURED",
        "admissible": cohort_state == "MEASURED",
        "evidence": rows[0].get("evidence") if len(rows) == 1 else None,
        "rows": rows,
        "records": records,
        "journal_written": written,
        "replayed": replayed,
        "partial_adopted": False,
        "measurement_contract_met": measurement,
        "expectancy_demonstrated": measurement,
        "metrics": metrics,
        "included_n": included or 0,
        "excluded_n": excluded or 0,
        "producer_admissible_n": sum(1 for row in records if row.get("admissible") and row.get("origin") == "producer"),
        "synthetic_admissible_n": sum(1 for row in records if row.get("admissible") and row.get("origin") == "synthetic"),
        "caller_admissible_n": sum(1 for row in records if row.get("admissible") and row.get("origin") == "caller"),
        "profitability_status": "UNKNOWN",
    }
    if out["state"] != "MEASURED":
        out["metrics"] = None
        out["expectancy_demonstrated"] = False
        out["measurement_contract_met"] = False
        out["evidence"] = None
        out["accepted"] = False
        out["admissible"] = False
    out.update(_safety())
    _attach_legacy(out, before, legacy)
    return out


def record_observation(observation, *, journal_path=None, legacy_path=None, origin="caller"):
    """Record one observation and flatten a single-row result."""
    out = record_observations([observation], journal_path=journal_path, legacy_path=legacy_path, origin=origin)
    rows = out.get("rows")
    if isinstance(rows, list) and len(rows) == 1 and out.get("state") != "BLOCKED":
        row = rows[0]
        out["evidence"] = row.get("evidence")
        out["transition"] = list(row.get("transition") or out["transition"])
        out["forwarded_fields"] = row.get("forwarded_fields")
        out["withheld"] = row.get("withheld")
        out["trade_id"] = row.get("trade_id")
        out["observation_id"] = row.get("observation_id")
    elif isinstance(rows, list) and len(rows) == 1:
        row = rows[0]
        out["transition"] = list(row.get("transition") or out["transition"])
        out["forwarded_fields"] = row.get("forwarded_fields")
        out["withheld"] = row.get("withheld")
        out["trade_id"] = row.get("trade_id")
        out["observation_id"] = row.get("observation_id")
        out["missing"] = list(row.get("missing") or out.get("missing") or [])
        out["evidence"] = None
        out["metrics"] = None
    return out


def record_producer_row(row, *, journal_path=None, legacy_path=None):
    """Store one live producer row. Missing contract fields stay missing."""
    return record_observation(row, journal_path=journal_path, legacy_path=legacy_path, origin="producer")


def handoff_admissible(journal_path, *, legacy_path=None):
    """Pass stored admissible evidence to the ledger, one cohort at a time.

    Realized profitability stays UNKNOWN while no producer row is admissible.
    Synthetic measurements are returned separately and do not confirm an edge.
    """
    legacy = Path(legacy_path) if legacy_path is not None else _EVIDENCE.DEFAULT_LEGACY
    try:
        before = legacy.read_bytes()
    except OSError:
        return _blocked(["LEGACY_UNREADABLE"])
    path, reason = resolve_journal_path(journal_path, legacy_path=legacy)
    if reason:
        return _blocked([reason], legacy_before=before, legacy_path=legacy)
    before_journal = path.read_bytes() if path.exists() else None
    loaded = load_journal(path)
    if loaded["state"] == "BLOCKED":
        loaded["journal_written"] = False
        loaded["metrics"] = None
        loaded["profitability_status"] = "UNKNOWN"
        _attach_legacy(loaded, before, legacy)
        return loaded
    if loaded.get("partial_detected"):
        blocked = _blocked(["PARTIAL_WRITE"], legacy_before=before, legacy_path=legacy)
        blocked["partial_adopted"] = False
        return blocked
    records = loaded.get("records") or []
    admissible = [row for row in records if row.get("admissible") and isinstance(row.get("evidence"), dict)]
    groups = {}
    for row in admissible:
        evidence = row["evidence"]
        if evidence.get("evidence_lane") != _EVIDENCE.LANES_VIRTUAL:
            continue
        key = (
            evidence.get("evidence_lane"),
            evidence.get("strategy_id"),
            evidence.get("strategy_version"),
            evidence.get("sample_role"),
        )
        groups.setdefault(key, []).append(evidence)
    separated = {}
    for key, evidence_records in groups.items():
        label = "{lane}|{strategy}|{version}|{role}".format(
            lane=key[0], strategy=key[1], version=key[2], role=key[3],
        )
        separated[label] = _EVIDENCE.measure_validated_cohort(evidence_records)
    mix = _mix(groups)
    producer_n = sum(1 for row in admissible if row.get("origin") == "producer" and row.get("evidence", {}).get("evidence_lane") == _EVIDENCE.LANES_VIRTUAL)
    synthetic_n = sum(1 for row in admissible if row.get("origin") == "synthetic" and row.get("evidence", {}).get("evidence_lane") == _EVIDENCE.LANES_VIRTUAL)
    caller_n = sum(1 for row in admissible if row.get("origin") == "caller" and row.get("evidence", {}).get("evidence_lane") == _EVIDENCE.LANES_VIRTUAL)
    if len(groups) == 1 and mix is None:
        only = next(iter(separated.values()))
        cohort_metrics = only.get("metrics") if only.get("state") == "MEASURED" else None
        measurement = bool(only.get("expectancy_demonstrated")) if only.get("state") == "MEASURED" else False
        state = only.get("state")
        reason = None if state == "MEASURED" else only.get("reason")
    elif len(groups) == 0:
        cohort_metrics = None
        measurement = False
        state = "EMPTY"
        reason = None
    else:
        cohort_metrics = None
        measurement = False
        state = "BLOCKED"
        reason = mix or "LEDGER_REJECTED"
    real_metrics = cohort_metrics if producer_n and len(groups) == 1 and synthetic_n == 0 and caller_n == 0 else None
    out = {
        "contract": CONTRACT,
        "state": state if state in {"MEASURED", "EMPTY"} else "BLOCKED",
        "transition": ["OBSERVED", "VALIDATED", "MEASURED"] if state == "MEASURED" and real_metrics is not None else ["OBSERVED"],
        "reason": reason,
        "reasons": [] if reason is None else _order([reason]),
        "accepted": real_metrics is not None,
        "admissible_n": producer_n + synthetic_n + caller_n,
        "producer_admissible_n": producer_n,
        "synthetic_admissible_n": synthetic_n,
        "caller_admissible_n": caller_n,
        "metrics": real_metrics,
        "synthetic_metrics": cohort_metrics if producer_n == 0 else None,
        "separated": separated or None,
        "blended": False,
        "measurement_contract_met": measurement if producer_n == 0 or real_metrics is not None else False,
        "expectancy_demonstrated": measurement if real_metrics is not None else False,
        "profitability_status": "UNKNOWN" if producer_n == 0 else "UNCONFIRMED",
        "journal_written": False,
        "journal_unchanged": (path.read_bytes() if path.exists() else None) == before_journal,
        "partial_adopted": False,
        "included_n": producer_n if real_metrics is not None else 0,
    }
    out.update(_safety())
    if producer_n == 0:
        out["expectancy_demonstrated"] = False
        out["metrics"] = None
        out["accepted"] = False
    _attach_legacy(out, before, legacy)
    return out


def _mix(groups):
    keys = list(groups)
    if len(keys) <= 1:
        return None
    if len({key[0] for key in keys}) > 1:
        return "MIXED_EVIDENCE_LANES"
    if len({key[1] for key in keys}) > 1:
        return "MIXED_STRATEGY_IDS"
    if len({key[2] for key in keys}) > 1:
        return "MIXED_STRATEGY_VERSIONS"
    if len({key[3] for key in keys}) > 1:
        return "MIXED_SAMPLE_ROLES"
    return "LEDGER_REJECTED"
