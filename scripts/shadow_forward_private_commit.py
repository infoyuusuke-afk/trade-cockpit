"""Fail-closed local commit primitive for private Shadow Forward artifacts.

Inactive library only: no service, scheduler, broker, RSS, or Real-submit path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import shadow_forward_private_path as path_policy


def commit_new_private_artifact(repo_root: Path, relative_path: str, data: bytes) -> CommitResult:
    """Create one immutable artifact; never overwrite an existing final path."""
    if not isinstance(data, bytes) or not data:
        raise ValueError("non-empty bytes required")
    final_path = path_policy.require_resolved_private_path(repo_root, relative_path)
    parent = final_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Re-resolve after mkdir so a newly materialized directory chain is checked.
    final_path = path_policy.require_resolved_private_path(repo_root, relative_path)
    if final_path.exists():
        raise FileExistsError("immutable artifact already exists")

    temp = final_path.with_name(final_path.name + ".pending")
    if temp.exists():
        raise FileExistsError("pending artifact exists; manual investigation required")

    try:
        # x = exclusive creation. A stale/racing writer fails closed.
        with temp.open("xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())

        # Never use replace(): it would permit silent overwrite.
        if final_path.exists():
            raise FileExistsError("final artifact appeared during commit")
        temp.rename(final_path)

        # Directory fsync is required on POSIX for the durability claim. Windows
        # needs a separately validated native directory-flush implementation;
        # until then the artifact is committed but not "durability verified".
        directory_durable = False
        if os.name == "posix":
            flags = getattr(os, "O_RDONLY", 0)
            dir_fd = os.open(parent, flags)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
            directory_durable = True
        return final_path
    except Exception:
        # Do not guess whether a failed commit is safe. A .pending artifact is
        # intentionally left for investigation if it exists.
        raise


def is_committed_artifact(path: Path) -> bool:
    """Pending files are never eligible evidence."""
    return path.is_file() and not path.name.endswith(".pending")
