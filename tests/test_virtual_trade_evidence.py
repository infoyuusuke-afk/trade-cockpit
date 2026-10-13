import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
LEGACY = ROOT / "paper_trade_history.json"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evidence = _load("virtual_trade_evidence", "scripts/virtual_trade_evidence.py")
adapter = _load("paper_history_expectancy_adapter_for_evidence", "scripts/paper_history_expectancy_adapter.py")
ledger = _load("strategy_expectancy_ledger_for_evidence", "scripts/strategy_expectancy_ledger.py")
morning = _load("morning_review_for_evidence", "scripts/morning_review.py")


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


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
):
    observed = {name: signal for name in evidence.SIGNAL_FIELDS}
    observed["entry_time"] = entry
    for name in evidence.EXIT_FIELDS:
        observed[name] = exit_at
    observed["sequence_time"] = sequence
    return {
        "evidence_lane": "VIRTUAL_SIGNAL",
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
        "inputs": [],
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


def _drawdown(nets):
    cumulative = peak = worst = 0.0
    for value in nets:
        cumulative += value
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return worst


class VirtualTradeEvidenceTests(unittest.TestCase):
    def test_complete_new_record_is_measured(self):
        fields = {item["field"] for item in evidence.FIELD_CONTRACT}
        for name in (
            "evidence_lane", "strategy_id", "strategy_version", "sample_role", "trade_id",
            "symbol", "side", "signal_known_at", "entry_time", "exit_known_at",
            "sequence_time", "window_start", "window_end", "universe_fixed_before_outcome",
            "pnl_yen", "fees", "slippage", "cost_model_status", "mfe", "mae", "source",
            "provenance",
        ):
            self.assertIn(name, fields)
        for item in evidence.FIELD_CONTRACT:
            self.assertTrue(item["source"])
            self.assertTrue(item["observed_at"])
            self.assertTrue(item["confirmed_when"])

        source = observation()
        before = copy.deepcopy(source)
        out = evidence.ingest(source)
        self.assertEqual(source, before)
        self.assertEqual(out["state"], "MEASURED")
        self.assertEqual(out["transition"], ["SOURCE", "VALIDATED", "MEASURED"])
        self.assertIsNone(out["reason"])
        self.assertTrue(out["accepted"])
        self.assertEqual(out["included_n"], 1)
        self.assertEqual(out["excluded_n"], 0)
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertIn("INSUFFICIENT_SAMPLE", out["integrity"])
        self.assertFalse(out["statistical_edge_confirmed"])
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])
        saved = out["evidence"]
        self.assertEqual(saved["evidence_lane"], "VIRTUAL_SIGNAL")
        self.assertEqual(saved["trade_id"], "vt-1")
        self.assertEqual(saved["cost_model_status"], "VERIFIED")
        self.assertEqual(saved["fees"], 100)
        self.assertEqual(saved["slippage"], 20)
        self.assertEqual(saved["pnl_yen"], 1000)
        self.assertEqual(saved["session_bucket_tokyo"], "OPEN_0900")
        self.assertEqual(saved["promotion_eligible"], False)
        self.assertEqual(saved["real_submit_allowed"], False)
        for field in ("signal_known_at", "fees", "mfe", "source"):
            detail = saved["provenance"][field]
            self.assertTrue(detail["source"])
            self.assertTrue(detail["observed_at"])
            self.assertTrue(detail["confirmed_when"])
        self.assertEqual(out["metrics"]["expectancy_per_trade"]["value"], 880)
        self.assertEqual(out["metrics"]["net_pnl"]["value"], 880)
        self.assertEqual(out["metrics"]["trade_count"]["value"], 1)
        self.assertLess(
            out["metrics"]["expectancy_per_trade"]["value"],
            out["metrics"]["gross_expectancy_per_trade"]["value"],
        )

    def test_missing_required_information_is_blocked(self):
        for key in ("strategy_id", "trade_id", "signal_known_at", "universe_fixed_before_outcome", "mfe"):
            source = observation()
            source.pop(key)
            before = copy.deepcopy(source)
            out = evidence.ingest(source)
            self.assertEqual(source, before, key)
            self.assertEqual(out["transition"], ["SOURCE", "BLOCKED"], key)
            self.assertEqual(out["state"], "BLOCKED", key)
            self.assertEqual(out["reason"], "UNOBSERVED", key)
            self.assertIn(key, out["missing"], key)
            self.assertIsNone(out["evidence"], key)
            self.assertIsNone(out["evidence_records"], key)
            self.assertIsNone(out["metrics"], key)
            self.assertEqual(out["included_n"], 0, key)
            self.assertFalse(out["expectancy_demonstrated"], key)

    def test_unverified_cost_is_blocked_and_not_promoted(self):
        source = observation(fees=0, slippage=0)
        source["cost_model_status"] = "UNVERIFIED"
        out = evidence.ingest(source)
        self.assertEqual(out["state"], "BLOCKED")
        self.assertEqual(out["transition"], ["SOURCE", "BLOCKED"])
        self.assertEqual(out["reason"], "COST_UNVERIFIED")
        self.assertIn("FEES_UNVERIFIED_ZERO", out["reasons"])
        self.assertIn("SLIPPAGE_UNVERIFIED_ZERO", out["reasons"])
        self.assertIsNone(out["evidence"])
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["expectancy_demonstrated"])

        verified_without_basis = observation(fees=0, slippage=0)
        verified_without_basis["cost_basis"] = {"fees_source": "placeholder", "slippage_source": "placeholder"}
        refused = evidence.ingest(verified_without_basis)
        self.assertEqual(refused["reason"], "COST_BASIS_ABSENT")
        self.assertIsNone(refused["evidence"])
        self.assertNotEqual(refused.get("cost_model_status"), "VERIFIED")

        explicit_zero = evidence.ingest(observation(fees=0, slippage=0))
        self.assertEqual(explicit_zero["state"], "MEASURED")
        self.assertEqual(explicit_zero["evidence"]["fees"], 0)
        self.assertEqual(explicit_zero["evidence"]["slippage"], 0)
        self.assertEqual(explicit_zero["evidence"]["cost_model_status"], "VERIFIED")
        self.assertEqual(explicit_zero["evidence"]["cost_basis"]["fees_source"], "explicit-fee-schedule")

    def test_invalid_timestamp_is_blocked(self):
        display = observation()
        display["entry_time"] = "2026-10-14 09:05:00 JST"
        display["field_observed_at"]["entry_time"] = "2026-10-14 09:05:00 JST"
        display_out = evidence.ingest(display)
        self.assertEqual(display_out["state"], "BLOCKED")
        self.assertIn("TIMESTAMP_INVALID", display_out["reasons"])
        self.assertIsNone(display_out["evidence"])
        self.assertNotEqual(display_out["evidence"], "2026-10-14T09:05:00+09:00")

        naive = observation()
        naive["entry_time"] = "2026-10-14T09:05:00"
        naive["field_observed_at"]["entry_time"] = "2026-10-14T09:05:00"
        naive_out = evidence.ingest(naive)
        self.assertEqual(naive_out["transition"], ["SOURCE", "BLOCKED"])
        self.assertIn("TIMESTAMP_NAIVE", naive_out["reasons"])
        self.assertIsNone(naive_out["evidence"])

    def test_lookahead_is_blocked(self):
        early_exit = observation(
            signal="2026-10-14T09:00:00+09:00",
            entry="2026-10-14T08:00:00+09:00",
            exit_at="2026-10-14T08:30:00+09:00",
            sequence="2026-10-14T08:30:01+09:00",
        )
        early = evidence.ingest(early_exit)
        self.assertEqual(early["state"], "BLOCKED")
        self.assertIn("LOOKAHEAD", early["reasons"])
        self.assertIsNone(early["evidence"])
        self.assertIsNone(early["metrics"])

        future_input = observation()
        future_input["inputs"] = [{
            "name": "close",
            "observed_at": "2026-10-14T15:00:00+09:00",
        }]
        future = evidence.ingest(future_input)
        self.assertEqual(future["transition"], ["SOURCE", "BLOCKED"])
        self.assertEqual(future["reason"], "LOOKAHEAD")
        self.assertIsNone(future["evidence"])

        late_universe = observation()
        late_universe["universe_fixed_at"] = "2026-10-14T15:00:00+09:00"
        universe = evidence.ingest(late_universe)
        self.assertIn("UNIVERSE_AFTER_OUTCOME", universe["reasons"])
        self.assertIsNone(universe["evidence"])

    def test_duplicate_trade_id_is_blocked(self):
        rows = [observation(trade_id="same"), observation(trade_id="same", pnl_yen=-40)]
        out = evidence.ingest_cohort(rows)
        self.assertEqual(out["state"], "BLOCKED")
        self.assertEqual(out["transition"], ["SOURCE", "BLOCKED"])
        self.assertEqual(out["reason"], "DUPLICATE_TRADE_ID")
        self.assertIsNone(out["metrics"])
        self.assertIsNone(out["separated"])
        self.assertEqual(out["included_n"], 0)
        self.assertEqual([row["state"] for row in out["rows"]], ["BLOCKED", "BLOCKED"])
        self.assertFalse(out["expectancy_demonstrated"])

        known = evidence.ingest(observation(), known_trade_ids={"vt-1"})
        self.assertEqual(known["reason"], "DUPLICATE_TRADE_ID")
        self.assertIsNone(known["evidence"])

    def test_real_and_virtual_are_separated(self):
        virtual = observation(trade_id="virtual-1")
        real = observation(trade_id="real-1")
        real["evidence_lane"] = "REAL_FILL"
        real["sample_role"] = "REAL"
        out = evidence.ingest_cohort([virtual, real])
        self.assertEqual(out["state"], "BLOCKED")
        self.assertEqual(out["reason"], "MIXED_EVIDENCE_LANES")
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["blended"])
        self.assertFalse(out["expectancy_demonstrated"])
        self.assertEqual(out["included_n"], 0)
        separated = out["separated"]["VIRTUAL_SIGNAL"]
        self.assertEqual(separated["state"], "MEASURED")
        self.assertEqual(separated["included_n"], 1)
        self.assertEqual(separated["evidence"]["evidence_lane"], "VIRTUAL_SIGNAL")
        self.assertEqual(separated["metrics"]["expectancy_per_trade"]["value"], 880)
        self.assertNotIn("REAL_FILL", out["separated"])
        self.assertEqual(out["rows"][1]["reason"], "LANE_NOT_VIRTUAL")
        self.assertIsNone(out["rows"][1]["evidence"])

    def test_train_test_and_shadow_are_separated(self):
        rows = [
            observation(trade_id="train", role="TRAIN", pnl_yen=100),
            observation(trade_id="test", role="TEST", pnl_yen=-50),
            observation(trade_id="shadow", role="SHADOW", pnl_yen=25),
        ]
        out = evidence.ingest_cohort(rows)
        self.assertEqual(out["reason"], "MIXED_SAMPLE_ROLES")
        self.assertIsNone(out["metrics"])
        self.assertFalse(out["blended"])
        self.assertEqual(out["included_n"], 0)
        self.assertEqual(set(out["separated"]), {"TRAIN", "TEST", "SHADOW"})
        for role, pnl, fees, slippage in (
            ("TRAIN", 100, 100, 20),
            ("TEST", -50, 100, 20),
            ("SHADOW", 25, 100, 20),
        ):
            part = out["separated"][role]
            self.assertEqual(part["state"], "MEASURED", role)
            self.assertEqual(part["evidence"]["sample_role"], role, role)
            self.assertEqual(part["metrics"]["expectancy_per_trade"]["value"], pnl - fees - slippage, role)
            self.assertNotEqual(part["evidence"]["sample_role"], "REAL", role)

        shadow = evidence.ingest(observation(role="SHADOW"))
        self.assertEqual(shadow["state"], "MEASURED")
        self.assertEqual(shadow["evidence"]["sample_role"], "SHADOW")

    def test_legacy_263_rows_are_not_modified(self):
        before = LEGACY.read_bytes()
        audit = evidence.audit_legacy_history(LEGACY)
        self.assertEqual(audit["count"], 263)
        self.assertTrue(audit["bytes_unchanged"])
        self.assertFalse(audit["legacy_rewritten"])
        self.assertEqual(audit["sha256_before"], audit["sha256_after"])
        self.assertEqual(audit["status"], "BLOCKED")
        self.assertEqual(audit["reason"], "EVIDENCE_LANE_INVALID")
        self.assertEqual(audit["included_n"], 0)
        self.assertIsNone(audit["metrics"])
        self.assertFalse(audit["expectancy_demonstrated"])
        self.assertFalse(audit["promotion_eligible"])
        self.assertFalse(audit["real_submit_allowed"])
        self.assertEqual(LEGACY.read_bytes(), before)

        legacy_row = json.loads(before.decode("utf-8"))[-1]
        original = copy.deepcopy(legacy_row)
        projected = evidence.from_morning_review_row(legacy_row)
        self.assertEqual(legacy_row, original)
        self.assertEqual(projected["state"], "BLOCKED")
        self.assertEqual(projected["transition"], ["SOURCE", "BLOCKED"])
        self.assertFalse(projected["aliased"])
        self.assertIn("signal_time", projected["refused_aliases"])
        self.assertIn("MFE", projected["refused_aliases"])
        self.assertIn("MAE", projected["refused_aliases"])
        self.assertIn("ticker", projected["refused_aliases"])
        self.assertIsNone(projected["evidence"])
        self.assertIn("FEES_UNVERIFIED_ZERO", projected["reasons"])
        self.assertIn("UNOBSERVED", projected["reasons"])
        self.assertEqual(LEGACY.read_bytes(), before)

        plan = {
            "name": "テスト",
            "ticker": "7203.T",
            "side": "LONG",
            "score": 80,
            "entry": 100,
            "entry_limit": 100,
            "stop": 95,
            "target1": 110,
            "target2": 120,
            "signal_time": "2026-10-14 09:00:00 JST",
            "strategy_id": "day_ifo_long",
            "strategy_version": "1.0",
            "source": "morning_snapshot",
        }
        reviewed = morning.audit_one(plan, {"intraday": {"low": 99, "high": 111, "close": 110, "vwap": 105}})
        self.assertEqual(reviewed["fees"], 0)
        self.assertEqual(reviewed["slippage"], 0)
        self.assertNotIn("cost_model_status", reviewed)
        self.assertNotIn("evidence_lane", reviewed)
        producer = evidence.from_morning_review_row(reviewed)
        self.assertEqual(producer["state"], "BLOCKED")
        self.assertIsNone(producer["evidence"])
        self.assertIn("MFE", producer["refused_aliases"])
        self.assertEqual(LEGACY.read_bytes(), before)

    def test_same_input_produces_the_same_output(self):
        first = evidence.ingest(observation())
        second = evidence.ingest(observation())
        third = evidence.ingest_cohort([observation()])
        self.assertEqual(_dump(first), _dump(second))
        self.assertEqual(first["evidence"]["trade_id"], third["evidence_records"][0]["trade_id"])
        self.assertEqual(first["metrics"], third["metrics"])
        self.assertEqual(first["transition"], third["transition"])

        utc = evidence.ingest(observation(
            signal="2026-10-14T00:00:00+00:00",
            entry="2026-10-14T00:05:00+00:00",
            exit_at="2026-10-14T06:00:00+00:00",
            sequence="2026-10-14T06:00:01+00:00",
        ))
        jst = evidence.ingest(observation())
        self.assertEqual(utc["evidence"]["entry_time"], jst["evidence"]["entry_time"])
        self.assertEqual(utc["evidence"]["signal_known_at"], "2026-10-14T09:00:00+09:00")
        self.assertEqual(utc["evidence"]["session_bucket_tokyo"], jst["evidence"]["session_bucket_tokyo"])
        self.assertNotEqual(
            utc["evidence"]["provenance"]["entry_time"]["original"],
            jst["evidence"]["provenance"]["entry_time"]["original"],
        )
        self.assertEqual(_dump(evidence.ingest(observation())), _dump(first))

    def test_session_bucket_uses_asia_tokyo(self):
        self.assertEqual(evidence.tokyo_session_bucket("2026-10-14T00:05:00+00:00"), "OPEN_0900")
        self.assertEqual(evidence.tokyo_session_bucket("2026-10-14T09:05:00+09:00"), "OPEN_0900")
        self.assertEqual(evidence.tokyo_session_bucket("2026-10-14T15:10:00+09:00"), "CLOSE_1500")
        self.assertEqual(evidence.tokyo_session_bucket("2026-10-13T23:00:00+00:00"), "OUT_OF_NAMED_SESSION")
        self.assertIsNone(evidence.tokyo_session_bucket("2026-10-14T09:05:00"))
        self.assertIsNone(evidence.tokyo_session_bucket("2026-10-14 09:05:00 JST"))

        saved = evidence.ingest(observation(
            signal="2026-10-14T00:00:00+00:00",
            entry="2026-10-14T00:05:00+00:00",
            exit_at="2026-10-14T06:00:00+00:00",
            sequence="2026-10-14T06:00:01+00:00",
        ))["evidence"]
        self.assertEqual(saved["entry_time"], "2026-10-14T09:05:00+09:00")
        self.assertEqual(saved["session_bucket_tokyo"], "OPEN_0900")
        measured = ledger.measure(adapter.connect([saved])["projected"])
        self.assertEqual(set(measured["by_time_bucket"]), {"OPEN_0900"})
        self.assertEqual(measured["status"], "MEASURED")

    def test_ledger_and_adapter_agree_on_a_clean_cohort(self):
        rows = cohort()
        out = evidence.ingest_cohort(rows)
        self.assertEqual(out["state"], "MEASURED")
        self.assertEqual(out["transition"], ["SOURCE", "VALIDATED", "MEASURED"])
        self.assertEqual(out["included_n"], 30)
        self.assertTrue(out["expectancy_demonstrated"])
        self.assertFalse(out["statistical_edge_confirmed"])
        self.assertFalse(out["promotion_eligible"])
        self.assertFalse(out["real_submit_allowed"])
        self.assertEqual(out["integrity"], [])
        nets = [(100 if index % 3 else -50) - 15 for index in range(30)]
        self.assertEqual(out["metrics"]["expectancy_per_trade"]["value"], sum(nets) / 30)
        self.assertEqual(out["metrics"]["max_drawdown"]["value"], _drawdown(nets))
        self.assertEqual(out["metrics"]["profit_factor"]["value"], (20 * 85) / (10 * 65))
        handoff = adapter.connect(out["evidence_records"])
        direct = ledger.measure(handoff["projected"])
        self.assertEqual(handoff["status"], "MEASURED")
        self.assertEqual(direct["status"], "MEASURED")
        self.assertEqual(direct["included_n"], 30)
        self.assertEqual(direct["metrics"]["expectancy_per_trade"]["value"], out["metrics"]["expectancy_per_trade"]["value"])
        self.assertEqual(direct["metrics"]["profit_factor"]["value"], out["metrics"]["profit_factor"]["value"])
        self.assertFalse(direct["promotion_eligible"])
        self.assertFalse(direct["real_submit_allowed"])
        self.assertEqual(set(direct["by_time_bucket"]), {"OPEN_0900", "AM_0915"})

        mixed = evidence.ingest_cohort([
            observation(trade_id="a", strategy_id="day_ifo_long"),
            observation(trade_id="b", strategy_id="day_short_mvp"),
        ])
        self.assertEqual(mixed["reason"], "MIXED_STRATEGY_IDS")
        self.assertIsNone(mixed["metrics"])
        self.assertEqual(set(mixed["separated"]), {"day_ifo_long", "day_short_mvp"})

    def test_corrupt_json_is_refused_without_repair(self):
        before = LEGACY.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "journal.json"
            journal.write_bytes(b"{")
            loaded = evidence.load_journal(journal)
            self.assertEqual(loaded["state"], "BLOCKED")
            self.assertEqual(loaded["reason"], "CORRUPT_JSON")
            self.assertIsNone(loaded["records"])
            refused = evidence.append_measured(journal, [observation()], legacy_path=LEGACY)
            self.assertEqual(refused["state"], "BLOCKED")
            self.assertEqual(refused["reason"], "CORRUPT_JSON")
            self.assertFalse(refused["journal_written"])
            self.assertEqual(journal.read_bytes(), b"{")
            self.assertTrue(refused["legacy_bytes_unchanged"])

            journal.write_text('{"trade_id": "x"}\n', encoding="utf-8")
            shaped = evidence.load_journal(journal)
            self.assertEqual(shaped["reason"], "RECORDS_NOT_A_LIST")
            self.assertIsNone(shaped["records"])

            journal.write_text("[1, 2]\n", encoding="utf-8")
            broken_rows = evidence.load_journal(journal)
            self.assertEqual(broken_rows["reason"], "RECORD_NOT_AN_OBJECT")

            missing = evidence.load_journal(Path(directory) / "absent.json")
            self.assertEqual(missing["reason"], "JOURNAL_UNREADABLE")
            self.assertIsNone(missing["records"])

            not_a_batch = evidence.ingest_cohort({"trade_id": "x"})
            self.assertEqual(not_a_batch["reason"], "RECORDS_NOT_A_LIST")
        self.assertEqual(LEGACY.read_bytes(), before)

    def test_live_submission_stays_disabled(self):
        source = (ROOT / "scripts" / "virtual_trade_evidence.py").read_text(encoding="utf-8")
        self.assertNotIn("import RssOrder", source)
        self.assertNotIn("real_submit_allowed = True", source)
        self.assertNotIn("promotion_eligible = True", source)
        self.assertNotIn("real_submit_allowed=True", source)

        flagged = observation()
        flagged["real_submit_allowed"] = True
        flagged["promotion_eligible"] = True
        flagged["RssOrder"] = {"symbol": "285A", "qty": 100}
        refused = evidence.ingest(flagged)
        self.assertEqual(refused["reason"], "PRIVATE_DATA_REJECTED")
        self.assertIsNone(refused["evidence"])
        self.assertNotIn("285A", _dump(refused))
        self.assertFalse(refused["real_submit_allowed"])

        flagged = observation()
        flagged["real_submit_allowed"] = True
        flagged["promotion_eligible"] = True
        refused = evidence.ingest(flagged)
        self.assertEqual(refused["reason"], "SAFETY_FLAG_REJECTED")
        self.assertEqual(refused["transition"], ["SOURCE", "BLOCKED"])
        self.assertIsNone(refused["evidence"])
        self.assertFalse(refused["real_submit_allowed"])
        self.assertFalse(refused["promotion_eligible"])
        self.assertFalse(refused["expectancy_demonstrated"])

        saved = evidence.ingest(observation())
        self.assertFalse(saved["real_submit_allowed"])
        self.assertFalse(saved["promotion_eligible"])
        self.assertFalse(saved["evidence"]["real_submit_allowed"])
        self.assertFalse(saved["evidence"]["promotion_eligible"])
        self.assertFalse(saved["statistical_edge_confirmed"])

    def test_validated_duplicate_is_not_repaired_by_the_ledger(self):
        first = evidence.ingest(observation(trade_id="keep"))["evidence"]
        second = evidence.ingest(observation(trade_id="other", pnl_yen=-40))["evidence"]
        second = dict(second)
        second["trade_id"] = first["trade_id"]
        out = evidence.measure_validated_cohort([first, second])
        self.assertEqual(out["transition"], ["SOURCE", "VALIDATED", "BLOCKED"])
        self.assertEqual(out["reason"], "DUPLICATE_FILL")
        self.assertIsNone(out["metrics"])
        self.assertEqual(out["included_n"], 0)
        self.assertEqual(out["submitted_records"][0]["trade_id"], out["submitted_records"][1]["trade_id"])
        self.assertIsNone(out["evidence_records"])
        self.assertFalse(out["expectancy_demonstrated"])

    def test_append_writes_only_measured_rows_and_leaves_legacy_bytes(self):
        before = LEGACY.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "virtual_trade_evidence.json"
            written = evidence.append_measured(journal, [observation()], legacy_path=LEGACY)
            self.assertEqual(written["state"], "MEASURED")
            self.assertTrue(written["journal_written"])
            self.assertTrue(written["legacy_bytes_unchanged"])
            saved_bytes = journal.read_bytes()
            again = evidence.append_measured(journal, [observation()], legacy_path=LEGACY)
            self.assertEqual(again["reason"], "DUPLICATE_TRADE_ID")
            self.assertFalse(again["journal_written"])
            self.assertTrue(again["journal_unchanged"])
            self.assertEqual(journal.read_bytes(), saved_bytes)

            unverified = observation(trade_id="cost", fees=0, slippage=0)
            unverified["cost_model_status"] = "UNVERIFIED"
            other = Path(directory) / "other.json"
            blocked = evidence.append_measured(other, [unverified], legacy_path=LEGACY)
            self.assertEqual(blocked["state"], "BLOCKED")
            self.assertFalse(blocked["journal_written"])
            self.assertFalse(other.exists())

            refused = evidence.append_measured(LEGACY, [observation(trade_id="nope")], legacy_path=LEGACY)
            self.assertEqual(refused["reason"], "REFUSED_LEGACY_WRITE")
            self.assertFalse(refused["journal_written"])

            loaded = evidence.load_journal(journal)
            self.assertEqual(loaded["state"], "READY")
            replay = adapter.connect(loaded["records"])
            self.assertEqual(replay["status"], "MEASURED")
            self.assertEqual(replay["included_n"], 1)
            self.assertFalse(replay["real_submit_allowed"])
        self.assertEqual(LEGACY.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
