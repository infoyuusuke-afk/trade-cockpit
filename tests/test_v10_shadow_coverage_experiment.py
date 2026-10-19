"""Issue #449: isolated SHADOW_ONLY coverage experiment; NEVER a live decision gate.

The 95% candidate is diagnostic only. It deliberately cannot yield prices,
signals, entries, aggregate breadth, risk sizing, or order permission.
"""
from __future__ import annotations

import unittest

TOTAL = 100
CANDIDATE_FRESH_MIN = 95
VALID = "FRESH"
REJECT = frozenset({"STALE", "UNKNOWN", "INVALID", "MISSING"})


def diagnostic_only(symbols, expected, *, identity, provenance_ok=True):
    """Count per-symbol evidence; no partial-board decision is ever authorized."""
    expected = tuple(expected)
    rows = tuple(symbols)
    names = [row["ticker"] for row in rows]
    trusted_universe = (
        len(expected) == TOTAL and len(set(expected)) == TOTAL
        and len(names) == len(set(names))
        and set(names) <= set(expected)
        and all(isinstance(s, str) and s for s in expected)
    )
    by_symbol = {row["ticker"]: row for row in rows if isinstance(row.get("ticker"), str)}
    fresh = sum(
        by_symbol[s].get("state") == VALID and by_symbol[s].get("dated_provenance") is True
        for s in expected if s in by_symbol
    )
    complete_fresh = trusted_universe and fresh == TOTAL
    candidate = bool(
        trusted_universe and identity == VALID and provenance_ok
        and fresh >= CANDIDATE_FRESH_MIN
    )
    return {
        "universe_verified": trusted_universe,
        "fresh": fresh,
        "expected": TOTAL,
        "full_board_pass": bool(complete_fresh and identity == VALID and provenance_ok),
        "shadow_95_candidate": candidate,
        "decision_available": False,  # Experiment does not authorize decisions
        "order_allowed": False,
        "real_submit_allowed": False,
        "derived_values": "WITHHELD_NOT_RECOMPUTED",
    }


class CoverageExperiment(unittest.TestCase):
    expected = tuple(f"S{i:03d}.T" for i in range(TOTAL))

    def board(self, missing=0, stale=0):
        n = TOTAL - missing
        return [
            {"ticker": s, "state": "STALE" if i < stale else "FRESH",
             "dated_provenance": True}
            for i, s in enumerate(self.expected[:n])
        ]

    def test_coverage_matrix(self):
        scenarios = (
            (0, 0, 100, True, True),
            (1, 0, 99, False, True),
            (3, 0, 97, False, True),
            (0, 1, 99, False, True),
            (0, 3, 97, False, True),
            (3, 3, 94, False, False),
        )
        for missing, stale, count, full, candidate in scenarios:
            with self.subTest(missing=missing, stale=stale):
                result = diagnostic_only(self.board(missing, stale), self.expected, identity="FRESH")
                self.assertEqual(result["fresh"], count)
                self.assertEqual(result["full_board_pass"], full)
                self.assertEqual(result["shadow_95_candidate"], candidate)
                self.assertFalse(result["decision_available"])
                self.assertFalse(result["real_submit_allowed"])
                self.assertFalse(result["order_allowed"])
                self.assertEqual(result["derived_values"], "WITHHELD_NOT_RECOMPUTED")

    def test_corrupt_identity_and_provenance_never_pass(self):
        for identity, trusted in (("UNKNOWN", True), ("INVALID", True), ("STALE", True), ("FRESH", False)):
            with self.subTest(identity=identity, trusted=trusted):
                out = diagnostic_only(self.board(), self.expected, identity=identity, provenance_ok=trusted)
                self.assertFalse(out["shadow_95_candidate"])
                self.assertFalse(out["full_board_pass"])

    def test_duplicate_or_unexpected_symbol_rejected(self):
        for bad in (
            self.board() + [self.board()[0]],
            self.board() + [{"ticker": "NOT_IN_UNIVERSE", "state": "FRESH", "dated_provenance": True}],
        ):
            out = diagnostic_only(bad, self.expected, identity="FRESH")
            self.assertFalse(out["universe_verified"])
            self.assertFalse(out["shadow_95_candidate"])

    def test_undated_row_never_counted_fresh(self):
        bad = self.board()
        bad[0]["dated_provenance"] = False
        out = diagnostic_only(bad, self.expected, identity="FRESH")
        self.assertEqual(out["fresh"], 99)
        self.assertFalse(out["full_board_pass"])

    def test_age_edge_contract_is_not_reimplemented_as_a_live_verdict(self):
        # State is a verdict from the canonical quote assessor: age alone is
        # insufficient without dated provenance. The 120s boundary must be
        # covered by canonical assessor parity tests before any promotion.
        for age, state in ((119, "FRESH"), (120, "FRESH"), (121, "STALE")):
            with self.subTest(age=age):
                rows = self.board()
                rows[0]["state"] = state
                result = diagnostic_only(rows, self.expected, identity="FRESH")
                self.assertEqual(result["fresh"], 100 if state == "FRESH" else 99)
                self.assertFalse(result["decision_available"])


if __name__ == "__main__":
    unittest.main()
