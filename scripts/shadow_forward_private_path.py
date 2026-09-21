"""Pure path policy for private Shadow Forward evidence.

No filesystem access is performed here. Runtime code must additionally resolve
and verify real paths/reparse points before any write.
"""
from __future__ import annotations

import os\nfrom pathlib import Path, PurePosixPath

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


def require_resolved_private_path(repo_root: Path, candidate: str) -> Path:
    """Resolve existing parents and require final target containment.

    This is the runtime companion to the pure string policy. It does not create
    files. Callers must run it immediately before each write and must still use
    exclusive/atomic creation semantics to reduce TOCTOU exposure.
    """
    relative = require_private_evidence_path(candidate)
    root = Path(repo_root).resolve(strict=True)
    target = root.joinpath(*PurePosixPath(relative).parts)

    # Resolve the deepest existing parent so symlink/junction/reparse escapes in
    # the directory chain are visible before a new leaf is created.
    probe = target
    missing = []
    while not probe.exists():
        missing.append(probe.name)
        parent = probe.parent
        if parent == probe:
            raise ValueError("cannot resolve candidate parent")
        probe = parent
    resolved = probe.resolve(strict=True)
    for part in reversed(missing):
        resolved = resolved / part

    allowed = [
        root.joinpath(*r.parts).resolve(strict=False)
        for r in ALLOWED_ROOTS
    ]
    if not any(resolved != ar and resolved.is_relative_to(ar) for ar in allowed):
        raise ValueError("resolved evidence path escapes approved private roots")
    if not resolved.is_relative_to(root):
        raise ValueError("resolved evidence path escapes repository")
    return resolved
