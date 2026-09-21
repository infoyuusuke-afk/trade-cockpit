"""Fail-closed local commit primitive for private Shadow Forward artifacts.

Inactive library only: no service, scheduler, broker, RSS, or Real-submit path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import shadow_forward_private_path as path_policy


@dataclass(frozen=True)
class CommitResult:
    path: Path
    file_fsync: bool
    directory_fsync: bool

    @property
    def durability_verified(self) -> bool:
        return self.file_fsync and self.directory_fsync


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

        # Do not publish a final name on platforms where directory durability
        # has not been independently validated. The durable Windows mechanism
        # requires a separate implementation + actual-machine approval.
        if os.name != "posix":
            raise OSError("directory durability unsupported; publication prohibited")

        # Publish without overwrite: hard-link creation fails if final exists.
        # Keep .pending until the directory entry for final is durably flushed.
        if final_path.exists():
            raise FileExistsError("final artifact appeared during commit")
        os.link(temp, final_path)

        flags = getattr(os, "O_RDONLY", 0)
        dir_fd = os.open(parent, flags)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

        temp.unlink()

        # Durably record removal of the pending marker before returning success.
        dir_fd = os.open(parent, flags)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

        return CommitResult(final_path, file_fsync=True, directory_fsync=True)
    except Exception:
        # Do not guess whether a failed commit is safe. A .pending artifact is
        # intentionally left for investigation if it exists.
        raise


def evidence_commit_status(result: CommitResult) -> str:
    """Return the only persistence-level eligibility status.

    COMMITTED_DURABLE is necessary but not sufficient for Phase 6 acceptance;
    all C-105/C-106/acceptance checks still apply.
    """
    if not isinstance(result, CommitResult):
        raise ValueError("CommitResult required")
    if not result.file_fsync:
        return "HOLD_FILE_DURABILITY_UNVERIFIED"
    if not result.directory_fsync:
        return "HOLD_DURABILITY_UNVERIFIED"
    return "COMMITTED_DURABLE"


def require_durable_for_acceptance(result: CommitResult) -> Path:
    if evidence_commit_status(result) != "COMMITTED_DURABLE":
        raise ValueError("artifact durability unverified; acceptance prohibited")
    return result.path
