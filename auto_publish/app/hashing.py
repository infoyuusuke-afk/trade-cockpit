"""SHA256 + canonical JSON helpers. Canonical JSON is the only form ever hashed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

CHUNK = 1024 * 1024


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    """Write-then-rename so a crash never leaves a half-written artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def json_file_bytes(obj: Any) -> bytes:
    """Exact bytes ``write_json_atomic`` writes (pretty, key-sorted, trailing newline)."""
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_json_atomic(path: Path, obj: Any) -> str:
    """Write pretty, key-sorted JSON atomically; return sha256 of the bytes written."""
    data = json_file_bytes(obj)
    write_atomic(path, data)
    return sha256_bytes(data)
