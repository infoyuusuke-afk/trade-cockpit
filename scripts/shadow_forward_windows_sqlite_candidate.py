"""Experimental, opt-in dual-DB SQLite private evidence candidate.

Not a production-backed durability guarantee. No existing runtime uses this.
Two independent SQLite transactions are NOT atomic together: partial commits
are detectable, not repaired or promoted. Windows power-loss durability and
independent fill authenticity require actual-machine acceptance.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

try:
    from .shadow_forward_private_path import require_resolved_private_path
except ImportError:
    from shadow_forward_private_path import require_resolved_private_path

SCHEMA="shadow-sqlite-candidate-v1"

def _hash(blob):
    return hashlib.sha256(blob).hexdigest()

def _db(repo_root, name):
    if name not in ("evidence","anchor"):
        raise ValueError("unrecognized store")
    rel=f"data/private/shadow_forward/sqlite_candidate/{name}.sqlite3"
    path=require_resolved_private_path(Path(repo_root),rel)
    path.parent.mkdir(parents=True,exist_ok=True)
    path=require_resolved_private_path(Path(repo_root),rel)
    return path

def _connect(path):
    conn=sqlite3.connect(str(path),timeout=2,isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA locking_mode=NORMAL")
    conn.execute("CREATE TABLE IF NOT EXISTS immutable_artifact (id TEXT PRIMARY KEY, schema TEXT NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL)")
    return conn

def _immutable_insert(conn,record_id,payload):
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO immutable_artifact(id,schema,payload,digest) VALUES(?,?,?,?)",
                     (record_id,SCHEMA,payload,_hash(payload)))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

def append_candidate(repo_root,record_id,evidence_bytes,anchor_hex,*,fail_after_evidence=False):
    """Store only with explicit opt-in caller; never return 'PRODUCTION_DURABLE'."""
    if not isinstance(record_id,str) or not record_id.isascii() or not (1<=len(record_id)<=120) or not all(c.isalnum() or c in "_-" for c in record_id):
        raise ValueError("invalid record_id")
    if not isinstance(evidence_bytes,bytes) or not evidence_bytes or len(evidence_bytes)>512*1024:
        raise ValueError("invalid evidence")
    if not isinstance(anchor_hex,str) or len(anchor_hex)!=64 or any(c not in "0123456789abcdef" for c in anchor_hex):
        raise ValueError("invalid independent anchor")
    evidence_path=_db(repo_root,"evidence")
    anchor_path=_db(repo_root,"anchor")
    if evidence_path==anchor_path:
        raise ValueError("separate stores required")
    # NEVER overwrite previous or partial artifact. Anchors are in another DB.
    # Preflight both sides first; races still fail at INSERT's primary key.
    for path in (evidence_path,anchor_path):
        with _connect(path) as conn:
            if conn.execute("SELECT 1 FROM immutable_artifact WHERE id=?",(record_id,)).fetchone():
                raise FileExistsError("previous or partial evidence requires manual review")
    with _connect(evidence_path) as conn:
        _immutable_insert(conn,record_id,evidence_bytes)
    if fail_after_evidence:
        raise OSError("injected failure after evidence commit")
    with _connect(anchor_path) as conn:
        _immutable_insert(conn,record_id,anchor_hex.encode("ascii"))
    return inspect_candidate(repo_root,record_id,expected_anchor=anchor_hex)

def inspect_candidate(repo_root,record_id,*,expected_anchor):
    if not isinstance(record_id,str) or not record_id.isascii() or not (1<=len(record_id)<=120) or not all(c.isalnum() or c in "_-" for c in record_id):
        return "BLOCK_INVALID_RECORD_ID"
    if not isinstance(expected_anchor,str) or len(expected_anchor)!=64:
        return "BLOCK_ANCHOR_INVALID"
    evidence_path=_db(repo_root,"evidence")
    anchor_path=_db(repo_root,"anchor")
    vals=[]
    for path in (evidence_path,anchor_path):
        with _connect(path) as conn:
            vals.append(conn.execute("SELECT schema,payload,digest FROM immutable_artifact WHERE id=?",(record_id,)).fetchone())
    if any(v is None for v in vals):
        return "HOLD_INCOMPLETE_PAIR"
    for schema,payload,digest in vals:
        if schema!=SCHEMA or _hash(payload)!=digest:
            return "BLOCK_DIGEST_MISMATCH"
    if vals[1][1]!=expected_anchor.encode("ascii"):
        return "BLOCK_ANCHOR_MISMATCH"
    # DB readback alone cannot guarantee disk power-loss durability or
    # observation truthfulness; it must NEVER assert PAIR_DURABLE_MATCH.
    return "CANDIDATE_READBACK_ONLY_NOT_PRODUCTION_DURABLE"
