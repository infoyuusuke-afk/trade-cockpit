import copy
import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parents[1]
LEGACY = ROOT / "paper_trade_history.json"
MORNING = ROOT / "scripts" / "morning_review.py"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


journal = _load("new_virtual_signal_journal", "scripts/new_virtual_signal_journal.py")
evidence = _load("virtual_trade_evidence_for_journal", "scripts/virtual_trade_evidence.py")
morning = _load("morning_review_for_journal", "scripts/morning_review.py")


def observation(
    *,
    trade_id="vt-1",
    pnl_yen=1000,
    fees=100,
    slippage=20,
    role="TEST",
    side="LONG",
    symbol="285A",
    signal="2026-10-14T09:00:00+09:00",
    entry="2026-10-14T09:05:00+09:00",
    exit_at="2026-10-14T15:00:00+09:00",
    sequence="2026-10-14T15:00:01+09:00",
    window_start="2026-10-01T00:00:00+09:00",
    window_end="2026-10-31T23:59:59+09:00",
    strategy_id="day_ifo_long",
    strategy_version="1.0",
    lane="VIRTUAL_SIGNAL",
):
    observed = {name: signal for name in evidence.SIGNAL_FIELDS}
    observed["entry_time"] = entry
    for name in evidence.EXIT_FIELDS:
        observed[name] = exit_at
    observed["sequence_time"] = sequence
    return {
        "evidence_lane": lane,
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "sample_role": role,
        "sample_role_basis": "role fixed before the outcome was known",
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "signal_known_at": signal,
        "entry_time": entry,
        "exit_known_at": exit_at,
        "sequence_time": sequence,
        "window_start": window_start,
        "window_end": window_end,
        "universe_fixed_before_outcome": True,
        "universe_fixed_at": signal,
        "pnl_yen": pnl_yen,
        "fees": fees,
        "slippage": slippage,
        "cost_model_status": "VERIFIED",
        "cost_basis": {
            "fees_source": "explicit-fee-schedule",
            "slippage_source": "explicit-slippage-observation",
        },
        "mfe": 1.2,
        "mae": 0.4,
        "mfe_mae_units": "R",
        "mfe_mae_timeframe": "post_entry_path",
        "source": "new_virtual_trade",
        "inputs": [{"name": "morning_snapshot", "observed_at": signal}],
        "field_observed_at": observed,
    }


def cohort(n=30):
    rows = []
    for index in range(n):
        stamp = f"2026-10-13T09:{index:02d}"
        rows.append(observation(
            trade_id=f"t{index:03d}",
            pnl_yen=100 if index % 3 else -50,
            fees=10,
            slippage=5,
            side="SHORT" if index % 2 else "LONG",
            symbol="1000" if index % 2 else "2000",
            signal=f"{stamp}:00+09:00",
            entry=f"{stamp}:10+09:00",
            exit_at=f"{stamp}:30+09:00",
            sequence=f"{stamp}:40+09:00",
        ))
    return rows


