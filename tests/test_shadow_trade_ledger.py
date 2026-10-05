import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 6, 10, 0, tzinfo=JST)


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger = _load("shadow_trade_ledger_test", "scripts/shadow_trade_ledger.py")
brain = _load("ai_brain_research_ledger", "scripts/ai_brain_research.py")
supervisor = _load("ai_shadow_supervisor_ledger", "scripts/ai_shadow_supervisor.py")
acceptance = _load("shadow_synthetic_acceptance_ledger", "scripts/shadow_synthetic_acceptance.py")


def _record(**overrides):
    base = {
        "record_class": "shadow_trade",
        "trade_id": "285A.T|LONG|1",
        "symbol": "285A.T",
        "side": "LONG",
        "strategy": "OR15",
        "model_id": "BASELINE",
        "decision_at": (NOW - timedelta(minutes=30)).isoformat(),
        "available_at": "09:16:00",
        "entry_signal_at": "09:16:00",
        "entry_order_at": None,
        "entry_fill_at": (NOW - timedelta(minutes=30)).isoformat(),
        "entry_price": 19130.0,
        "entry_slippage": 10.0,
        "exit_signal_at": "09:46:00",
        "exit_fill_at": (NOW - timedelta(minutes=5)).isoformat(),
        "exit_price": 19170.0,
        "exit_slippage": 10.0,
        "quantity": None,
        "gross_pnl": 40.0,
        "commission": ledger.FEE_UNKNOWN,
        "other_cost": ledger.FEE_UNKNOWN,
        "net_pnl": ledger.FEE_UNKNOWN,
        "mae": 80.0,
        "mfe": 170.0,
        "regime": "UNKNOWN",
        "data_quality": "OK",
        "source_stage": ledger.SOURCE_LIVE,
        "entry_seq": 1,
        "fee_basis": "UNCONFIRMED",
        "real_submit_allowed": False,
    }
    base.update(overrides)
    return base


