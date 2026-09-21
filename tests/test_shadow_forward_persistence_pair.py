import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from shadow_forward_private_commit import CommitResult
from shadow_forward_persistence_pair import (
    EvidenceAnchorPair, pair_status, require_pair_for_next_validation,
)

A = "a" * 64
B = "b" * 64


def cr(name, file=True, directory=True):
    return CommitResult(Path(name), file, directory)


class PersistencePairTests(unittest.TestCase):
    def test_matching_separate_durable_pair_passes(self):
        pair = EvidenceAnchorPair(cr("evidence.bin"), cr("anchor.bin"), A, A)
        self.assertEqual(pair_status(pair), "PAIR_DURABLE_MATCH")
        self.assertEqual(require_pair_for_next_validation(pair),
                         (Path("evidence.bin"), Path("anchor.bin")))

    def test_evidence_not_durable_holds(self):
        pair = EvidenceAnchorPair(cr("e.bin", True, False), cr("a.bin"), A, A)
        self.assertEqual(pair_status(pair), "HOLD_EVIDENCE_NOT_DURABLE")

    def test_anchor_not_durable_holds(self):
        pair = EvidenceAnchorPair(cr("e.bin"), cr("a.bin", True, False), A, A)
        self.assertEqual(pair_status(pair), "HOLD_ANCHOR_NOT_DURABLE")

    def test_anchor_mismatch_blocks(self):
        pair = EvidenceAnchorPair(cr("e.bin"), cr("a.bin"), A, B)
        self.assertEqual(pair_status(pair), "BLOCK_ANCHOR_MISMATCH")
        with self.assertRaises(ValueError):
            require_pair_for_next_validation(pair)

    def test_same_artifact_cannot_be_evidence_and_anchor(self):
        pair = EvidenceAnchorPair(cr("same.bin"), cr("same.bin"), A, A)
        self.assertEqual(pair_status(pair), "BLOCK_ANCHOR_NOT_SEPARATE")

    def test_invalid_anchor_shape_blocks(self):
        pair = EvidenceAnchorPair(cr("e.bin"), cr("a.bin"), "x", A)
        self.assertEqual(pair_status(pair), "BLOCK_EVIDENCE_ANCHOR_INVALID")


if __name__ == "__main__":
    unittest.main()
