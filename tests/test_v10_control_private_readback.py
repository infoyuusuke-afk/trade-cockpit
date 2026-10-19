"""Synthetic tests for the read-only CONTROL evidence/witness gate.

All data is fabricated, temporary and strictly ignored private-folder paths.
No account, MS2 ticks, order submissions, network or Windows runtime.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

from scripts.shadow_forward_private_commit import CommitResult, commit_new_private_artifact
from scripts.shadow_forward_persistence_pair import EvidenceAnchorPair
from scripts import v10_control_private_readback as reader

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 20, 8, 0, tzinfo=JST)
PRIVATE = "data/private/shadow_forward"
EVIDENCE = PRIVATE + "/synthetic-evidence.json"
WITNESS = PRIVATE + "/synthetic-witness.json"
CHAIN_ANCHOR = "a" * 64


def record(key="A"):
    intent_hash = "synthetic-intent-" + key
    return {
        "intent": {
            "intent_hash": intent_hash, "strategy_id": "OR15_LONG",
            "cockpit_tab": "scalp", "symbol": "9999.T", "side": "BUY",
            "quote_currency": "JPY",
            "available_at": "2026-10-19T08:45:00+09:00",
        },
        "entry": {
            "intent_hash": intent_hash, "strategy_id": "OR15_LONG",
            "event_type": "ENTRY_FILL",
            "evidence_source": "INDEPENDENT_OBSERVED_FILL",
            "fill_id": "synthetic-entry-" + key,
            "fill_price": 100.0, "filled_qty": 100, "quote_currency": "JPY",
            "observed_at": "2026-10-19T09:10:00+09:00",
            "available_at": "2026-10-19T09:10:01+09:00",
        },
        "exit": {
            "intent_hash": intent_hash, "strategy_id": "OR15_LONG",
            "event_type": "EXIT_FILL",
            "evidence_source": "INDEPENDENT_OBSERVED_FILL",
            "fill_id": "synthetic-exit-" + key,
            "fill_price": 101.0, "filled_qty": 100, "quote_currency": "JPY",
            "observed_at": "2026-10-19T09:30:00+09:00",
            "available_at": "2026-10-19T09:30:01+09:00",
        },
        "cost": {
            "intent_hash": intent_hash, "cost_model_status": "VERIFIED",
            "cost_pct": 0.1, "cost_basis": "ENTRY_NOTIONAL_PCT",
            "available_at": "2026-10-19T09:30:10+09:00",
        },
    }


def envelope(events):
    return {
        "schema_version": reader.EVIDENCE_SCHEMA,
        "source": reader.SOURCE,
        "real_submit_allowed": False,
        "events": events,
    }


def blob(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class PrivateReadbackTests(unittest.TestCase):
    def setUp(self):
        if os.name != "posix":
            self.skipTest("real immutable commit and nofollow tests require POSIX")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / PRIVATE).mkdir(parents=True)

    def install(self, events=None, *, raw=None, witness_changes=None):
        if events is None:
            events = [record()]
        raw = raw if raw is not None else blob(envelope(events))
        anchor = {
            "schema_version": reader.WITNESS_SCHEMA,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "evidence_chain_anchor": CHAIN_ANCHOR,
            "records_expected": len(events),
            "real_submit_allowed": False,
        }
        anchor.update(witness_changes or {})
        evidence_result = commit_new_private_artifact(self.root, EVIDENCE, raw)
        witness_result = commit_new_private_artifact(self.root, WITNESS, blob(anchor))
        return EvidenceAnchorPair(evidence_result, witness_result,
                                  CHAIN_ANCHOR, CHAIN_ANCHOR)

    def read(self, pair, *, now=NOW, ep=EVIDENCE, wp=WITNESS):
        return reader.readback_paper_for_control(
            self.root, evidence_relative=ep, witness_relative=wp,
            retained_pair=pair, now=now,
        )

    def assert_blocked(self, result, reason):
        rows, audit = result
        self.assertEqual(rows, [])
        self.assertEqual(audit["status"], reason)
        self.assertEqual(audit["eligible_records"], 0)
        self.assertFalse(audit["source_authenticated"])
        self.assertFalse(audit["private_evidence_published"])
        self.assertFalse(audit["runtime_activated"])

    def test_valid_durable_pair_and_independent_disk_readback(self):
        pair = self.install()
        rows, audit = self.read(pair)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pnl_yen"], 90.0)
        self.assertEqual(rows[0]["mode"], "paper")
        self.assertFalse(rows[0]["real_submit_allowed"])
        self.assertFalse(rows[0]["source_authenticated"])
        self.assertEqual(audit["status"],
                         "READBACK_INTEGRITY_PASS_SOURCE_UNAUTHENTICATED")
        self.assertTrue(audit["readback_sha256_verified"])
        self.assertTrue(audit["durability_pair_policy_pass"])
        self.assertEqual(audit["quarantined_records"], 0)
        self.assertNotIn("synthetic-intent-", str((rows, audit)))
        self.assertNotIn("synthetic-entry-", str((rows, audit)))
        self.assertFalse((self.root / (EVIDENCE + ".pending")).exists())

    def test_tampered_evidence_detected_independent_witness(self):
        pair = self.install()
        (self.root / EVIDENCE).write_bytes(blob(envelope([record("TAMPER")])))
        self.assert_blocked(self.read(pair), "BLOCK_EVIDENCE_DIGEST_MISMATCH")

    def test_modified_witness_prevented(self):
        pair = self.install(witness_changes={"evidence_sha256": "b" * 64})
        self.assert_blocked(self.read(pair), "BLOCK_EVIDENCE_DIGEST_MISMATCH")

    def test_unrecognized_anchor_or_digest_is_blocked(self):
        pair = self.install(witness_changes={"evidence_chain_anchor": "b" * 64})
        self.assert_blocked(self.read(pair), "BLOCK_WITNESS_MISMATCH")

    def test_pair_not_durable_or_different_paths_fail_closed(self):
        pair = self.install()
        missing = EvidenceAnchorPair(
            CommitResult(pair.evidence.path, True, False), pair.anchor,
            CHAIN_ANCHOR, CHAIN_ANCHOR,
        )
        self.assert_blocked(self.read(missing), "BLOCK_PAIR_NOT_DURABLE")
        mismatch = EvidenceAnchorPair(
            CommitResult(self.root / PRIVATE / "decoy.bin", True, True),
            pair.anchor, CHAIN_ANCHOR, CHAIN_ANCHOR,
        )
        self.assert_blocked(self.read(mismatch), "BLOCK_DURABLE_PAIR_PATH_MISMATCH")

    def test_unresolved_pending_sibling_blocks_readback(self):
        pair = self.install()
        (self.root / (EVIDENCE + ".pending")).write_bytes(b"uncertain")
        self.assert_blocked(self.read(pair), "BLOCK_READBACK_INVALID_OR_UNAVAILABLE")

    def test_symlink_and_hardlink_payload_blocked(self):
        pair = self.install()
        payload = self.root / EVIDENCE
        extra = self.root / PRIVATE / "extra-hardlink"
        os.link(payload, extra)
        self.assert_blocked(self.read(pair), "BLOCK_READBACK_INVALID_OR_UNAVAILABLE")
        extra.unlink()
        payload.unlink()
        payload.symlink_to(self.root / WITNESS)
        self.assert_blocked(self.read(pair), "BLOCK_READBACK_INVALID_OR_UNAVAILABLE")

    def test_private_path_traversal_and_public_access_rejected(self):
        pair = self.install()
        self.assert_blocked(
            self.read(pair, ep="../../.git/config"),
            "BLOCK_READBACK_INVALID_OR_UNAVAILABLE",
        )
        self.assert_blocked(
            self.read(pair, ep="docs/owner-account.json"),
            "BLOCK_READBACK_INVALID_OR_UNAVAILABLE",
        )

    def test_reject_same_evidence_and_witness(self):
        pair = self.install()
        self.assert_blocked(
            self.read(pair, ep=EVIDENCE, wp=EVIDENCE),
            "BLOCK_SAME_SOURCE_AND_WITNESS",
        )

    def test_evidence_schema_and_duplicate_json_key_fail_closed(self):
        bad = (b'{"schema_version":"' + reader.EVIDENCE_SCHEMA.encode()
               + b'","source":"SHADOW_FORWARD_PRIVATE","real_submit_allowed":false,'
               + b'"events":[],"events":[]}')
        pair = self.install(events=[], raw=bad)
        self.assert_blocked(self.read(pair), "BLOCK_READBACK_INVALID_OR_UNAVAILABLE")

    def test_evidence_contains_unapproved_real_submit_flag(self):
        row = envelope([record()])
        row["real_submit_allowed"] = True
        pair = self.install(raw=blob(row))
        self.assert_blocked(self.read(pair), "BLOCK_EVIDENCE_CONTRACT")

    def test_missing_available_at_never_generates_eligible_trade(self):
        data = record()
        data["cost"].pop("available_at")
        pair = self.install(events=[data])
        rows, audit = self.read(pair)
        self.assertEqual(rows, [])
        self.assertEqual(audit["eligible_records"], 0)
        self.assertEqual(audit["quarantined_records"], 1)
        self.assertTrue(audit["readback_sha256_verified"])
        self.assertEqual(audit["exclusions"], {"AVAILABLE_AT_UNVERIFIED": 1})

    def test_duplicate_intents_quarantined_after_digest_pass(self):
        pair = self.install(events=[record(), record()])
        rows, audit = self.read(pair)
        self.assertEqual(rows, [])
        self.assertEqual(audit["quarantined_records"], 2)
        self.assertEqual(audit["exclusions"], {"DUPLICATE_INTENT": 2})

    def test_future_clock_or_naive_now_fails_closed(self):
        pair = self.install()
        rows, audit = self.read(pair, now=datetime(2026, 10, 19, 9, 0, tzinfo=JST))
        self.assertEqual(rows, [])
        self.assertEqual(audit["quarantined_records"], 1)
        self.assertEqual(audit["exclusions"], {"FUTURE_SOURCE_EVIDENCE": 1})
        self.assert_blocked(
            self.read(pair, now=datetime(2026, 10, 20, 8, 0)),
            "BLOCK_READBACK_INVALID_OR_UNAVAILABLE",
        )

    def test_schema_witness_counts_and_extra_keys_blocked(self):
        pair = self.install(events=[record()], witness_changes={"records_expected": 2})
        self.assert_blocked(self.read(pair), "BLOCK_EVIDENCE_CONTRACT")

    def test_windows_unsupported_without_opening_any_file(self):
        pair = self.install()
        with mock.patch.object(reader, "_platform", return_value="nt"), \
             mock.patch.object(reader, "_safe_read", side_effect=AssertionError("unsafe")):
            self.assert_blocked(self.read(pair), "BLOCK_UNSUPPORTED_PLATFORM")

    def test_cannot_open_files_outside_private_root_with_symlinked_directory(self):
        pair = self.install()
        private = self.root / PRIVATE
        outside = self.root / "other"
        outside.mkdir()
        link = private / "link"
        link.symlink_to(outside, target_is_directory=True)
        self.assert_blocked(
            self.read(pair, ep=PRIVATE + "/link/secret.bin"),
            "BLOCK_READBACK_INVALID_OR_UNAVAILABLE",
        )

    def test_oversized_private_input_fails_closed(self):
        pair = self.install()
        (self.root / EVIDENCE).write_bytes(b"x" * (reader.MAX_EVIDENCE_BYTES + 1))
        self.assert_blocked(self.read(pair), "BLOCK_READBACK_INVALID_OR_UNAVAILABLE")

    def test_empty_valid_history_distinct_from_missing_history(self):
        pair = self.install(events=[])
        rows, audit = self.read(pair)
        self.assertEqual(rows, [])
        self.assertEqual(audit["records_examined"], 0)
        self.assertEqual(audit["eligible_records"], 0)
        self.assertEqual(audit["quarantined_records"], 0)
        self.assertTrue(audit["readback_sha256_verified"])


if __name__ == "__main__":
    unittest.main()
