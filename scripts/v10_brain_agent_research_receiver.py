"""V10 Brain-side receiver for signed Agents SDK research (research lane only).

PROJECT_ITEM_ID: P0-AGENTS-SDK-V10-BRAIN-INTEGRATION-20261021

The Agents SDK sidecar (scripts/agent_sdk_brain_handoff.py) writes signed,
non-tradable research envelopes ``agent_research_<run_id>.json`` into an
OWNER-selected private inbox. This module is the RECEIVING end that the V10
Brain runs (one-shot, ``--once``): it independently re-verifies every
envelope, stores a durable receipt, and writes its own Brain ACK.

Kept apart on purpose:
- The sidecar's own ``*.ack.json`` (state RESEARCH_ONLY_ACK_RECEIVED_NOT_BRAIN_LIVE)
  is never read or counted here. Only this receiver writes
  ``*.brain_ack.json`` with ``ack_kind=BRAIN_RECEIVER_ACK`` and the receiving
  process identity.
- Research is stored as a research lane input for Shadow / post-hoc review. It
  is never promoted to LIVE-authenticated market data, never reaches a trade
  decision, and ``real_submit_allowed`` is always false.
- No network, broker, subprocess, timer, scheduler or paid API code. It does
  not touch the 31 pinned V10 runtime files, Excel or the running Brain.

Durability: receipts live in a private SQLite file
(``brain_agent_research_receipts.sqlite``, BEGIN IMMEDIATE, synchronous=FULL,
rollback journal). A restart reloads them; a run_id is accepted at most once.
Every ACK is read back independently after writing.

States per envelope:
  RECEIVED            verified and stored; Brain ACK written
  DUPLICATE_REJECTED  run_id already received (or the same file seen again)
  BLOCKED             verification failed (fail-closed, reason recorded)
  PENDING             present in the inbox, not yet processed by the receiver
Per specialist role the stored status stays exactly WATCH / NO_SIGNAL /
NO_DATA; an envelope that fails is BLOCKED as a whole. Disagreement between
roles and the coordinator's own conflicts are recorded, never resolved.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import sys

if __package__:
    from . import agent_sdk_brain_handoff as handoff
else:  # direct file mode resolves the sibling script, never a global package
    import agent_sdk_brain_handoff as handoff

RECEIVER_COMPONENT = "v10-brain-agent-research-receiver"
ACK_SCHEMA = "100b-v10-brain-agent-research-ack-v1"
ACK_KIND = "BRAIN_RECEIVER_ACK"
DB_NAME = "brain_agent_research_receipts.sqlite"
DATA_LANE = "PUBLIC_RESEARCH_UNAUTHENTICATED_NOT_EXECUTION"
INBOX_PREFIX = "agent_research_"
SIDECAR_ACK_SUFFIX = ".ack.json"
BRAIN_ACK_SUFFIX = ".brain_ack.json"
ROLE_STATUSES = ("WATCH", "NO_SIGNAL", "NO_DATA")


class ReceiverBlocked(ValueError):
    pass


def _canon(obj) -> bytes:
    return handoff._canon(obj)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def receiver_identity() -> dict:
    """Who received: this receiver's code hash and process, not the sidecar."""
    code = Path(__file__).resolve().read_bytes()
    return {
        "component": RECEIVER_COMPONENT,
        "receiver_code_sha256": hashlib.sha256(code).hexdigest(),
        "process_id": os.getpid(),
    }


