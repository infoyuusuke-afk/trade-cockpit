"""Fail-closed persistence pair gate for Shadow Forward evidence + anchor.

Pure policy only. File creation is delegated to shadow_forward_private_commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shadow_forward_private_commit import CommitResult, evidence_commit_status


@dataclass(frozen=True)
class EvidenceAnchorPair:
    evidence: CommitResult
    anchor: CommitResult
    evidence_anchor: str
    retained_anchor: str


def pair_status(pair: EvidenceAnchorPair) -> str:
    if not isinstance(pair, EvidenceAnchorPair):
        raise ValueError("EvidenceAnchorPair required")
    if evidence_commit_status(pair.evidence) != "COMMITTED_DURABLE":
        return "HOLD_EVIDENCE_NOT_DURABLE"
    if evidence_commit_status(pair.anchor) != "COMMITTED_DURABLE":
        return "HOLD_ANCHOR_NOT_DURABLE"
    if not isinstance(pair.evidence_anchor, str) or len(pair.evidence_anchor) != 64:
        return "BLOCK_EVIDENCE_ANCHOR_INVALID"
    if not isinstance(pair.retained_anchor, str) or len(pair.retained_anchor) != 64:
        return "BLOCK_RETAINED_ANCHOR_INVALID"
    if pair.evidence_anchor != pair.retained_anchor:
        return "BLOCK_ANCHOR_MISMATCH"
    if pair.evidence.path == pair.anchor.path:
        return "BLOCK_ANCHOR_NOT_SEPARATE"
    return "PAIR_DURABLE_MATCH"


def require_pair_for_next_validation(pair: EvidenceAnchorPair) -> tuple[Path, Path]:
    if pair_status(pair) != "PAIR_DURABLE_MATCH":
        raise ValueError("evidence/anchor pair not eligible")
    return pair.evidence.path, pair.anchor.path
