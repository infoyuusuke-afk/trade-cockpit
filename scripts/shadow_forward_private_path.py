"""Pure path policy for private Shadow Forward evidence.

No filesystem access is performed here. Runtime code must additionally resolve
and verify real paths/reparse points before any write.
"""
from __future__ import annotations

from pathlib import PurePosixPath

ALLOWED_ROOTS = (
    PurePosixPath("data/private/shadow_forward"),
    PurePosixPath("ms2_live/records/shadow_forward"),
)


def normalize_repo_relative(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path required")
    if "\\" in path:
        raise ValueError("backslash path rejected")
    p = PurePosixPath(path)
    if p.is_absolute():
        raise ValueError("absolute path rejected")
    if any(part in ("", ".", "..") for part in p.parts):
        raise ValueError("ambiguous or traversal path rejected")
    return p


def allowed_private_path(path: str) -> bool:
    try:
        p = normalize_repo_relative(path)
    except ValueError:
        return False
    for root in ALLOWED_ROOTS:
        try:
            p.relative_to(root)
        except ValueError:
            continue
        if p == root:
            return False
        return True
    return False


def require_private_evidence_path(path: str) -> str:
    if not allowed_private_path(path):
        raise ValueError("Shadow Forward evidence path outside approved private roots")
    return str(normalize_repo_relative(path))