def _connect(root: Path) -> sqlite3.Connection:
    db = root / DB_NAME
    if db.is_symlink():
        raise ReceiverBlocked("RECEIPT_DB_LINK_UNTRUSTED")
    conn = sqlite3.connect(str(db), timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS receipts ("
        " run_id TEXT PRIMARY KEY,"
        " envelope_sha256 TEXT NOT NULL UNIQUE,"
        " received_at TEXT NOT NULL,"
        " receiver_json TEXT NOT NULL,"
        " roles_json TEXT NOT NULL,"
        " conflicts_json TEXT NOT NULL,"
        " ack_sha256 TEXT NOT NULL,"
        " real_submit_allowed INTEGER NOT NULL CHECK (real_submit_allowed = 0))")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS attempts ("
        " seq INTEGER PRIMARY KEY AUTOINCREMENT,"
        " file_name TEXT NOT NULL,"
        " file_sha256 TEXT,"
        " run_id TEXT,"
        " evaluated_at TEXT NOT NULL,"
        " state TEXT NOT NULL CHECK (state IN ('RECEIVED','DUPLICATE_REJECTED','BLOCKED')),"
        " reason TEXT,"
        " real_submit_allowed INTEGER NOT NULL CHECK (real_submit_allowed = 0))")
    return conn


def _record_attempt(conn, *, name, file_sha, run_id, now, state, reason):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO attempts (file_name, file_sha256, run_id, evaluated_at, state, reason,"
            " real_submit_allowed) VALUES (?,?,?,?,?,?,0)",
            (name, file_sha, run_id, _iso(now), state, reason))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _roles_and_conflicts(research: dict) -> tuple[list, list]:
    roles = []
    for item in research["specialists"]:
        status = item["status"]
        if status not in ROLE_STATUSES:
            raise ReceiverBlocked("ROLE_STATUS_UNKNOWN")
        roles.append({"role": item["role"], "status": status,
                      "evidence_ids": list(item["evidence_ids"])})
    roles.sort(key=lambda r: r["role"])
    conflicts = [{"kind": "COORDINATOR_REPORTED", "text": text}
                 for text in research["coordinator"]["conflicts"]]
    observed = {r["status"] for r in roles if r["status"] != "NO_DATA"}
    if len(observed) > 1:
        conflicts.append({"kind": "ROLE_STATUS_DIVERGENCE",
                          "text": ",".join(r["role"] + "=" + r["status"] for r in roles)})
    return roles, conflicts


def _write_ack(root: Path, ack: dict) -> Path:
    name = root / (INBOX_PREFIX + ack["run_id"] + BRAIN_ACK_SUFFIX)
    handoff._write_once(name, _canon(ack) + b"\n")
    back = json.loads(name.read_bytes().decode("utf-8"))
    body = {k: v for k, v in back.items() if k != "hmac_sha256"}
    if back != ack or not hmac.compare_digest(
            hmac.new(handoff._key(), _canon(body), hashlib.sha256).hexdigest(), back["hmac_sha256"]):
        raise ReceiverBlocked("BRAIN_ACK_INDEPENDENT_READBACK_FAILED")
    return name


def receive_one(path: Path, root: Path, conn, *, now: datetime, identity: dict) -> dict:
    """Verify one envelope; on success store the receipt then write the ACK."""
    name = path.name
    file_sha = None
    try:
        raw = path.read_bytes()
        file_sha = hashlib.sha256(raw).hexdigest()
        known = conn.execute("SELECT run_id FROM receipts WHERE run_id = ?",
                             (name[len(INBOX_PREFIX):-len(".json")],)).fetchone()
        if known is not None:
            _record_attempt(conn, name=name, file_sha=file_sha, run_id=known[0], now=now,
                            state="DUPLICATE_REJECTED", reason="RUN_ID_ALREADY_RECEIVED")
            return {"file": name, "state": "DUPLICATE_REJECTED", "reason": "RUN_ID_ALREADY_RECEIVED"}
        # Independent re-verification: HMAC, exact schema, safety flags,
        # source binding, freshness, roles and NO_DATA rules. The sidecar's
        # ACK is not consulted; nothing is written by this call.
        handoff.consume(input_path=str(path), private_dir=str(root), now=now, write_ack=False)
        doc = handoff._read_once(path, root)
        payload = doc["payload"]
        research = payload["research"]
        if (payload.get("real_submit_allowed") is not False or research.get("real_submit_allowed") is not False
                or payload.get("brain_trade_decision_eligible") is not False
                or payload.get("data_lane") != DATA_LANE):
            raise ReceiverBlocked("REAL_ORDER_OR_LANE_FLAG_UNSAFE")
        envelope_sha = hashlib.sha256(_canon(doc)).hexdigest()
        roles, conflicts = _roles_and_conflicts(research)
        ack = {
            "schema_version": ACK_SCHEMA,
            "ack_kind": ACK_KIND,
            "run_id": payload["run_id"],
            "envelope_sha256": envelope_sha,
            "source_fingerprint_sha256": payload["source_fingerprint_sha256"],
            "received_at": _iso(now),
            "receiver": identity,
            "verification": "PASS",
            "state": "RECEIVED",
            "reasons": [],
            "roles": roles,
            "conflicts": conflicts,
            "data_lane": DATA_LANE,
            "live_market_data": False,
            "brain_trade_decision_eligible": False,
            "real_submit_allowed": False,
        }
        ack["hmac_sha256"] = hmac.new(handoff._key(), _canon(ack), hashlib.sha256).hexdigest()
        ack_sha = hashlib.sha256(_canon(ack)).hexdigest()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM receipts WHERE run_id = ? OR envelope_sha256 = ?",
                            (payload["run_id"], envelope_sha)).fetchone():
                conn.execute("ROLLBACK")
                _record_attempt(conn, name=name, file_sha=file_sha, run_id=payload["run_id"], now=now,
                                state="DUPLICATE_REJECTED", reason="RUN_ID_ALREADY_RECEIVED")
                return {"file": name, "state": "DUPLICATE_REJECTED", "reason": "RUN_ID_ALREADY_RECEIVED"}
            conn.execute(
                "INSERT INTO receipts (run_id, envelope_sha256, received_at, receiver_json, roles_json,"
                " conflicts_json, ack_sha256, real_submit_allowed) VALUES (?,?,?,?,?,?,?,0)",
                (payload["run_id"], envelope_sha, _iso(now), json.dumps(identity, sort_keys=True),
                 json.dumps(roles, ensure_ascii=False, sort_keys=True),
                 json.dumps(conflicts, ensure_ascii=False, sort_keys=True), ack_sha))
            conn.execute(
                "INSERT INTO attempts (file_name, file_sha256, run_id, evaluated_at, state, reason,"
                " real_submit_allowed) VALUES (?,?,?,?,'RECEIVED',NULL,0)",
                (name, file_sha, payload["run_id"], _iso(now)))
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        _write_ack(root, ack)
        return {"file": name, "state": "RECEIVED", "run_id": payload["run_id"], "conflicts": len(conflicts)}
    except (handoff.BridgeBlocked, handoff.pilot.Blocked, ReceiverBlocked) as exc:
        reason = str(exc)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        reason = "INBOX_INPUT_UNVERIFIED:" + type(exc).__name__
    _record_attempt(conn, name=name, file_sha=file_sha, run_id=None, now=now, state="BLOCKED", reason=reason)
    return {"file": name, "state": "BLOCKED", "reason": reason}


