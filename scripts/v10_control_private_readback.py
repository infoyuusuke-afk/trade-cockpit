"""Read-only, POSIX-only private evidence readback for V10 CONTROL.

NO automatic writers, daemon, schedule, browser publication, HTTP endpoint,
broker, Excel, live MS2 input or real order paths. The caller must supply a
separately retained, durable EvidenceAnchorPair from the existing subsystem.

Readback verifies independent on-disk evidence bytes against a separately
retained private checksum witness, then reuses the evidenced PAPER projection.
SHA checks prove integrity only relative to that retained witness; they do NOT
authenticate an observer, market source, or broker trades.

Windows physical durability/open semantics are not accepted here. Windows
readback fails closed until a separate reviewed native implementation exists.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from scripts.shadow_forward_private_path import (
    require_private_evidence_path, require_resolved_private_path,
)
from scripts.shadow_forward_persistence_pair import (
    EvidenceAnchorPair, pair_status,
)
from scripts.v10_control_paper_provenance_adapter import project_control_batch

EVIDENCE_SCHEMA = "v10_control_private_paper_batch_v1"
WITNESS_SCHEMA = "v10_control_private_digest_witness_v1"
SOURCE = "SHADOW_FORWARD_PRIVATE"
_SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024
MAX_WITNESS_BYTES = 4096
MAX_ITEMS = 2048


def _platform():
    return os.name


def _blocked(reason):
    # These reason codes are public-safe; never include filesystem paths,
    # private data, identifiers, exception strings or evidence timestamps.
    return [], {
        "status": reason,
        "eligible_records": 0,
        "source_authenticated": False,
        "real_submit_allowed": False,
        "private_evidence_published": False,
        "runtime_activated": False,
    }


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _json(raw):
    def reject_constant(_):
        raise ValueError("nonfinite JSON constant")
    return json.loads(
        raw.decode("utf-8", "strict"),
        object_pairs_hook=_unique_pairs,
        parse_constant=reject_constant,
    )


def _safe_read(root: Path, relative: str, max_bytes: int) -> bytes:
    """No-follow, descriptor-relative read of an already committed artifact.

    Every ancestor is opened relative to the previously validated directory
    descriptor, never by following a string path after the initial policy
    check. Reject pending siblings, special files, links, oversized payloads,
    and files mutated mid-read. This function performs NO writes.
    """
    validated = require_private_evidence_path(relative)
    resolved = require_resolved_private_path(root, validated)
    if not resolved.is_file():
        raise ValueError("not a regular artifact")
    if not all(hasattr(os, field) for field in ("O_NOFOLLOW", "O_DIRECTORY")):
        raise ValueError("safe open flags unavailable")

    parts = tuple(validated.split("/"))
    flags_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    flags_file = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(str(root.resolve(strict=True)), flags_dir)
    opened = []
    try:
        opened.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, flags_dir, dir_fd=descriptor)
            opened.append(descriptor)
        filename = parts[-1]
        try:
            os.stat(filename + ".pending", dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError("unresolved pending artifact")

        file_fd = os.open(filename, flags_file, dir_fd=descriptor)
        opened.append(file_fd)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("not a unique regular file")
        if before.st_size <= 0 or before.st_size > max_bytes:
            raise ValueError("invalid artifact length")
        output = bytearray()
        while len(output) <= max_bytes:
            chunk = os.read(file_fd, min(64 * 1024, max_bytes + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        after = os.fstat(file_fd)
        if (len(output) != before.st_size
                or len(output) > max_bytes
                or (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("artifact changed during readback")
        # Reject path replacement between initial validation and final read.
        checked = require_resolved_private_path(root, validated)
        final_stat = checked.stat(follow_symlinks=False)
        if (final_stat.st_dev, final_stat.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError("artifact replaced")
        return bytes(output)
    finally:
        for fd in reversed(opened):
            os.close(fd)


def readback_paper_for_control(
    repo_root: Path, *, evidence_relative: str, witness_relative: str,
    retained_pair: EvidenceAnchorPair, now,
):
    """Read (evidence, witness) without mutating files; return safe rows only.

    The validated durable pair's anchor is NOT a substitute for source
    authentication, and the witness's SHA is NOT the legacy chain's hash.
    The two are separately compared without changing either hash contract.
    """
    if _platform() != "posix":
        return _blocked("BLOCK_UNSUPPORTED_PLATFORM")
    if not isinstance(retained_pair, EvidenceAnchorPair):
        return _blocked("BLOCK_DURABLE_PAIR_MISSING")
    try:
        if pair_status(retained_pair) != "PAIR_DURABLE_MATCH":
            return _blocked("BLOCK_PAIR_NOT_DURABLE")
        if not _SHA.fullmatch(retained_pair.evidence_anchor):
            return _blocked("BLOCK_ANCHOR_INVALID")
        root = Path(repo_root).resolve(strict=True)
        ep = require_resolved_private_path(root, evidence_relative)
        wp = require_resolved_private_path(root, witness_relative)
        if ep == wp:
            return _blocked("BLOCK_SAME_SOURCE_AND_WITNESS")
        if retained_pair.evidence.path != ep or retained_pair.anchor.path != wp:
            return _blocked("BLOCK_DURABLE_PAIR_PATH_MISMATCH")

        # Independent opens after durable producer completion. No in-memory
        # values from the writer are trusted as evidence bytes.
        witness = _json(_safe_read(root, witness_relative, MAX_WITNESS_BYTES))
        if type(witness) is not dict or set(witness) != {
            "schema_version", "evidence_sha256", "evidence_chain_anchor",
            "records_expected", "real_submit_allowed",
        }:
            return _blocked("BLOCK_WITNESS_SCHEMA")
        if (witness["schema_version"] != WITNESS_SCHEMA
                or witness["real_submit_allowed"] is not False
                or type(witness["records_expected"]) is not int
                or not 0 <= witness["records_expected"] <= MAX_ITEMS
                or type(witness["evidence_sha256"]) is not str
                or _SHA.fullmatch(witness["evidence_sha256"]) is None
                or witness["evidence_chain_anchor"] != retained_pair.evidence_anchor):
            return _blocked("BLOCK_WITNESS_MISMATCH")

        raw = _safe_read(root, evidence_relative, MAX_EVIDENCE_BYTES)
        if hashlib.sha256(raw).hexdigest() != witness["evidence_sha256"]:
            return _blocked("BLOCK_EVIDENCE_DIGEST_MISMATCH")
        evidence = _json(raw)
        if type(evidence) is not dict or set(evidence) != {
            "schema_version", "source", "events", "real_submit_allowed",
        }:
            return _blocked("BLOCK_EVIDENCE_SCHEMA")
        if (evidence["schema_version"] != EVIDENCE_SCHEMA
                or evidence["source"] != SOURCE
                or evidence["real_submit_allowed"] is not False
                or type(evidence["events"]) is not list
                or len(evidence["events"]) != witness["records_expected"]):
            return _blocked("BLOCK_EVIDENCE_CONTRACT")

        accepted, audit = project_control_batch(evidence["events"], now=now)
        return accepted, {
            **audit,
            "status": "READBACK_INTEGRITY_PASS_SOURCE_UNAUTHENTICATED",
            "readback_sha256_verified": True,
            "durability_pair_policy_pass": True,
            "source_authenticated": False,
            "private_evidence_published": False,
            "runtime_activated": False,
        }
    except (ValueError, OSError, UnicodeError, TypeError, AttributeError, OverflowError):
        return _blocked("BLOCK_READBACK_INVALID_OR_UNAVAILABLE")
