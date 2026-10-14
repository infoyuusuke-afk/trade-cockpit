"""Synthetic MS2 observation/receipt contract — PURE and OFFLINE.

This is a forward-only candidate contract. It is NOT a producer, persistent
writer, authenticator, market-data adapter, order interface or PIT attestation.
All output contains reason/count categories, never private symbols or raw values.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import re

from scripts import local_source_health_contract as source_health

SCHEMA_VERSION = "ms2-observation-receipt-0.1"
DECISION_SCHEMA = "ms2-observation-decision-0.1"
REQUIRED_STREAMS = frozenset({"MARKET_SNAPSHOT", "CONDITION", "UNDER_OVER"})
STREAMS = REQUIRED_STREAMS | {"SIGNAL"}
PHASES = frozenset({"PRE_QUEUE_DROP", "QUEUED", "POST_QUEUE_REJECT", "PERSISTENCE_CLAIM"})
CAPTURE_FIELDS = frozenset({
    "schema_version", "producer_sha", "session_id", "poll_seq", "symbol",
    "stream", "record_sha256", "read_started_at", "read_finished_at",
    "available_at", "created_at",
})
RECEIPT_FIELDS = frozenset({
    "schema_version", "session_id", "poll_seq", "symbol", "stream",
    "record_sha256", "phase", "at",
})
DECISION_FIELDS = frozenset({
    "schema_version", "session_id", "poll_seq", "symbol", "decision_at",
    "input_streams",
})
TIME_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SESSION = re.compile(r"^[0-9a-f]{32}$")


class ContractError(Exception):
    def __init__(self, code: str):
        self.code = code


def _time(value: object) -> datetime:
    if not isinstance(value, str) or not TIME_FORMAT.fullmatch(value):
        raise ContractError("TIMEZONE_OR_TIMESTAMP_INVALID")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("missing timezone")
        return result
    except ValueError as exc:
        raise ContractError("TIMEZONE_OR_TIMESTAMP_INVALID") from exc


def _identity(record: dict) -> tuple[str, int, str, str]:
    if not isinstance(record, dict):
        raise ContractError("RECORD_SHAPE_INVALID")
    if not isinstance(record.get("session_id"), str) or not SESSION.fullmatch(record["session_id"]):
        raise ContractError("SESSION_ID_INVALID")
    seq = record.get("poll_seq")
    if type(seq) is not int or seq <= 0:
        raise ContractError("POLL_SEQ_INVALID")
    symbol = record.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 64:
        raise ContractError("SYMBOL_INVALID")
    stream = record.get("stream")
    if stream not in STREAMS:
        raise ContractError("STREAM_INVALID")
    return (record["session_id"], seq, symbol, stream)


def _capture(record: dict) -> tuple[tuple, tuple[datetime, ...]]:
    if not isinstance(record, dict) or record.keys() != CAPTURE_FIELDS:
        raise ContractError("CAPTURE_FIELDS_INVALID")
    key = _identity(record)
    if record["schema_version"] != SCHEMA_VERSION:
        raise ContractError("SCHEMA_INVALID")
    if not isinstance(record["producer_sha"], str) or not SHA.fullmatch(record["producer_sha"]):
        raise ContractError("PRODUCER_SHA_INVALID")
    if not isinstance(record["record_sha256"], str) or not DIGEST.fullmatch(record["record_sha256"]):
        raise ContractError("RECORD_DIGEST_INVALID")
    start, finish, available, created = (
        _time(record[field]) for field in
        ("read_started_at", "read_finished_at", "available_at", "created_at")
    )
    if not start <= finish <= available <= created:
        raise ContractError("CAPTURE_TEMPORAL_ORDER_INVALID")
    return key, (start, finish, available, created)


def _receipt(record: dict) -> tuple[tuple, datetime]:
    if not isinstance(record, dict) or record.keys() != RECEIPT_FIELDS:
        raise ContractError("RECEIPT_FIELDS_INVALID")
    key = _identity(record)
    if record["schema_version"] != SCHEMA_VERSION:
        raise ContractError("SCHEMA_INVALID")
    if record["phase"] not in PHASES:
        raise ContractError("RECEIPT_PHASE_INVALID")
    if not isinstance(record["record_sha256"], str) or not DIGEST.fullmatch(record["record_sha256"]):
        raise ContractError("RECORD_DIGEST_INVALID")
    return key, _time(record["at"])


def _decision(record: dict) -> tuple[tuple, datetime, tuple[str, ...]]:
    if not isinstance(record, dict) or record.keys() != DECISION_FIELDS:
        raise ContractError("DECISION_FIELDS_INVALID")
    if record.get("schema_version") != DECISION_SCHEMA:
        raise ContractError("DECISION_SCHEMA_INVALID")
    ident = dict(record, stream="SIGNAL")
    key = _identity(ident)
    streams = record["input_streams"]
    if not isinstance(streams, list) or not streams or len(streams) != len(set(map(str, streams))):
        raise ContractError("DECISION_INPUTS_INVALID")
    if not all(isinstance(s, str) and s in REQUIRED_STREAMS for s in streams):
        raise ContractError("DECISION_INPUTS_INVALID")
    return key, _time(record["decision_at"]), tuple(streams)


def evaluate(captures: list[dict], receipts: list[dict],
             health_snapshot: dict, decisions: list[dict] | None = None) -> dict:
    """Return anonymous conservative states; no source/PIT/persistence attestation."""
    reasons: Counter[str] = Counter()
    phases: Counter[str] = Counter()
    out = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED",
        "reason_counts": {},
        "receipt_state_counts": {},
        "capture_count": 0,
        "poll_groups": 0,
        "decision_count": 0,
        "source_authenticated": False,
        "shared_poll_durability_proven": False,
        "persisted_verified": False,
        "decision_asof_proven": False,
        "pit_research_eligible": False,
        "shadow_forward_eligible": False,
        "performance_eligible": False,
        "eligible_observed_n": 0,
        "real_submit_allowed": False,
        "promotion_eligible": False,
        "statistical_edge_confirmed": False,
    }

    if not isinstance(captures, list) or not isinstance(receipts, list) or not isinstance(decisions, (list, type(None))):
        reasons["INPUT_COLLECTION_INVALID"] += 1
        out["reason_counts"] = dict(sorted(reasons.items()))
        return out

    if not source_health.validate(health_snapshot):
        reasons["SOURCE_HEALTH_CONTRACT_INVALID"] += 1
    elif (health_snapshot.get("source") != "MS2_RSS" or
          health_snapshot.get("state") != "HEALTHY" or
          health_snapshot["consecutive_failures"] != 0 or
          health_snapshot["reasons"] or
          health_snapshot.get("last_data_at") is None):
        reasons["SOURCE_HEALTH_NOT_READY"] += 1
    else:
        try:
            if _time(health_snapshot["last_data_at"]) > _time(health_snapshot["observed_at"]):
                reasons["SOURCE_HEALTH_CLOCK_INVALID"] += 1
        except ContractError:
            reasons["SOURCE_HEALTH_CLOCK_INVALID"] += 1

    records: dict[tuple, dict] = {}
    times: dict[tuple, tuple[datetime, ...]] = {}
    by_poll: defaultdict[tuple, set[str]] = defaultdict(set)
    producers: dict[str, str] = {}
    seqs: defaultdict[tuple, set[int]] = defaultdict(set)
    for item in captures:
        try:
            key, timestamps = _capture(item)
        except ContractError as exc:
            reasons[exc.code] += 1
            continue
        session, seq, symbol, stream = key
        previous_producer = producers.setdefault(session, item["producer_sha"])
        if previous_producer != item["producer_sha"]:
            reasons["SESSION_PRODUCER_CONFLICT"] += 1
        if key in records:
            if records[key] != item:
                reasons["CAPTURE_IDENTITY_CONFLICT"] += 1
            continue  # exact duplicate is idempotent
        records[key] = item
        times[key] = timestamps
        by_poll[(session, seq, symbol)].add(stream)
        seqs[(session, symbol)].add(seq)

    out["capture_count"] = len(records)
    out["poll_groups"] = len(by_poll)
    if not records:
        reasons["NO_CAPTURE_EVIDENCE"] += 1

    for present in by_poll.values():
        if present & REQUIRED_STREAMS and not REQUIRED_STREAMS.issubset(present):
            reasons["REQUIRED_STREAM_NOT_CAPTURED"] += 1
        if present == {"SIGNAL"}:
            reasons["SIGNAL_WITHOUT_SOURCE_POLL"] += 1
    for observed in seqs.values():
        if max(observed) - min(observed) + 1 != len(observed):
            reasons["OBSERVED_POLL_SEQ_GAP"] += 1

    receipt_events: dict[tuple, datetime] = {}
    for item in receipts:
        try:
            key, event_at = _receipt(item)
        except ContractError as exc:
            reasons[exc.code] += 1
            continue
        if key not in records:
            reasons["RECEIPT_WITHOUT_CAPTURE"] += 1
            continue
        if item["record_sha256"] != records[key]["record_sha256"]:
            reasons["RECEIPT_IDENTITY_CONFLICT"] += 1
            continue
        if event_at < times[key][3]:
            reasons["RECEIPT_PRECEDES_CREATION"] += 1
            continue
        phase_key = (key, item["phase"])
        prev = receipt_events.get(phase_key)
        if prev is not None:
            if prev != event_at:
                reasons["RECEIPT_EVENT_CONFLICT"] += 1
            continue
        receipt_events[phase_key] = event_at

    receipts_by_key: defaultdict[tuple, dict[str, datetime]] = defaultdict(dict)
    for (key, phase), when in receipt_events.items():
        receipts_by_key[key][phase] = when
    for key in records:
        items = receipts_by_key.get(key, {})
        if not items:
            phases["UNKNOWN_NO_RECEIPT"] += 1
            reasons["RECEIPT_MISSING"] += 1
        elif "PRE_QUEUE_DROP" in items:
            if len(items) != 1:
                reasons["ILLEGAL_RECEIPT_TRANSITION"] += 1
                phases["CONFLICT"] += 1
            else:
                phases["DROPPED_PRE_QUEUE"] += 1
        elif "QUEUED" not in items:
            phases["CONFLICT"] += 1
            reasons["CLAIM_OR_REJECTION_WITHOUT_QUEUE"] += 1
        elif ("PERSISTENCE_CLAIM" in items and "POST_QUEUE_REJECT" in items):
            phases["CONFLICT"] += 1
            reasons["ILLEGAL_RECEIPT_TRANSITION"] += 1
        elif "PERSISTENCE_CLAIM" in items:
            if items["PERSISTENCE_CLAIM"] < items["QUEUED"]:
                phases["CONFLICT"] += 1
                reasons["CLAIM_BEFORE_QUEUE"] += 1
            else:
                phases["PERSISTENCE_CLAIM_UNVERIFIED"] += 1
        elif "POST_QUEUE_REJECT" in items:
            if items["POST_QUEUE_REJECT"] < items["QUEUED"]:
                phases["CONFLICT"] += 1
                reasons["REJECTION_BEFORE_QUEUE"] += 1
            else:
                phases["REJECTED_AFTER_QUEUE"] += 1
        else:
            phases["UNKNOWN_QUEUED_NOT_PERSISTED"] += 1
            reasons["PERSISTENCE_UNCONFIRMED"] += 1

    for item in decisions or []:
        try:
            (session, seq, symbol, _stream), asof, refs = _decision(item)
        except ContractError as exc:
            reasons[exc.code] += 1
            continue
        out["decision_count"] += 1
        for stream in refs:
            key = (session, seq, symbol, stream)
            if key not in records:
                reasons["DECISION_INPUT_MISSING"] += 1
            elif times[key][2] > asof or times[key][3] > asof:
                reasons["DECISION_REFERENCES_FUTURE_INPUT"] += 1
            elif "PERSISTENCE_CLAIM" not in receipts_by_key.get(key, {}):
                reasons["DECISION_INPUT_NOT_PERSISTED"] += 1

    out["reason_counts"] = dict(sorted(reasons.items()))
    out["receipt_state_counts"] = dict(sorted(phases.items()))
    if not reasons:
        out["status"] = "STRUCTURALLY_CONSISTENT_UNATTESTED"
    return out
