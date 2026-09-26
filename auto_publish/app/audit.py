"""Hash-chained, append-only audit trail.

Each row's ``hash`` = sha256(prev_hash + canonical_json(row fields)). Editing or
deleting any row (DB triggers already forbid it) breaks the chain, which
``verify_chain`` detects.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .clock import Clock, iso_utc
from .hashing import canonical_json, sha256_text

GENESIS = "0" * 64


def _row_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return sha256_text(prev_hash + canonical_json(fields))


def append(
    conn: sqlite3.Connection,
    clock: Clock,
    *,
    actor: str,
    entity_type: str,
    entity_id: str,
    action: str,
    from_state: str | None = None,
    to_state: str | None = None,
    detail: dict | None = None,
) -> str:
    """Append one audit row. Must be called inside the caller's transaction so the
    audit row commits atomically with the change it describes."""
    last = conn.execute("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = last["hash"] if last else GENESIS
    fields = {
        "ts_utc": iso_utc(clock.now()),
        "actor": actor,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "from_state": from_state,
        "to_state": to_state,
        "detail_json": canonical_json(detail or {}),
    }
    h = _row_hash(prev_hash, fields)
    conn.execute(
        "INSERT INTO audit_log(ts_utc, actor, entity_type, entity_id, action, from_state, to_state, detail_json, prev_hash, hash)"
        " VALUES (:ts_utc, :actor, :entity_type, :entity_id, :action, :from_state, :to_state, :detail_json, :prev_hash, :hash)",
        {**fields, "prev_hash": prev_hash, "hash": h},
    )
    return h


def verify_chain(conn: sqlite3.Connection) -> dict:
    prev = GENESIS
    count = 0
    for row in conn.execute("SELECT * FROM audit_log ORDER BY seq"):
        fields = {k: row[k] for k in ("ts_utc", "actor", "entity_type", "entity_id", "action", "from_state", "to_state", "detail_json")}
        if row["prev_hash"] != prev or _row_hash(prev, fields) != row["hash"]:
            return {"ok": False, "broken_at_seq": row["seq"], "rows_checked": count}
        prev = row["hash"]
        count += 1
    return {"ok": True, "rows_checked": count, "head": prev}
