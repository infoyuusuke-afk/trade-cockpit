"""V10 Brain-side receiver for signed Agents SDK research (research lane only).

PROJECT_ITEM_ID: P0-AGENTS-SDK-V10-BRAIN-INTEGRATION-20261021

The Agents SDK sidecar (scripts/agent_sdk_brain_handoff.py) writes signed,
non-tradable research envelopes ``agent_research_<run_id>.json`` into an
OWNER-selected private inbox. This module is the RECEIVING end that the V10
Brain runs (one-shot, ``--once``): it reads each envelope once, verifies those
exact bytes, stores a durable receipt, and writes its own Brain ACK.

Kept apart on purpose:
- Two keys. The envelope is verified with the sidecar key
  (AGENT_BRIDGE_HMAC_KEY). The Brain ACK is signed with a separate receiver
  key (AGENT_BRAIN_RECEIVER_HMAC_KEY) that the sidecar must not hold; the two
  must differ. A file signed with the sidecar key is not a Brain ACK.
- The sidecar's own ``*.ack.json`` is never read or counted. Only this
  receiver writes ``*.brain_ack.json`` with ``ack_kind=BRAIN_RECEIVER_ACK``.
- Research stays a research-lane input for Shadow / post-hoc review: never
  LIVE-authenticated market data, never a trade decision,
  ``real_submit_allowed`` always false.
- No network, broker, subprocess, timer, scheduler or paid API code. It does
  not touch the 31 pinned V10 runtime files, Excel or the running Brain.

Durability: receipts live in a private SQLite file
(``brain_agent_research_receipts.sqlite``, BEGIN IMMEDIATE, synchronous=FULL,
rollback journal) together with the exact canonical ACK bytes. If the process
stops after the receipt is committed but before the ACK file exists, the next
pass rewrites the ACK from the stored bytes (hash-checked). A run_id is
received at most once.

States per envelope:
  RECEIVED            verified and stored; Brain ACK written
  DUPLICATE_REJECTED  a verified envelope whose run_id was already received
  BLOCKED             verification failed (fail-closed, reason recorded once
                      per file content; the same unchanged file is not re-logged)
  PENDING             present in the inbox, not processed yet. The sidecar's
                      15-minute freshness window applies: --status shows when
                      each pending envelope expires; after that it is BLOCKED
                      (stale) and the research must be re-run.
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
import re
import sqlite3
import sys

if __package__:
    from . import agent_sdk_brain_handoff as handoff
else:  # direct file mode resolves the sibling script, never a global package
    import agent_sdk_brain_handoff as handoff

RECEIVER_COMPONENT = "v10-brain-agent-research-receiver"
ACK_SCHEMA = "100b-v10-brain-agent-research-ack-v2"
ACK_KIND = "BRAIN_RECEIVER_ACK"
RECEIVER_KEY_ENV = "AGENT_BRAIN_RECEIVER_HMAC_KEY"
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


def _receiver_key() -> bytes:
    raw = os.environ.get(RECEIVER_KEY_ENV, "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        raise ReceiverBlocked("RECEIVER_HMAC_KEY_MISSING_OR_INVALID")
    key = bytes.fromhex(raw)
    if hmac.compare_digest(key, handoff._key()):
        raise ReceiverBlocked("RECEIVER_KEY_MUST_DIFFER_FROM_SIDECAR_KEY")
    return key


def _sign(body: dict) -> str:
    return hmac.new(_receiver_key(), _canon(body), hashlib.sha256).hexdigest()


def receiver_identity(host_component=None) -> dict:
    """Self-reported identity of the receiving process (not proof by itself).

    host_component names the V10 process that runs the receiver in-process
    (for example the Brain observer); None means the standalone CLI.
    """
    code = Path(__file__).resolve().read_bytes()
    return {
        "component": RECEIVER_COMPONENT,
        "host_component": host_component or "standalone-cli",
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
        " ack_bytes BLOB NOT NULL,"
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


def _ack_path(root: Path, run_id: str) -> Path:
    return root / (INBOX_PREFIX + run_id + BRAIN_ACK_SUFFIX)


def _ack_file_matches(path: Path, ack_bytes: bytes) -> bool:
    try:
        return path.read_bytes() == ack_bytes
    except OSError:
        return False


def _ensure_ack(root: Path, run_id: str, ack_bytes: bytes, ack_sha: str) -> str:
    """Write the stored ACK if it is missing; never overwrite a different file."""
    if hashlib.sha256(ack_bytes).hexdigest() != ack_sha:
        raise ReceiverBlocked("STORED_ACK_HASH_MISMATCH")
    path = _ack_path(root, run_id)
    if path.exists() or path.is_symlink():
        return "ACK_PRESENT" if _ack_file_matches(path, ack_bytes) else "ACK_MISMATCH"
    handoff._write_once(path, ack_bytes)
    back = json.loads(path.read_bytes().decode("utf-8"))
    body = {k: v for k, v in back.items() if k != "hmac_sha256"}
    if path.read_bytes() != ack_bytes or not hmac.compare_digest(_sign(body), back["hmac_sha256"]):
        raise ReceiverBlocked("BRAIN_ACK_INDEPENDENT_READBACK_FAILED")
    return "ACK_WRITTEN"


def receive_one(path: Path, root: Path, conn, *, now: datetime, identity: dict) -> dict:
    """Read once, verify those exact bytes, store the receipt, then the ACK."""
    name = path.name
    file_sha = _file_sha(path)  # bookkeeping key only; verified content comes from the read below
    try:
        doc = handoff._read_once(path, root)            # the only read used for verification
        payload = handoff.verify_document(doc, file_name=name, now=now)
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
            "receiver_key_separate_from_sidecar": True,
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
        ack["hmac_sha256"] = _sign(ack)
        ack_bytes = _canon(ack) + b"\n"
        ack_sha = hashlib.sha256(ack_bytes).hexdigest()
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM receipts WHERE run_id = ? OR envelope_sha256 = ?",
                            (payload["run_id"], envelope_sha)).fetchone():
                conn.execute("ROLLBACK")
                _record_attempt(conn, name=name, file_sha=file_sha, run_id=payload["run_id"], now=now,
                                state="DUPLICATE_REJECTED", reason="RUN_ID_ALREADY_RECEIVED")
                return {"file": name, "state": "DUPLICATE_REJECTED", "reason": "RUN_ID_ALREADY_RECEIVED"}
            conn.execute(
                "INSERT INTO receipts (run_id, envelope_sha256, received_at, ack_bytes, ack_sha256,"
                " real_submit_allowed) VALUES (?,?,?,?,?,0)",
                (payload["run_id"], envelope_sha, _iso(now), ack_bytes, ack_sha))
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
    except (handoff.BridgeBlocked, handoff.pilot.Blocked, ReceiverBlocked) as exc:
        reason = str(exc)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        reason = "INBOX_INPUT_UNVERIFIED:" + type(exc).__name__
    else:
        # The receipt is committed. A failure from here on leaves the ACK to be
        # rewritten from the stored bytes on the next pass (no BLOCKED entry).
        try:
            ack_state = _ensure_ack(root, payload["run_id"], ack_bytes, ack_sha)
        except (OSError, ReceiverBlocked, handoff.BridgeBlocked) as exc:
            return {"file": name, "state": "RECEIVED", "run_id": payload["run_id"],
                    "ack": "ACK_WRITE_PENDING:" + (str(exc) or type(exc).__name__)}
        return {"file": name, "state": "RECEIVED", "run_id": payload["run_id"], "ack": ack_state,
                "conflicts": len(conflicts)}
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


def _file_sha(path: Path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def receive_inbox(private_dir, *, now: datetime, host_component=None) -> dict:
    """One pass: restore missing ACKs, then process new or changed inbox files."""
    now = handoff._now(now)
    root = handoff._private_dir(private_dir)
    handoff._key()      # no sidecar key: nothing can be verified
    _receiver_key()     # no separate receiver key: no Brain ACK can be signed
    identity = receiver_identity(host_component)
    results, restored = [], []
    with closing(_connect(root)) as conn:
        for run_id, ack_bytes, ack_sha in conn.execute(
                "SELECT run_id, ack_bytes, ack_sha256 FROM receipts ORDER BY received_at, run_id").fetchall():
            if not _ack_path(root, run_id).exists():
                restored.append({"run_id": run_id, "ack": _ensure_ack(root, run_id, bytes(ack_bytes), ack_sha)})
        seen = {(r[0], r[1]) for r in conn.execute(
            "SELECT file_name, file_sha256 FROM attempts WHERE file_sha256 IS NOT NULL")}
        for path in _inbox_files(root):
            sha = _file_sha(path)
            if sha is not None and (path.name, sha) in seen:
                continue  # this exact file content was already decided (received or blocked)
            results.append(receive_one(path, root, conn, now=now, identity=identity))
    return {"state": "PASS_COMPLETED", "receiver": RECEIVER_COMPONENT, "restored_acks": restored,
            "results": results, "real_submit_allowed": False}


def _pending_expiry(path: Path):
    """Unverified hint only: when the 15-minute freshness window would end."""
    try:
        doc = json.loads(path.read_bytes().decode("utf-8"))
        emitted = handoff._dt(doc["payload"]["emitted_at"])
        return _iso(emitted + handoff.MAX_HANDOFF_AGE)
    except Exception:
        return None


def status(private_dir) -> dict:
    """Receipts after a restart, plus inbox envelopes not yet received (PENDING)."""
    root = handoff._private_dir(private_dir)
    with closing(_connect(root)) as conn:
        rows = conn.execute("SELECT run_id, ack_bytes, ack_sha256 FROM receipts"
                            " ORDER BY received_at, run_id").fetchall()
        attempts = conn.execute("SELECT state, COUNT(*) FROM attempts GROUP BY state").fetchall()
        decided = {(r[0], r[1]) for r in conn.execute("SELECT file_name, file_sha256 FROM attempts")}
    received, mismatched, ack_missing = [], [], []
    for run_id, ack_bytes, ack_sha in rows:
        ack_bytes = bytes(ack_bytes)
        path = _ack_path(root, run_id)
        if hashlib.sha256(ack_bytes).hexdigest() != ack_sha:
            mismatched.append(run_id)
        elif not path.exists():
            ack_missing.append(run_id)
        elif _ack_file_matches(path, ack_bytes):
            received.append(run_id)
        else:
            mismatched.append(run_id)
    received_ids = {r[0] for r in rows}
    pending = []
    for p in _inbox_files(root):
        if p.name[len(INBOX_PREFIX):-len(".json")] in received_ids or (p.name, _file_sha(p)) in decided:
            continue
        pending.append({"file": p.name, "expires_at_unverified": _pending_expiry(p)})
    return {"receiver": RECEIVER_COMPONENT, "received_run_ids": received,
            "ack_mismatch_run_ids": mismatched, "ack_missing_run_ids": ack_missing,
            "pending": pending, "attempt_counts": dict(attempts), "real_submit_allowed": False}


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