class ShadowTradeLedgerTests(unittest.TestCase):
    def test_fee_audit_has_no_confirmed_schedule(self):
        self.assertFalse(ledger.FEE_AUDIT["confirmed_commission_schedule"])
        self.assertEqual(ledger.FEE_AUDIT["recorded_commission"], "FEE_UNKNOWN")
        self.assertEqual(ledger.CONFIRMED_LIVE_FEE_BASES, frozenset())
        self.assertIn("RssOrder", ledger.FEE_AUDIT["order_method"])
        self.assertTrue(any("0" in item for item in ledger.FEE_AUDIT["rejected_placeholders"]))
        self.assertTrue(any("10" in item for item in ledger.FEE_AUDIT["rejected_placeholders"]))

    def test_synthetic_replay_records_every_field_and_stays_out_of_live_n(self):
        with tempfile.TemporaryDirectory() as temp:
            result = acceptance.run_synthetic_acceptance(Path(temp))
            trades, error = ledger.read_shadow_trades(Path(temp) / "shadow_trades.jsonl")
            status = json.loads((Path(temp) / "shadow_research_status.json").read_text(encoding="utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["live_roundtrip"], "NOT_RUN/SYNTHETIC_LEDGER")
        self.assertFalse(error)
        self.assertEqual(len(trades), 2)
        for trade in trades:
            self.assertTrue(set(ledger.LEDGER_FIELDS).issubset(trade))
            self.assertEqual(trade["source_stage"], "SYNTHETIC/REPLAY")
            self.assertEqual(trade["commission"], "FEE_UNKNOWN")
            self.assertEqual(trade["other_cost"], "FEE_UNKNOWN")
            self.assertEqual(trade["net_pnl"], "FEE_UNKNOWN")
            self.assertIsNone(trade["quantity"])
            self.assertIsNone(trade["entry_order_at"])
            self.assertFalse(trade["real_submit_allowed"])
        self.assertEqual(trades[0]["entry_price"], 19130.0)
        self.assertEqual(trades[0]["exit_price"], 19170.0)
        self.assertEqual(trades[0]["gross_pnl"], 40.0)
        self.assertEqual(trades[0]["mae"], 80.0)
        self.assertEqual(trades[0]["mfe"], 170.0)
        self.assertEqual(status["CLEAN_SHADOW_TRADE_N"], 0)
        self.assertEqual(status["BASELINE_N"], 0)
        self.assertEqual(status["FEATURE_DELTA_EV"], "NOT_AVAILABLE")
        self.assertEqual(status["PROMOTION_CANDIDATE"], "NONE")
        self.assertNotIn("net_ev", json.dumps(status))
        text = acceptance.format_report(result)
        self.assertIn("FEE=FEE_UNKNOWN", text)
        self.assertIn("LIVE_SAMPLE_N=0", text)
        self.assertNotIn("LIVE_ROUNDTRIP=PASS", text)

    def test_fixture_fee_reaches_the_research_pipe_without_a_live_sample(self):
        with tempfile.TemporaryDirectory() as temp:
            acceptance.run_synthetic_acceptance(Path(temp))
            stored, _error = ledger.read_shadow_trades(Path(temp) / "shadow_trades.jsonl")
        priced = [ledger.apply_synthetic_fixture_fee(trade, 1.0, 0.25) for trade in stored]
        status = brain.evaluate_shadow_trade_ledger(priced)
        self.assertEqual(status["CLEAN_SHADOW_TRADE_N"], 0)
        self.assertEqual(status["BASELINE_N"], 0)
        self.assertEqual(status["FEATURE_DELTA_EV"], "NOT_AVAILABLE")
        self.assertEqual(status["PROMOTION_CANDIDATE"], "NONE")
        self.assertEqual(status["pipe_n"], 2)
        self.assertFalse(status["pipe_counts_as_live_sample"])
        self.assertFalse(status["pipe_promotion_candidate"])
        self.assertEqual(status["pipe_trades"][0]["net_pnl"], 38.75)
        self.assertEqual(status["pipe_trades"][0]["mae"], 80.0)
        self.assertEqual(status["pipe_trades"][0]["mfe"], 170.0)
        self.assertEqual(status["pipe_trades"][1]["gross_pnl"], -10.0)
        self.assertEqual(status["pipe_trades"][1]["net_pnl"], -11.25)
        self.assertTrue(all(row["source_stage"] == "SYNTHETIC/REPLAY" and row["counts_as_live_sample"] is False for row in status["pipe_trades"]))
        self.assertTrue(all(trade["commission"] == "FEE_UNKNOWN" for trade in stored))
        with self.assertRaises(ValueError):
            ledger.apply_synthetic_fixture_fee(_record(), 1.0)

    def test_bad_rows_are_excluded_and_a_number_without_a_basis_is_still_unknown(self):
        synthetic = _record(source_stage="SYNTHETIC/REPLAY", trade_id="285A.T|SHORT|2", symbol="285A.T", side="SHORT", entry_seq=2)
        priced = ledger.apply_synthetic_fixture_fee(synthetic, 1.0, 0.0)
        assumed_zero = _record(commission=0, other_cost=0, net_pnl=40.0, fee_basis="ASSUMED_ZERO")
        rows = [
            priced,
            dict(priced),
            _record(data_quality="STALE"),
            _record(exit_fill_at=(NOW - timedelta(hours=2)).isoformat()),
            _record(symbol="", trade_id="|LONG|1"),
            _record(),
            _record(mae=None),
            assumed_zero,
        ]
        status = brain.evaluate_shadow_trade_ledger(rows)
        reasons = [item["reason"] for item in status["excluded"]]
        self.assertEqual(status["CLEAN_SHADOW_TRADE_N"], 0)
        self.assertEqual(status["BASELINE_N"], 0)
        self.assertEqual(status["pipe_n"], 1)
        self.assertEqual(status["PROMOTION_CANDIDATE"], "NONE")
        self.assertIn("DUPLICATE", reasons)
        self.assertIn("STALE_PRICE", reasons)
        self.assertIn("TIMESTAMP_INCONSISTENT", reasons)
        self.assertIn("IDENTITY_UNKNOWN", reasons)
        self.assertIn("FEE_UNKNOWN", reasons)
        self.assertIn("INCOMPLETE", reasons)
        self.assertTrue(all(item["counts_as_live_sample"] is False for item in status["excluded"]))

    def test_a_confirmed_basis_can_enter_baseline_and_synthetic_still_cannot(self):
        live = _record(commission=1.0, other_cost=0.5, net_pnl=38.5, fee_basis="TEST_ONLY_NOT_A_TARIFF")
        synthetic = ledger.apply_synthetic_fixture_fee(
            _record(source_stage="SYNTHETIC/REPLAY", trade_id="285A.T|LONG|2", entry_seq=2),
            1.0,
            0.5,
        )
        target = brain.trade_ledger
        original = target.CONFIRMED_LIVE_FEE_BASES
        try:
            blocked = brain.evaluate_shadow_trade_ledger([live, synthetic])
            target.CONFIRMED_LIVE_FEE_BASES = frozenset({"TEST_ONLY_NOT_A_TARIFF"})
            status = brain.evaluate_shadow_trade_ledger([live, synthetic])
        finally:
            target.CONFIRMED_LIVE_FEE_BASES = original
        self.assertEqual(blocked["CLEAN_SHADOW_TRADE_N"], 0)
        self.assertEqual(blocked["pipe_n"], 1)
        self.assertEqual(status["CLEAN_SHADOW_TRADE_N"], 1)
        self.assertEqual(status["BASELINE_N"], 1)
        self.assertEqual(status["pipe_n"], 1)
        self.assertEqual(status["PROMOTION_CANDIDATE"], "NONE")
        self.assertEqual(status["FEATURE_DELTA_EV"], "NOT_AVAILABLE")
        self.assertEqual(status["baseline_by_side"]["LONG"]["n"], 1)
        self.assertEqual(status["baseline_by_side"]["LONG"]["net_ev"], 38.5)

    def test_live_exit_is_recorded_without_loosening_the_entry_rule(self):
        self.assertEqual(supervisor.LONG_ENTRY_SIGNALS, frozenset({"初動買い候補", "買いサイン", "持ち越しロング確定"}))
        self.assertEqual(supervisor.SHORT_ENTRY_SIGNALS, frozenset({"初動ショート候補", "空売りサイン", "持ち越しショート確定"}))
        source = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertNotIn("commission = 0", source)
        self.assertNotIn("fee_bps", source)
        self.assertNotIn("import shadow_execution", source)
        self.assertNotIn("submit_shadow_order", source)
        now = acceptance.NOW
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            engine = supervisor.load_engine(data, now=now)
            waiting = acceptance._live([acceptance._row(signal="市場時間外")])
            supervisor.apply_cycle(
                engine,
                waiting,
                supervisor.assess_live_payload(waiting, file_mtime=now, now=now),
                now=now,
                data_dir=data,
            )
            self.assertEqual(engine["open_positions"], {})
            self.assertFalse((data / "shadow_trades.jsonl").exists())
            entry = acceptance._live([acceptance._row()])
            supervisor.apply_cycle(
                engine,
                entry,
                supervisor.assess_live_payload(entry, file_mtime=now, now=now),
                now=now,
                data_dir=data,
            )
            self.assertEqual(len(engine["open_positions"]), 1)
            self.assertFalse((data / "shadow_trades.jsonl").exists())
            flat_at = now + timedelta(minutes=20)
            flat = acceptance._live(
                [acceptance._row(signal="監視", price=19180.0, bid=19170.0, ask=19190.0)],
                updated_at="2026-10-02 09:36:05",
            )
            supervisor.apply_cycle(
                engine,
                flat,
                supervisor.assess_live_payload(flat, file_mtime=flat_at, now=flat_at),
                now=flat_at,
                data_dir=data,
            )
            trades, error = ledger.read_shadow_trades(data / "shadow_trades.jsonl")
            status = json.loads((data / "shadow_research_status.json").read_text(encoding="utf-8"))
            again = ledger.append_shadow_trade(data, trades[0])
            reread, reread_error = ledger.read_shadow_trades(data / "shadow_trades.jsonl")
        self.assertFalse(error)
        self.assertFalse(reread_error)
        self.assertEqual(len(trades), 1)
        self.assertFalse(again)
        self.assertEqual(len(reread), 1)
        self.assertEqual(trades[0]["source_stage"], "LIVE_SHADOW")
        self.assertEqual(trades[0]["model_id"], "BASELINE")
        self.assertEqual(trades[0]["commission"], "FEE_UNKNOWN")
        self.assertEqual(trades[0]["gross_pnl"], 40.0)
        self.assertIsNone(trades[0]["quantity"])
        self.assertFalse(trades[0]["real_submit_allowed"])
        self.assertEqual(status["CLEAN_SHADOW_TRADE_N"], 0)
        self.assertEqual(status["BASELINE_N"], 0)
        self.assertEqual(status["FEATURE_DELTA_EV"], "NOT_AVAILABLE")
        self.assertEqual(status["PROMOTION_CANDIDATE"], "NONE")
