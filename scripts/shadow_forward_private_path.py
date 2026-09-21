"""Path policy for private Shadow Forward evidence.

Pure string checks are paired with runtime filesystem containment checks.
No file is created by this module.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

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
    for approved in ALLOWED_ROOTS:
        try:
            p.relative_to(approved)
        except ValueError:
            continue
        return p != approved
    return False


def require_private_evidence_path(path: str) -> str:
    if not allowed_private_path(path):
        raise ValueError("Shadow Forward evidence path outside approved private roots")
    return str(normalize_repo_relative(path))


def _is_junction(path: Path) -> bool:
    check = getattr(os.path, "isjunction", None)
    return bool(callable(check) and check(path))


def _reject_existing_linklike_components(root: Path, target: Path) -> None:
    current = root
    for part in target.relative_to(root).parts:
        current = current / part
        # is_symlink must be checked even for dangling links.
        if current.is_symlink():
            raise ValueError("symlink component prohibited in private evidence path")
        if _is_junction(current):
            raise ValueError("junction component prohibited in private evidence path")
        if not current.exists():
            break


def require_resolved_private_path(repo_root: Path, candidate: str) -> Path:
    """Require lexical + resolved containment without following link aliases."""
    relative = require_private_evidence_path(candidate)
    root = Path(repo_root).resolve(strict=True)
    lexical_target = root.joinpath(*PurePosixPath(relative).parts)

    # Never permit approved roots or existing candidate components to be aliases.
    for approved in ALLOWED_ROOTS:
        _reject_existing_linklike_components(root, root.joinpath(*approved.parts))
    _reject_existing_linklike_components(root, lexical_target)

    probe = lexical_target
    missing: list[str] = []
    while not probe.exists():
        if probe.is_symlink():
            raise ValueError("dangling symlink prohibited in private evidence path")
        missing.append(probe.name)
        parent = probe.parent
        if parent == probe:
            raise ValueError("cannot resolve candidate parent")
        probe = parent

    resolved = probe.resolve(strict=True)
    for part in reversed(missing):
        resolved = resolved / part

    # Compare against lexical approved roots. Because linklike components above
    # were rejected, resolving must not redefine an approved root elsewhere.
    approved_targets = [root.joinpath(*a.parts) for a in ALLOWED_ROOTS]
    if not any(resolved != a and resolved.is_relative_to(a) for a in approved_targets):
        raise ValueError("resolved evidence path escapes approved private roots")
    if not resolved.is_relative_to(root):
        raise ValueError("resolved evidence path escapes repository")
    return resolved
