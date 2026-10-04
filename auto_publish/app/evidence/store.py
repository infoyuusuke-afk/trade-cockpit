"""Evidence lock: content-addressed immutable copies + SHA256 verification.

At ingest every input file is copied to ``evidence_store/<sha[:2]>/<sha>`` and
made read-only. All later stages read facts from that copy, and every stage
that relies on evidence re-hashes it first. Any mismatch is fail-closed.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

from ..errors import EvidenceError
from ..hashing import sha256_file, sha256_json


def store_copy(src: Path, store_root: Path, expected_sha: str) -> Path:
    dest = store_root / expected_sha[:2] / expected_sha
    if dest.exists():
        if sha256_file(dest) != expected_sha:
            raise EvidenceError(f"evidence store corrupted for {expected_sha}", code="EVIDENCE_STORE_CORRUPT")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp-{os.getpid()}")
    shutil.copyfile(src, tmp)
    if sha256_file(tmp) != expected_sha:
        tmp.unlink(missing_ok=True)
        raise EvidenceError(f"{src} changed while being ingested", code="EVIDENCE_CHANGED_DURING_INGEST")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    os.replace(tmp, dest)
    return dest


def verify_row(row) -> None:
    """Re-hash the stored copy of an evidence row; raise if it does not match the lock."""
    p = Path(row["store_path"])
    if not p.exists():
        raise EvidenceError(f"evidence missing: {row['rel_path']}", code="EVIDENCE_MISSING",
                            details={"rel_path": row["rel_path"]})
    actual = sha256_file(p)
    if actual != row["sha256"]:
        raise EvidenceError(
            f"evidence hash mismatch for {row['rel_path']}", code="EVIDENCE_TAMPERED",
            details={"rel_path": row["rel_path"], "expected": row["sha256"], "actual": actual},
        )


def verify_session(conn, session_date: str) -> int:
    rows = conn.execute("SELECT * FROM evidence WHERE session_date = ? ORDER BY rel_path", (session_date,)).fetchall()
    if not rows:
        raise EvidenceError(f"no evidence recorded for session {session_date}", code="EVIDENCE_MISSING")
    for r in rows:
        verify_row(r)
    return len(rows)


def manifest(conn, session_date: str) -> tuple[dict, str]:
    rows = conn.execute(
        "SELECT rel_path, sha256, size_bytes, kind FROM evidence WHERE session_date = ? ORDER BY rel_path",
        (session_date,),
    ).fetchall()
    m = {
        "session_date": session_date,
        "files": [dict(r) for r in rows],
    }
    return m, sha256_json(m)


def load_json(row) -> Any:
    verify_row(row)
    try:
        return json.loads(Path(row["store_path"]).read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{row['rel_path']} is not valid UTF-8 JSON: {exc}", code="EVIDENCE_UNPARSEABLE") from exc


def resolve_pointer(doc: Any, pointer: str) -> Any:
    """RFC 6901 JSON pointer resolution; raises EvidenceError if absent."""
    if pointer == "":
        return doc
    if not pointer.startswith("/"):
        raise EvidenceError(f"bad pointer {pointer!r}", code="BAD_POINTER")
    cur = doc
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(cur, list):
                cur = cur[int(token)]
            elif isinstance(cur, dict):
                cur = cur[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError, ValueError) as exc:
            raise EvidenceError(f"pointer {pointer} not found", code="POINTER_NOT_FOUND") from exc
    return cur
