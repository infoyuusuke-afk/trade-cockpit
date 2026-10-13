import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('pl', Path(__file__).parents[1] / 'scripts/private_ledger.py')
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


def make_entry(**overrides):
    entry = {
        "ticker": "7013", "name": "IHI", "side": "BUY",
        "price": 2772.5, "quantity": 100, "fee": 55,
        "executed_at": "2026-09-15 09:05:00",
        "horizon": "day", "strategy_version": "v1",
        "source": "楽天証券手入力",
    }
    entry.update(overrides)
    return entry


class ValidateEntryTests(unittest.TestCase):
    def test_valid_entry_has_no_problems(self):
        self.assertEqual(pl.validate_entry(make_entry()), [])

    def test_missing_required_field_detected(self):
        entry = make_entry()
        del entry["price"]
        self.assertIn("missing_price", pl.validate_entry(entry))

    def test_invalid_side_detected(self):
        problems = pl.validate_entry(make_entry(side="LONG"))
        self.assertIn("invalid_side:LONG", problems)

    def test_non_numeric_price_detected(self):
        problems = pl.validate_entry(make_entry(price="high"))
        self.assertIn("non_numeric_price", problems)

    def test_empty_string_counts_as_missing(self):
        problems = pl.validate_entry(make_entry(name=""))
        self.assertIn("missing_name", problems)


class RealLedgerSafetyTests(unittest.TestCase):
    def test_rejects_nonfinite_real_values(self):
        for field in ("price", "quantity", "fee"):
            for value in (float("nan"), float("inf"), float("-inf"), "nan"):
                errors=pl.validate_entry(make_entry(**{field:value}))
                self.assertIn(f"non_finite_{field}",errors)

    def test_rejects_negative_or_zero_prices_and_quantities(self):
        for field in ("price", "quantity"):
            for value in (-100.0, 0.0):
                self.assertIn(f"invalid_value_{field}",pl.validate_entry(make_entry(**{field:value})))

    def test_fees_zero_allowed_but_negative_rejected(self):
        self.assertEqual(pl.validate_entry(make_entry(fee=0.0)),[])
        self.assertIn("invalid_value_fee",pl.validate_entry(make_entry(fee=-0.01)))

    def test_invalid_real_execution_date_rejected(self):
        self.assertIn("invalid_executed_at",pl.validate_entry(make_entry(executed_at="not-a-date")))
        self.assertIn("invalid_executed_at",pl.validate_entry(make_entry(executed_at="2026-02-30 09:00:00")))

    def test_boolean_not_a_valid_financial_number(self):
        self.assertIn("non_numeric_price",pl.validate_entry(make_entry(price=True)))

    def test_reconciliation_status_does_not_accept_unverified_pass(self):
        self.assertIn("reconciliation_requires_independent_evidence",pl.validate_entry(make_entry(reconciliation_status="PASS")))
        self.assertIn("reconciliation_requires_independent_evidence",pl.validate_entry(make_entry(reconciliation_status="照合済み")))
        self.assertIn("reconciliation_requires_independent_evidence",pl.validate_entry(make_entry(reconciliation_status="実績未取得")))
        self.assertEqual(pl.validate_entry(make_entry(reconciliation_status="未照合")),[])

    def test_unverified_reconciled_entry_does_not_create_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"ledger.jsonl"
            with self.assertRaises(ValueError):
                pl.append_entry(make_entry(reconciliation_status="照合済み"),path=path)
            self.assertFalse(path.exists())

    def test_rejected_financial_entry_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"ledger.jsonl"
            with self.assertRaises(ValueError):
                pl.append_entry(make_entry(price=float("nan")),path=path)
            self.assertFalse(path.exists())


class NormalizeEntryTests(unittest.TestCase):
    def test_generates_trade_id_when_absent(self):
        record = pl.normalize_entry(make_entry())
        self.assertTrue(record["trade_id"].startswith("T-"))

    def test_preserves_explicit_trade_id(self):
        record = pl.normalize_entry(make_entry(trade_id="T-FIXED"))
        self.assertEqual(record["trade_id"], "T-FIXED")

    def test_default_reconciliation_status_is_unmatched(self):
        record = pl.normalize_entry(make_entry())
        self.assertEqual(record["reconciliation_status"], "未照合")

    def test_default_rule_violation_is_empty_list(self):
        record = pl.normalize_entry(make_entry())
        self.assertEqual(record["rule_violation"], [])


class AppendAndLoadTests(unittest.TestCase):
    def test_roundtrip_append_then_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            pl.append_entry(make_entry(trade_id="T-1"), path=path)
            pl.append_entry(make_entry(trade_id="T-2", executed_at="2026-09-16 09:00:00"), path=path)
            records = pl.load_entries(path=path)
            self.assertEqual(len(records), 2)

    def test_invalid_entry_raises_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            with self.assertRaises(ValueError):
                pl.append_entry(make_entry(side="LONG"), path=path)
            self.assertFalse(path.exists())

    def test_load_missing_file_returns_empty_list_not_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "does_not_exist.jsonl"
            self.assertEqual(pl.load_entries(path=path), [])

    def test_day_filter_only_returns_matching_date(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger.jsonl"
            pl.append_entry(make_entry(trade_id="T-1", executed_at="2026-09-15 09:05:00"), path=path)
            pl.append_entry(make_entry(trade_id="T-2", executed_at="2026-09-16 09:05:00"), path=path)
            records = pl.load_entries(path=path, day="2026-09-15")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["trade_id"], "T-1")


if __name__ == "__main__":
    unittest.main()
