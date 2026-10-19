"""Strict synthetic-only contract for the V10 CONTROL pure adapter.

No private MS2/broker/fill/account contents, I/O, service or real order calls.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import unittest

from scripts.v10_control_paper_provenance_adapter import (
    SCHEMA, project_control_batch, project_control_row,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=JST)


def fixture(tag="A"):
    intent = {
        "intent_hash": "synthetic-intent-" + tag,
        "strategy_id": "OR15_LONG",
        "symbol": "9999.T",
        "side": "BUY",
        "cockpit_tab": "scalp",
        "quote_currency": "JPY",
        "available_at": "2026-10-19T08:45:00+09:00",
    }
    entry = {
        "intent_hash": intent["intent_hash"],
        "strategy_id": "OR15_LONG",
        "event_type": "ENTRY_FILL",
        "evidence_source": "INDEPENDENT_OBSERVED_FILL",
        "fill_id": "synthetic-entry-" + tag,
        "fill_price": 100.0,
        "filled_qty": 100,
        "quote_currency": "JPY",
        "observed_at": "2026-10-19T09:10:00+09:00",
        "available_at": "2026-10-19T09:10:01+09:00",
    }
    exit_ = {
        "intent_hash": intent["intent_hash"],
        "strategy_id": "OR15_LONG",
        "event_type": "EXIT_FILL",
        "evidence_source": "INDEPENDENT_OBSERVED_FILL",
        "fill_id": "synthetic-exit-" + tag,
        "fill_price": 101.0,
        "filled_qty": 100,
        "quote_currency": "JPY",
        "observed_at": "2026-10-19T09:30:00+09:00",
        "available_at": "2026-10-19T09:30:01+09:00",
    }
    cost = {
        "intent_hash": intent["intent_hash"],
        "cost_model_status": "VERIFIED",
        "cost_pct": 0.1,
        "cost_basis": "ENTRY_NOTIONAL_PCT",
        "available_at": "2026-10-19T09:30:10+09:00",
    }
    return {"intent": intent, "entry": entry, "exit": exit_, "cost": cost}


def project(item, now=NOW):
    return project_control_row(
        item["intent"], item["entry"], item["exit"], item["cost"], now=now
    )


class V10ControlPaperEvidenceAdapter(unittest.TestCase):
    def assert_blocked(self, item, expected, now=NOW):
        row, reason = project(item, now=now)
        self.assertIsNone(row)
        self.assertEqual(reason, expected)

    def test_independent_observed_roundtrip_exports_safe_paper(self):
        row, reason = project(fixture())
        self.assertIsNone(reason)
        self.assertEqual(row["schema_version"], SCHEMA)
        self.assertEqual(row["mode"], "paper")
        self.assertEqual(row["cockpit_tab"], "scalp")
        self.assertEqual(row["status"], "CLOSED")
        self.assertEqual(row["pnl_yen"], 90.0)
        self.assertEqual(row["closed_at"], "2026-10-19T09:30:00+09:00")
        self.assertEqual(row["available_at"], "2026-10-19T09:30:10+09:00")
        self.assertTrue(row["trade_id"].startswith("paper-"))
        self.assertFalse(row["source_authenticated"])
        self.assertFalse(row["real_submit_allowed"])
        for forbidden in ("entry_fill_price", "exit_fill_price", "fill_id",
                          "intent_hash", "account", "broker", "position"):
            self.assertNotIn(forbidden, str(row))
        self.assertFalse("symbol" in row)
        self.assertFalse("ticker" in row)

    def test_deterministic_hash_and_no_clock_injection(self):
        first, _ = project(fixture())
        second, _ = project(fixture())
        self.assertEqual(first, second)
        self.assertEqual(len(first["trade_id"]), 70)
        self.assert_blocked(fixture(), "NOW_TIMEZONE_REQUIRED",
                            now=datetime(2026, 10, 19, 12, 0))

    def test_exact_short_net_pnl_after_verified_cost(self):
        event = fixture()
        event["intent"]["side"] = "SELL"
        event["exit"]["fill_price"] = 98.0
        row, reason = project(event)
        self.assertIsNone(reason)
        self.assertEqual(row["pnl_yen"], 190.0)
        self.assertEqual(row["mode"], "paper")

    def test_missing_or_unapproved_tab_never_guessed_from_strategy(self):
        for tab in (None, "", "REAL", "control", "scalping", "next-theme"):
            event = fixture()
            event["intent"]["cockpit_tab"] = tab
            self.assert_blocked(event, "STRATEGY_TAB_UNVERIFIED")

    def test_quote_currency_and_cost_basis_must_be_explicit(self):
        for who in ("intent", "entry", "exit"):
            event = fixture()
            event[who].pop("quote_currency")
            self.assert_blocked(event, "JPY_QUOTE_PROVENANCE_MISSING")
            event = fixture()
            event[who]["quote_currency"] = "USD"
            self.assert_blocked(event, "JPY_QUOTE_PROVENANCE_MISSING")
        for cost_basis in (None, "", "SELL_NOTIONAL_PCT", "UNKNOWN"):
            event = fixture()
            event["cost"]["cost_basis"] = cost_basis
            self.assert_blocked(event, "COST_BASIS_UNVERIFIED")

    def test_estimated_fill_and_uncertain_source_rejected(self):
        for confidence in ("PROBABLE", "UNCERTAIN", "UNOBSERVABLE"):
            event = fixture()
            event["entry"]["fill_confidence"] = confidence
            self.assert_blocked(event, "EVIDENCE_ESTIMATED_FILL_REJECTED")
        event = fixture()
        event["exit"]["evidence_source"] = "MODEL"
        self.assert_blocked(event, "EVIDENCE_INDEPENDENT_FILL_EVIDENCE_MISSING")

    def test_fill_lineage_qty_and_cost_must_verify(self):
        event = fixture()
        event["exit"]["strategy_id"] = "OTHER"
        self.assert_blocked(event, "EVIDENCE_LINEAGE_MISMATCH")
        event = fixture()
        event["exit"]["filled_qty"] = 50
        self.assert_blocked(event, "EVIDENCE_UNMATCHED_FILLED_QTY")
        event = fixture()
        event["entry"]["fill_id"] = event["exit"]["fill_id"]
        self.assert_blocked(event, "EVIDENCE_FILL_ID_COLLISION")
        event = fixture()
        event["cost"]["cost_model_status"] = "UNKNOWN"
        self.assert_blocked(event, "EVIDENCE_COST_EVIDENCE_NOT_VERIFIED")
        event = fixture()
        event["cost"]["cost_pct"] = -1
        self.assert_blocked(event, "EVIDENCE_COST_VALUE_MISSING")

    def test_no_auto_backfill_of_available_at(self):
        for place in ("intent", "entry", "exit", "cost"):
            event = fixture()
            event[place].pop("available_at")
            self.assert_blocked(event, "AVAILABLE_AT_UNVERIFIED")
        event = fixture()
        event["exit"]["available_at"] = "2026-10-19T09:30:10"
        self.assert_blocked(event, "AVAILABLE_AT_UNVERIFIED")

    def test_reject_point_in_time_leakage(self):
        changes = (
            ("intent", "2026-10-19T09:12:00+09:00"),
            ("entry", "2026-10-19T09:31:00+09:00"),
            ("exit", "2026-10-19T09:29:59+09:00"),
            ("cost", "2026-10-19T09:29:59+09:00"),
        )
        for key, at in changes:
            event = fixture()
            event[key]["available_at"] = at
            self.assert_blocked(event, "POINT_IN_TIME_LEAKAGE_OR_ORDER")

    def test_futuristic_publication_never_accepted(self):
        event = fixture()
        event["cost"]["available_at"] = "2026-10-19T12:00:01+09:00"
        self.assert_blocked(event, "FUTURE_SOURCE_EVIDENCE")
        event = fixture()
        event["cost"]["available_at"] = "2026-10-20T00:00:00+09:00"
        self.assert_blocked(event, "FUTURE_SOURCE_EVIDENCE")

    def test_real_submit_flag_and_private_fields_rejected(self):
        for place in ("intent", "entry", "exit", "cost"):
            event = fixture()
            event[place]["real_submit_allowed"] = True
            self.assert_blocked(event, "REAL_SUBMIT_EVIDENCE_REJECTED")
        event = fixture()
        event["intent"]["broker_account"] = "synthetic-only-do-not-publish"
        self.assert_blocked(event, "EVIDENCE_PRIVATE_FIELD_REJECTED")

    def test_identity_and_timestamp_bounds(self):
        event = fixture()
        event["intent"]["intent_hash"] = "invalid id with whitespace"
        self.assert_blocked(event, "SYMBOL_OR_INTENT_IDENTITY_UNSAFE")
        event = fixture()
        event["intent"]["symbol"] = "USDJPY"
        self.assert_blocked(event, "SYMBOL_OR_INTENT_IDENTITY_UNSAFE")
        event = fixture()
        event["entry"]["fill_id"] = "id with slash/"
        self.assert_blocked(event, "FILL_IDENTIFIERS_UNSAFE")

    def test_duplicate_intents_quarantines_all(self):
        a = fixture()
        b = copy.deepcopy(a)
        rows, audit = project_control_batch([a, b], now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(audit["records_examined"], 2)
        self.assertEqual(audit["eligible_records"], 0)
        self.assertEqual(audit["quarantined_records"], 2)
        self.assertEqual(audit["exclusions"], {"DUPLICATE_INTENT": 2})

    def test_duplicate_valid_plus_malformed_member_both_rejected(self):
        a = fixture()
        b = copy.deepcopy(a)
        b["exit"]["evidence_source"] = "MODEL"
        rows, audit = project_control_batch([a, b], now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(audit["exclusions"], {"DUPLICATE_INTENT": 2})

    def test_batch_returns_only_anonymous_counts_and_safe_rows(self):
        a = fixture("A")
        b = fixture("B")
        b["entry"]["fill_price"] = None
        rows, audit = project_control_batch([a, b, {}, None], now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(audit["records_examined"], 4)
        self.assertEqual(audit["eligible_records"], 1)
        self.assertEqual(audit["quarantined_records"], 3)
        self.assertFalse(audit["persistence_verified"])
        self.assertFalse(audit["source_authenticated"])
        self.assertFalse(audit["real_submit_allowed"])
        self.assertFalse(audit["private_evidence_published"])
        self.assertEqual(audit["exclusions"].get("INVALID_BATCH_ITEM"), 1)
        self.assertNotIn("fill_price", str(audit))
        self.assertNotIn("synthetic-intent-", str(audit))

    def test_missing_input_and_unsafe_now_raise(self):
        for bad in (None, {}, ()):
            with self.assertRaises(ValueError):
                project_control_batch(bad, now=NOW)
        with self.assertRaises(ValueError):
            project_control_batch([], now=datetime(2026, 10, 19, 11, 0))
        self.assertEqual(project_control_batch([], now=NOW)[0], [])

    def test_valid_source_row_is_structurally_compatible_with_control_ui(self):
        row, reason = project(fixture())
        self.assertIsNone(reason)
        self.assertIn(row["cockpit_tab"], (
            "scalp", "event-hot", "ms2-live", "overnight",
            "swing", "value", "kioxia-calendar",
        ))
        self.assertIn(row["mode"], ("paper", "shadow", "backtest"))
        self.assertTrue(row["trade_id"].replace("-", "").isalnum())
        available = datetime.fromisoformat(row["available_at"])
        closed = datetime.fromisoformat(row["closed_at"])
        self.assertTrue(closed <= available <= NOW)
        self.assertTrue(isinstance(row["pnl_yen"], float))


if __name__ == "__main__":
    unittest.main()