def producer_row():
    data = {
        "day_ifo_candidates": [{
            "name": "キオクシア",
            "ticker": "285A",
            "side": "LONG",
            "score": 80,
            "plan": {
                "entry": 1000,
                "entry_limit": 1000,
                "stop": 980,
                "target1": 1030,
                "target2": 1050,
            },
            "price": 990,
            "atr_pct": 4.0,
            "turnover": 5_000_000_000,
        }]
    }
    now = datetime(2026, 10, 14, 8, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    snap = morning.morning_snapshot(data, now)
    plan = snap["candidates"][0]
    stock = {"intraday": {"low": 990, "high": 1040, "close": 1030, "vwap": 1010}, "price": 1030}
    row = morning.audit_one(plan, stock)
    row["date"] = now.date().isoformat()
    return row


class NewVirtualSignalJournalTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.pop(journal.ENV_PATH, None)
        self.legacy_before = LEGACY.read_bytes()

    def tearDown(self):
        if self._env is None:
            os.environ.pop(journal.ENV_PATH, None)
        else:
            os.environ[journal.ENV_PATH] = self._env
        self.assertEqual(LEGACY.read_bytes(), self.legacy_before)

    def test_producer_gap_is_conditional_and_blocks_a_live_row(self):
        report = journal.inspect_producer()
        self.assertEqual(report["acceptance"], "CONDITIONAL")
        self.assertFalse(report["producer_can_measure"])
        self.assertFalse(report["auto_record_armed"])
        self.assertFalse(report["morning_review_wired"])
        self.assertFalse(report["scheduled"])
        self.assertFalse(report["real_submit_allowed"])
        self.assertFalse(report["promotion_eligible"])
        self.assertFalse(report["statistical_edge_confirmed"])
        available = {item["field"]: item["available"] for item in report["fields"]}
        self.assertTrue(available["strategy_id"])
        self.assertTrue(available["side"])
        for name in (
            "symbol", "signal_known_at", "provenance", "sample_role", "trade_id",
            "universe_fixed_at", "window_start", "window_end", "fees", "slippage",
            "exit_known_at", "mfe", "mae",
        ):
            self.assertFalse(available[name], name)
        self.assertNotIn("new_virtual_signal_journal", MORNING.read_text(encoding="utf-8"))

        row = producer_row()
        self.assertEqual(row["strategy_id"], "day_ifo_long")
        self.assertEqual(row["strategy_version"], "1.0")
        self.assertIn("JST", row["signal_time"])
        self.assertNotIn("signal_known_at", row)
        self.assertNotIn("trade_id", row)
        self.assertNotIn("sample_role", row)
        self.assertEqual(row["fees"], 0)
        self.assertEqual(row["slippage"], 0)
        self.assertIn("MFE", row)
        self.assertNotIn("mfe", row)
        original = copy.deepcopy(row)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            out = journal.record_producer_row(row, journal_path=path, legacy_path=LEGACY)
            self.assertEqual(row, original)
            self.assertEqual(out["state"], "BLOCKED")
            self.assertEqual(out["transition"], ["OBSERVED", "BLOCKED"])
            self.assertEqual(out["reason"], "UNOBSERVED")
            for code in (
                "UNOBSERVED",
                "ALIAS_REFUSED_SIGNAL_TIME",
                "ALIAS_REFUSED_TICKER",
                "ALIAS_REFUSED_MFE",
                "ALIAS_REFUSED_MAE",
                "ALIAS_REFUSED_DATE",
                "EXCURSION_NOT_POINT_IN_TIME",
                "FEES_UNVERIFIED_ZERO",
                "SLIPPAGE_UNVERIFIED_ZERO",
            ):
                self.assertIn(code, out["reasons"], code)
            self.assertIn("trade_id", out["missing"])
            self.assertIn("signal_known_at", out["missing"])
            self.assertIn("sample_role", out["missing"])
            self.assertIn("exit_known_at", out["missing"])
            self.assertNotIn("signal_known_at", out["forwarded_fields"])
            self.assertNotIn("mfe", out["forwarded_fields"])
            self.assertNotIn("symbol", out["forwarded_fields"])
            self.assertIn("strategy_id", out["forwarded_fields"])
            self.assertIsNone(out["evidence"])
            self.assertIsNone(out["metrics"])
            self.assertFalse(out["admissible"])
            self.assertFalse(out["expectancy_demonstrated"])
            self.assertFalse(out["statistical_edge_confirmed"])
            self.assertEqual(out["producer_admissible_n"], 0)
            self.assertEqual(out["profitability_status"], "UNKNOWN")
            self.assertTrue(out["legacy_bytes_unchanged"])
            stored = journal.load_journal(path)
            self.assertEqual(stored["state"], "READY")
            self.assertEqual(len(stored["records"]), 1)
            self.assertEqual(stored["records"][0]["origin"], "producer")
            self.assertIsNone(stored["records"][0]["evidence"])
            self.assertNotIn("signal_known_at", stored["records"][0]["observation"])
            handoff = journal.handoff_admissible(path, legacy_path=LEGACY)
            self.assertEqual(handoff["producer_admissible_n"], 0)
            self.assertEqual(handoff["synthetic_admissible_n"], 0)
            self.assertIsNone(handoff["metrics"])
            self.assertIsNone(handoff["synthetic_metrics"])
            self.assertEqual(handoff["profitability_status"], "UNKNOWN")
            self.assertFalse(handoff["journal_written"])

    def test_complete_observation_reaches_measured_and_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            source = observation()
            before = copy.deepcopy(source)
            out = journal.record_observation(source, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(source, before)
            self.assertEqual(out["state"], "MEASURED")
            self.assertEqual(out["transition"], ["OBSERVED", "VALIDATED", "MEASURED"])
            self.assertIsNone(out["reason"])
            self.assertTrue(out["journal_written"])
            self.assertFalse(out["replayed"])
            self.assertEqual(out["evidence"]["trade_id"], "vt-1")
            self.assertEqual(out["evidence"]["session_bucket_tokyo"], "OPEN_0900")
            self.assertEqual(out["evidence"]["signal_known_at"], "2026-10-14T09:00:00+09:00")
            self.assertEqual(out["metrics"]["expectancy_per_trade"]["value"], 880)
            self.assertFalse(out["expectancy_demonstrated"])
            self.assertFalse(out["measurement_contract_met"])
            self.assertFalse(out["statistical_edge_confirmed"])
            self.assertFalse(out["promotion_eligible"])
            self.assertFalse(out["real_submit_allowed"])
            self.assertTrue(out["legacy_bytes_unchanged"])
            first_bytes = path.read_bytes()
            self.assertFalse(_partial(path).exists())

            replay = journal.record_observation(source, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertTrue(replay["replayed"])
            self.assertFalse(replay["journal_written"])
            self.assertEqual(replay["state"], "MEASURED")
            self.assertEqual(replay["evidence"], out["evidence"])
            self.assertEqual(path.read_bytes(), first_bytes)
            self.assertEqual(len(journal.load_journal(path)["records"]), 1)

            handoff = journal.handoff_admissible(path, legacy_path=LEGACY)
            self.assertEqual(handoff["producer_admissible_n"], 0)
            self.assertEqual(handoff["synthetic_admissible_n"], 1)
            self.assertIsNone(handoff["metrics"])
            self.assertEqual(handoff["synthetic_metrics"]["net_pnl"]["value"], 880)
            self.assertEqual(handoff["profitability_status"], "UNKNOWN")
            self.assertFalse(handoff["statistical_edge_confirmed"])
            self.assertFalse(handoff["expectancy_demonstrated"])
            self.assertFalse(handoff["journal_written"])
            self.assertEqual(path.read_bytes(), first_bytes)

    def test_missing_required_field_is_blocked_without_being_filled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            source = observation()
            source.pop("strategy_id")
            source.pop("trade_id")
            out = journal.record_observation(source, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(out["state"], "BLOCKED")
            self.assertEqual(out["transition"], ["OBSERVED", "BLOCKED"])
            self.assertEqual(out["reason"], "UNOBSERVED")
            self.assertIn("strategy_id", out["missing"])
            self.assertIn("trade_id", out["missing"])
            self.assertNotIn("strategy_id", out["forwarded_fields"])
            self.assertIsNone(out["evidence"])
            self.assertIsNone(out["metrics"])
            self.assertEqual(out["included_n"], 0)
            stored = journal.load_journal(path)["records"][0]["observation"]
            self.assertNotIn("strategy_id", stored)
            self.assertNotIn("trade_id", stored)

    def test_unverified_cost_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            source = observation(fees=0, slippage=0)
            source["cost_model_status"] = "UNVERIFIED"
            out = journal.record_observation(source, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(out["state"], "BLOCKED")
            self.assertEqual(out["transition"], ["OBSERVED", "BLOCKED"])
            self.assertEqual(out["reason"], "COST_UNVERIFIED")
            self.assertIn("FEES_UNVERIFIED_ZERO", out["reasons"])
            self.assertIn("SLIPPAGE_UNVERIFIED_ZERO", out["reasons"])
            self.assertIsNone(out["evidence"])
            self.assertFalse(out["expectancy_demonstrated"])
            self.assertFalse(out["statistical_edge_confirmed"])
            text = path.read_text(encoding="utf-8")
            self.assertNotIn('"cost_model_status": "VERIFIED"', text)

    def test_future_information_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            source = observation(exit_at="2026-10-14T08:00:00+09:00")
            out = journal.record_observation(source, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(out["state"], "BLOCKED")
            self.assertIn("LOOKAHEAD", out["reasons"])
            self.assertIsNone(out["evidence"])
            self.assertIsNone(out["metrics"])
            self.assertEqual(journal.handoff_admissible(path, legacy_path=LEGACY)["admissible_n"], 0)

    def test_duplicate_replays_and_conflict_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            first = journal.record_observation(observation(), journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(first["state"], "MEASURED")
            blob = path.read_bytes()
            conflict = observation(pnl_yen=1)
            refused = journal.record_observation(conflict, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(refused["state"], "BLOCKED")
            self.assertEqual(refused["reason"], "EVIDENCE_MISMATCH")
            self.assertFalse(refused["journal_written"])
            self.assertEqual(path.read_bytes(), blob)
            self.assertEqual(len(journal.load_journal(path)["records"]), 1)

    def test_corrupt_and_partial_files_are_not_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            path.write_bytes(b'{"contract": "new-virtual-signal-journal-1"')
            loaded = journal.load_journal(path)
            self.assertEqual(loaded["reason"], "PARTIAL_WRITE")
            self.assertIsNone(loaded["records"])
            self.assertFalse(loaded["partial_adopted"])
            refused = journal.record_observation(observation(), journal_path=path, legacy_path=LEGACY)
            self.assertEqual(refused["reason"], "PARTIAL_WRITE")
            self.assertFalse(refused["journal_written"])
            self.assertEqual(path.read_bytes(), b'{"contract": "new-virtual-signal-journal-1"')
            recovered = journal.recover_journal(path, legacy_path=LEGACY)
            self.assertEqual(recovered["reason"], "RECOVERY_REFUSED")
            self.assertFalse(recovered["partial_removed"])
            self.assertEqual(path.read_bytes(), b'{"contract": "new-virtual-signal-journal-1"')

            path.write_text('{"trade_id": "x"}\n', encoding="utf-8")
            corrupt = journal.load_journal(path)
            self.assertEqual(corrupt["reason"], "CORRUPT_JSON")
            self.assertIsNone(corrupt["records"])
            again = journal.record_observation(observation(), journal_path=path, legacy_path=LEGACY)
            self.assertEqual(again["reason"], "CORRUPT_JSON")
            self.assertEqual(path.read_text(encoding="utf-8"), '{"trade_id": "x"}\n')

    def test_restart_keeps_committed_records_and_ignores_partial_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            out = journal.record_observation(observation(), journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(out["state"], "MEASURED")
            committed = path.read_bytes()
            secret = "PARTIAL-SECRET-DO-NOT-MERGE"
            _partial(path).write_text(secret, encoding="utf-8")
            blocked = journal.record_observation(
                observation(trade_id="vt-2"), journal_path=path, legacy_path=LEGACY, origin="synthetic",
            )
            self.assertEqual(blocked["reason"], "PARTIAL_WRITE")
            self.assertFalse(blocked["partial_adopted"])
            self.assertEqual(path.read_bytes(), committed)
            self.assertEqual(_partial(path).read_text(encoding="utf-8"), secret)

            restored = journal.recover_journal(path, legacy_path=LEGACY)
            self.assertTrue(restored["recovered"])
            self.assertTrue(restored["partial_removed"])
            self.assertFalse(restored["partial_adopted"])
            self.assertFalse(restored["partial_bytes_used"])
            self.assertFalse(_partial(path).exists())
            self.assertEqual(path.read_bytes(), committed)
            self.assertNotIn(secret, path.read_text(encoding="utf-8"))
            reloaded = journal.load_journal(path)
            self.assertEqual(reloaded["state"], "READY")
            self.assertEqual(len(reloaded["records"]), 1)
            self.assertEqual(reloaded["records"][0]["evidence"]["trade_id"], "vt-1")

            orphan = Path(directory) / "orphan.json"
            _partial(orphan).write_text(secret, encoding="utf-8")
            refused = journal.recover_journal(orphan, legacy_path=LEGACY)
            self.assertEqual(refused["reason"], "RECOVERY_REFUSED")
            self.assertFalse(orphan.exists())
            self.assertEqual(_partial(orphan).read_text(encoding="utf-8"), secret)

    def test_utc_timestamp_is_normalized_and_naive_timestamp_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "utc.json"
            source = observation(
                signal="2026-10-14T00:00:00+00:00",
                entry="2026-10-14T00:05:00+00:00",
                exit_at="2026-10-14T06:00:00+00:00",
                sequence="2026-10-14T06:00:01+00:00",
            )
            out = journal.record_observation(source, journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(out["state"], "MEASURED")
            self.assertEqual(out["evidence"]["signal_known_at"], "2026-10-14T09:00:00+09:00")
            self.assertEqual(out["evidence"]["entry_time"], "2026-10-14T09:05:00+09:00")
            self.assertEqual(out["evidence"]["session_bucket_tokyo"], "OPEN_0900")
            other = Path(directory) / "utc-again.json"
            journal.record_observation(source, journal_path=other, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(path.read_bytes(), other.read_bytes())

            naive_path = Path(directory) / "naive.json"
            naive = observation()
            naive["signal_known_at"] = "2026-10-14T09:00:00"
            blocked = journal.record_observation(naive, journal_path=naive_path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(blocked["state"], "BLOCKED")
            self.assertIn("TIMESTAMP_NAIVE", blocked["reasons"])
            self.assertIsNone(blocked["evidence"])
            stored = journal.load_journal(naive_path)["records"][0]
            self.assertEqual(stored["observation"]["signal_known_at"], "2026-10-14T09:00:00")
            self.assertIsNone(stored["evidence"])

    def test_lanes_and_roles_are_not_blended(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            mixed = journal.record_observations(
                [observation(trade_id="real", lane="REAL_FILL", role="REAL"), observation(trade_id="virt")],
                journal_path=path,
                legacy_path=LEGACY,
                origin="synthetic",
            )
            self.assertEqual(mixed["state"], "BLOCKED")
            self.assertIn("MIXED_EVIDENCE_LANES", mixed["reasons"])
            self.assertIsNone(mixed["metrics"])
            self.assertFalse(mixed["statistical_edge_confirmed"])
            stored = {row["trade_id"]: row for row in journal.load_journal(path)["records"]}
            self.assertFalse(stored["real"]["admissible"])
            self.assertIsNone(stored["real"]["evidence"])
            self.assertTrue(stored["virt"]["admissible"])
            self.assertEqual(stored["virt"]["evidence"]["evidence_lane"], "VIRTUAL_SIGNAL")
            handoff = journal.handoff_admissible(path, legacy_path=LEGACY)
            self.assertIsNone(handoff["metrics"])
            self.assertFalse(handoff["blended"])
            self.assertEqual(handoff["producer_admissible_n"], 0)
            self.assertEqual(handoff["synthetic_metrics"]["trade_count"]["value"], 1)

            role_path = Path(directory) / "roles.json"
            roles = journal.record_observations(
                [observation(trade_id="train", role="TRAIN"), observation(trade_id="test", role="TEST")],
                journal_path=role_path,
                legacy_path=LEGACY,
                origin="synthetic",
            )
            self.assertEqual(roles["state"], "BLOCKED")
            self.assertEqual(roles["reason"], "MIXED_SAMPLE_ROLES")
            self.assertIsNone(roles["metrics"])
            separated = journal.handoff_admissible(role_path, legacy_path=LEGACY)
            self.assertIsNone(separated["metrics"])
            self.assertIsNone(separated["synthetic_metrics"])
            self.assertEqual(separated["reason"], "MIXED_SAMPLE_ROLES")
            self.assertEqual(len(separated["separated"]), 2)
            for item in separated["separated"].values():
                self.assertEqual(item["state"], "MEASURED")
                self.assertEqual(item["included_n"], 1)
                self.assertFalse(item["statistical_edge_confirmed"])
                self.assertFalse(item["expectancy_demonstrated"])

    def test_thirty_synthetic_rows_do_not_confirm_an_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            out = journal.record_observations(cohort(), journal_path=path, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(out["state"], "MEASURED")
            self.assertEqual(out["included_n"], 30)
            self.assertTrue(out["measurement_contract_met"])
            self.assertTrue(out["expectancy_demonstrated"])
            self.assertFalse(out["statistical_edge_confirmed"])
            self.assertFalse(out["edge_confirmed_by_sample_size"])
            self.assertFalse(out["promotion_eligible"])
            self.assertFalse(out["real_submit_allowed"])
            self.assertEqual(out["producer_admissible_n"], 0)
            self.assertEqual(out["profitability_status"], "UNKNOWN")
            nets = [(100 if index % 3 else -50) - 15 for index in range(30)]
            self.assertEqual(out["metrics"]["expectancy_per_trade"]["value"], sum(nets) / 30)
            self.assertEqual(out["metrics"]["profit_factor"]["value"], (20 * 85) / (10 * 65))
            handoff = journal.handoff_admissible(path, legacy_path=LEGACY)
            self.assertEqual(handoff["producer_admissible_n"], 0)
            self.assertEqual(handoff["synthetic_admissible_n"], 30)
            self.assertIsNone(handoff["metrics"])
            self.assertFalse(handoff["expectancy_demonstrated"])
            self.assertTrue(handoff["measurement_contract_met"])
            self.assertFalse(handoff["statistical_edge_confirmed"])
            self.assertEqual(handoff["profitability_status"], "UNKNOWN")
            self.assertEqual(handoff["synthetic_metrics"]["trade_count"]["value"], 30)
            self.assertEqual(handoff["synthetic_metrics"]["expectancy_per_trade"]["value"], sum(nets) / 30)

    def test_same_input_is_byte_identical_and_legacy_263_is_unchanged(self):
        self.assertEqual(len(json.loads(self.legacy_before.decode("utf-8"))), 263)
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "left.json"
            right = Path(directory) / "right.json"
            source = observation()
            journal.record_observation(source, journal_path=left, legacy_path=LEGACY, origin="synthetic")
            journal.record_observation(copy.deepcopy(source), journal_path=right, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(left.read_bytes(), right.read_bytes())
        self.assertEqual(LEGACY.read_bytes(), self.legacy_before)

    def test_unconfigured_public_and_legacy_paths_write_nothing(self):
        missing = journal.record_observation(observation(), legacy_path=LEGACY, origin="synthetic")
        self.assertEqual(missing["reason"], "JOURNAL_PATH_UNCONFIGURED")
        self.assertFalse(missing["journal_written"])
        self.assertFalse(missing["real_submit_allowed"])

        public = ROOT / "new_virtual_signal_journal.json"
        self.assertFalse(public.exists())
        refused = journal.record_observation(observation(), journal_path=public, legacy_path=LEGACY)
        self.assertEqual(refused["reason"], "PUBLIC_PATH_REJECTED")
        self.assertFalse(public.exists())

        legacy_write = journal.record_observation(observation(), journal_path=LEGACY, legacy_path=LEGACY)
        self.assertEqual(legacy_write["reason"], "REFUSED_LEGACY_WRITE")
        self.assertEqual(LEGACY.read_bytes(), self.legacy_before)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "from-env.json"
            os.environ[journal.ENV_PATH] = str(target)
            recorded = journal.record_observation(observation(), legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(recorded["state"], "MEASURED")
            self.assertTrue(target.is_file())
            os.environ.pop(journal.ENV_PATH, None)

        private = ROOT / "data" / "private" / "new_virtual_signal_journal_test.json"
        partial = _partial(private)
        try:
            allowed = journal.record_observation(observation(), journal_path=private, legacy_path=LEGACY, origin="synthetic")
            self.assertEqual(allowed["state"], "MEASURED")
            self.assertTrue(private.is_file())
            self.assertIn("data/private", str(private))
        finally:
            private.unlink(missing_ok=True)
            partial.unlink(missing_ok=True)

    def test_private_fields_are_not_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            source = observation()
            source["password"] = "do-not-store-this-secret"
            source["account_number"] = "999999"
            out = journal.record_observation(source, journal_path=path, legacy_path=LEGACY)
            self.assertEqual(out["reason"], "PRIVATE_DATA_REJECTED")
            self.assertFalse(out["journal_written"])
            self.assertFalse(path.exists())
            self.assertNotIn("do-not-store-this-secret", json.dumps(out))

    def test_checksum_mismatch_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.json"
            journal.record_observation(observation(), journal_path=path, legacy_path=LEGACY, origin="synthetic")
            document = json.loads(path.read_text(encoding="utf-8"))
            document["sha256"] = "0" * 64
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            blob = path.read_bytes()
            loaded = journal.load_journal(path)
            self.assertEqual(loaded["reason"], "JOURNAL_CHECKSUM_MISMATCH")
            self.assertIsNone(loaded["records"])
            refused = journal.record_observation(
                observation(trade_id="vt-2"), journal_path=path, legacy_path=LEGACY, origin="synthetic",
            )
            self.assertEqual(refused["reason"], "JOURNAL_CHECKSUM_MISMATCH")
            self.assertFalse(refused["journal_written"])
            self.assertEqual(path.read_bytes(), blob)
            recovered = journal.recover_journal(path, legacy_path=LEGACY)
            self.assertEqual(recovered["reason"], "RECOVERY_REFUSED")
            self.assertEqual(path.read_bytes(), blob)


def _partial(path):
    return Path(str(path) + journal.PARTIAL_SUFFIX)


if __name__ == "__main__":
    unittest.main()