def _inbox_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.iterdir()):
        n = p.name
        if (n.startswith(INBOX_PREFIX) and n.endswith(".json")
                and not n.endswith(SIDECAR_ACK_SUFFIX) and not n.endswith(BRAIN_ACK_SUFFIX)):
            out.append(p)
    return out


def receive_inbox(private_dir, *, now: datetime) -> dict:
    """One pass over the inbox. Already received run_ids are not reprocessed."""
    now = handoff._now(now)
    root = handoff._private_dir(private_dir)
    handoff._key()  # no key, no verification: fail closed before reading anything
    identity = receiver_identity()
    results = []
    with closing(_connect(root)) as conn:
        done = {(r[0], r[1]) for r in conn.execute(
            "SELECT run_id, file_sha256 FROM attempts WHERE state = 'RECEIVED'")}
        for path in _inbox_files(root):
            run_id = path.name[len(INBOX_PREFIX):-len(".json")]
            try:
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                sha = None
            if (run_id, sha) in done and (root / (INBOX_PREFIX + run_id + BRAIN_ACK_SUFFIX)).exists():
                continue  # restart: this exact envelope was already received and acknowledged
            results.append(receive_one(path, root, conn, now=now, identity=identity))
    return {"state": "PASS_COMPLETED", "receiver": RECEIVER_COMPONENT, "results": results,
            "real_submit_allowed": False}


def status(private_dir) -> dict:
    """Receipts after a restart, plus inbox envelopes not yet received (PENDING)."""
    root = handoff._private_dir(private_dir)
    with closing(_connect(root)) as conn:
        rows = conn.execute("SELECT run_id, envelope_sha256, ack_sha256, roles_json, conflicts_json"
                            " FROM receipts ORDER BY received_at, run_id").fetchall()
        attempts = conn.execute("SELECT state, COUNT(*) FROM attempts GROUP BY state").fetchall()
    received, mismatched = [], []
    for run_id, env_sha, ack_sha, roles_json, conflicts_json in rows:
        ack_path = root / (INBOX_PREFIX + run_id + BRAIN_ACK_SUFFIX)
        ok = False
        if ack_path.exists():
            back = json.loads(ack_path.read_bytes().decode("utf-8"))
            ok = (hashlib.sha256(_canon(back)).hexdigest() == ack_sha and back.get("ack_kind") == ACK_KIND
                  and back.get("envelope_sha256") == env_sha and back.get("real_submit_allowed") is False)
        (received if ok else mismatched).append(run_id)
    pending = [p.name for p in _inbox_files(root)
               if p.name[len(INBOX_PREFIX):-len(".json")] not in {r[0] for r in rows}]
    return {"receiver": RECEIVER_COMPONENT, "received_run_ids": received,
            "ack_mismatch_run_ids": mismatched, "pending_files": pending,
            "attempt_counts": dict(attempts), "real_submit_allowed": False}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="V10 Brain receiver for signed agent research (research lane only)")
    p.add_argument("--private-dir", required=True, help="OWNER-selected private inbox (absolute)")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Receive every new envelope once, then exit")
    mode.add_argument("--status", action="store_true", help="Show receipts and pending envelopes")
    args = p.parse_args(argv)
    try:
        if args.once:
            out = receive_inbox(args.private_dir, now=datetime.now(timezone.utc))
        else:
            out = status(args.private_dir)
        print(json.dumps(out, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, (handoff.BridgeBlocked, ReceiverBlocked)) else "RECEIVER_UNVERIFIED"
        print(json.dumps({"state": "BLOCKED", "reason": reason, "real_submit_allowed": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
