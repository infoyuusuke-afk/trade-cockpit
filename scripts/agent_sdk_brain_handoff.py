"""Opt-in signed, non-tradable Agents SDK -> private Brain RESEARCH inbox.

This is a SIDE-CAR pilot, NOT a modification of V10's existing live Brain,
its market-data safety gates, its trading path or its existing context schema.
Local HMAC proves possession of a configured secret, NOT official market truth.
No model call, internet, API key, scheduler or broker capability here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import sys

try:
    from scripts import agent_sdk_coordination_pilot as pilot
except ModuleNotFoundError:
    import agent_sdk_coordination_pilot as pilot

SCHEMA = "100b-agent-brain-research-envelope-v1"
ACK_SCHEMA = "100b-agent-brain-research-ack-v1"
MAX_BYTES = 65_536
MAX_HANDOFF_AGE = timedelta(minutes=15)
MAX_SOURCE_AGE = timedelta(days=7)
KEY_ENV = "AGENT_BRIDGE_HMAC_KEY"
SIG_RE = re.compile(r"^[0-9a-f]{64}$")


class BridgeBlocked(ValueError):
    pass


def _canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _key():
    raw = os.environ.get(KEY_ENV, "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        raise BridgeBlocked("PRIVATE_HMAC_KEY_MISSING_OR_INVALID")
    return bytes.fromhex(raw)


def _dt(raw):
    return pilot._time(raw).astimezone(timezone.utc)


def _now(value):
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise BridgeBlocked("LOCAL_CLOCK_UNVERIFIED")
    return value.astimezone(timezone.utc)


def _private_dir(path):
    p = Path(path)
    if (not p.is_absolute() or str(p).startswith(("\\\\", "//"))
            or ".." in p.parts or not p.is_dir()):
        raise BridgeBlocked("PRIVATE_DIRECTORY_INVALID")
    project = Path(__file__).resolve().parent.parent
    if p == project or project in p.parents:
        raise BridgeBlocked("PRIVATE_DIRECTORY_INSIDE_REPOSITORY")
    for part in (p, *p.parents):
        mode = part.lstat()
        if (stat.S_ISLNK(mode.st_mode) or
                bool(getattr(mode, "st_file_attributes", 0) & 0x400)):
            raise BridgeBlocked("PRIVATE_DIRECTORY_LINK_UNTRUSTED")
    return p


def _read_once(path, private_dir):
    p = Path(path)
    if p.parent != private_dir or p.is_symlink() or not p.name.startswith("agent_research_"):
        raise BridgeBlocked("INBOX_PATH_INVALID")
    before = p.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 2 <= before.st_size <= MAX_BYTES):
        raise BridgeBlocked("INBOX_FILE_INVALID")
    with p.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
        middle = os.fstat(handle.fileno())
    after = p.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink)
    if (len(raw) != before.st_size or identity(before) != identity(middle)
            or identity(before) != identity(after)):
        raise BridgeBlocked("INBOX_CHANGED_DURING_READ")
    try:
        def unique(pairs):
            out = {}
            for k, v in pairs:
                if k in out:
                    raise BridgeBlocked("JSON_DUPLICATE_KEY")
                out[k] = v
            return out
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              BridgeBlocked("JSON_NONFINITE")))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise BridgeBlocked("INBOX_JSON_INVALID") from exc


def _write_once(path, content):
    if len(content) > MAX_BYTES:
        raise BridgeBlocked("INBOX_TOO_LARGE")
    if path.exists() or path.is_symlink():
        raise BridgeBlocked("DUPLICATE_HANDOFF_OR_ACK_BLOCKED")
    try:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise BridgeBlocked("DUPLICATE_HANDOFF_OR_ACK_BLOCKED") from exc
    # Never overwrite an existing message: crash leaves an inspectable trace.


def _validate_result(source, result, *, now):
    # No model-generated ability to cross the trade gate. Exact fields only.
    valid_source = pilot.validate_snapshot(source, now)
    if type(result) is not dict or set(result) != {
        "schema_version", "run_id", "evaluated_at", "state", "specialists",
        "coordinator", "actual_profit_yen", "costs_verified",
        "broker_fills_verified", "promotion_eligible", "real_submit_allowed"
    }:
        raise BridgeBlocked("MODEL_RESULT_SCHEMA_INVALID")
    if (result["schema_version"] != "100b-agent-bridge-result-v1"
            or result["run_id"] != source["run_id"]
            or result["state"] not in (
                "RESEARCH_ONLY_NOT_LIVE", "OFFLINE_SYNTHETIC_NO_API_CALL"
            ) or result["actual_profit_yen"] is not None
            or any(result[k] is not False for k in (
                "costs_verified", "broker_fills_verified", "promotion_eligible",
                "real_submit_allowed"
            ))):
        raise BridgeBlocked("MODEL_RESULT_SAFETY_GATE_INVALID")
    evaluated = _dt(result["evaluated_at"])
    if evaluated > now or not timedelta(0) <= now - evaluated <= MAX_HANDOFF_AGE:
        raise BridgeBlocked("MODEL_RESULT_STALE_OR_FUTURE")
    if (type(result["specialists"]) is not list
            or len(result["specialists"]) != len(pilot.ROLES)):
        raise BridgeBlocked("SPECIALIST_COUNT_INVALID")
    by_role = {}
    for item in result["specialists"]:
        role = item.get("role") if type(item) is dict else None
        if role not in pilot.ROLES or role in by_role:
            raise BridgeBlocked("SPECIALIST_DUPLICATE_OR_INVALID_ROLE")
        if (set(item) != {
            "role", "status", "evidence_ids", "hypothesis",
            "invalidation", "real_submit_allowed"
        } or item.get("real_submit_allowed") is not False):
            raise BridgeBlocked("SPECIALIST_RESULT_FIELDS_OR_SAFETY_INVALID")
        assigned = [x for x in valid_source["sources"] if x["role"] == role]
        if not assigned:
            if (item.get("status") != "NO_DATA" or
                    item.get("evidence_ids") != [] or
                    item.get("real_submit_allowed") is not False):
                raise BridgeBlocked("NO_DATA_ROLE_MISMATCH")
        else:
            if item.get("status") == "NO_DATA":
                raise BridgeBlocked("FALSE_NO_DATA")
            pilot.validate_specialist(role, item, assigned)
        by_role[role] = item
    if set(by_role) != set(pilot.ROLES):
        raise BridgeBlocked("SPECIALIST_ROLE_MISSING")
    if (type(result["coordinator"]) is not dict or
            set(result["coordinator"]) != {
                "summary", "conflicts", "next_checks", "real_submit_allowed"
            }):
        raise BridgeBlocked("COORDINATOR_RESULT_FIELDS_INVALID")
    pilot.validate_coordinator(result["coordinator"])
    if result["coordinator"].get("real_submit_allowed") is not False:
        raise BridgeBlocked("COORDINATOR_ORDER_FLAG_UNSAFE")
    for row in valid_source["sources"]:
        available = _dt(row["available_at"])
        if available > evaluated or evaluated - available > MAX_SOURCE_AGE:
            raise BridgeBlocked("SOURCE_STALE_AT_EVALUATION")
    return valid_source


def produce(source, result, *, private_dir, now):
    """Manual opt-in. Must be after a validated research result, no API call."""
    now = _now(now)
    root = _private_dir(private_dir)
    doc = _validate_result(source, result, now=now)
    payload = {
        "run_id": doc["run_id"],
        "evaluated_at": result["evaluated_at"],
        "emitted_at": now.isoformat(),
        "source_fingerprint_sha256": pilot.fingerprint(doc),
        "sources": doc,
        "research": result,
        "data_lane": "PUBLIC_RESEARCH_UNAUTHENTICATED_NOT_EXECUTION",
        "brain_trade_decision_eligible": False,
        "real_submit_allowed": False,
    }
    digest = hmac.new(_key(), _canon(payload), hashlib.sha256).hexdigest()
    wrapper = {"schema_version": SCHEMA, "payload": payload, "hmac_sha256": digest}
    target = root / ("agent_research_" + doc["run_id"] + ".json")
    _write_once(target, _canon(wrapper) + b"\n")
    return target


def consume(*, input_path, private_dir, now, write_ack=False):
    """One-shot independent readback. Research ACK != Brain live verification."""
    now = _now(now)
    root = _private_dir(private_dir)
    doc = _read_once(Path(input_path), root)
    if type(doc) is not dict or set(doc) != {"schema_version", "payload", "hmac_sha256"}:
        raise BridgeBlocked("ENVELOPE_SCHEMA_INVALID")
    if doc["schema_version"] != SCHEMA or not isinstance(doc["hmac_sha256"], str):
        raise BridgeBlocked("ENVELOPE_VERSION_INVALID")
    if not SIG_RE.fullmatch(doc["hmac_sha256"]):
        raise BridgeBlocked("SIGNATURE_FORMAT_INVALID")
    if not hmac.compare_digest(
        hmac.new(_key(), _canon(doc["payload"]), hashlib.sha256).hexdigest(),
        doc["hmac_sha256"]
    ):
        raise BridgeBlocked("HANDOFF_AUTHENTICATION_FAILED")
    payload = doc["payload"]
    if type(payload) is not dict or set(payload) != {
        "run_id", "evaluated_at", "emitted_at", "source_fingerprint_sha256",
        "sources", "research", "data_lane", "brain_trade_decision_eligible",
        "real_submit_allowed"
    }:
        raise BridgeBlocked("PAYLOAD_SCHEMA_INVALID")
    if (payload["brain_trade_decision_eligible"] is not False or
            payload["real_submit_allowed"] is not False or
            payload["data_lane"] != "PUBLIC_RESEARCH_UNAUTHENTICATED_NOT_EXECUTION"
            or payload["run_id"] != payload["sources"].get("run_id")
            or payload["source_fingerprint_sha256"] != pilot.fingerprint(payload["sources"])):
        raise BridgeBlocked("PAYLOAD_SOURCE_BINDING_INVALID")
    emitted = _dt(payload["emitted_at"])
    if emitted > now or not timedelta(0) <= now - emitted <= MAX_HANDOFF_AGE:
        raise BridgeBlocked("HANDOFF_STALE_OR_FUTURE")
    _validate_result(payload["sources"], payload["research"], now=now)
    if Path(input_path).name != "agent_research_" + payload["run_id"] + ".json":
        raise BridgeBlocked("HANDOFF_FILENAME_MISMATCH")
    ack = {
        "schema_version": ACK_SCHEMA,
        "run_id": payload["run_id"],
        "envelope_sha256": hashlib.sha256(_canon(doc)).hexdigest(),
        "received_at": now.isoformat(),
        "state": "RESEARCH_ONLY_ACK_RECEIVED_NOT_BRAIN_LIVE",
        "real_submit_allowed": False,
        "brain_trade_decision_eligible": False,
    }
    if write_ack:
        name = root / ("agent_research_" + payload["run_id"] + ".ack.json")
        _write_once(name, _canon(ack) + b"\n")
    return ack


def main(argv=None):
    p = argparse.ArgumentParser(description="Private research-only ACK sidecar; no V10 writes")
    p.add_argument("--consume", required=True, help="Exact owner-selected research JSON")
    p.add_argument("--private-dir", required=True, help="Same private root as research JSON")
    p.add_argument("--write-ack", action="store_true", help="Create one private receipt, no overwrite")
    args = p.parse_args(argv)
    try:
        ack = consume(input_path=args.consume, private_dir=args.private_dir,
                      now=datetime.now(timezone.utc), write_ack=args.write_ack)
        print(json.dumps(ack, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"state": "BLOCKED", "reason": str(exc) if isinstance(
            exc, BridgeBlocked) else "HANDOFF_INPUT_UNVERIFIED",
                          "real_submit_allowed": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
