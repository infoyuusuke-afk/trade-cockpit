"""P0-V10-INTEGRATION-AND-LIVE-START-20261020: fresh-rows-only board use.

Synthetic data only. CI PASS is not a real-machine acceptance and approves no
deployment.

Rule (Get-BoardAvailability in the Gateway and the Collector bridge, and
assess_board_availability in the Shadow supervisor, all the same):
- A board whose only fault is STALE or UNKNOWN rows becomes AVAILABLE_PARTIAL
  when the identity quote is fresh, the universe is complete, no row is
  INVALID, >= 95% of the expected rows are FRESH, and the Collector declares
  aggregate_basis FRESH_ROWS_ONLY (market aggregates from FRESH rows only,
  signals of other rows blocked).
- Without that declaration, below 95%, with an INVALID row, a missing or
  unexpected row, or a stale identity quote, the board stays blocked.
- A non-fresh row is never used: no virtual entry or exit on it, and the Brain
  observer skips it.
"""
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load("v10_row_gate_operability_for_partial", "tests/test_v10_row_gate_operability.py")
sup = base.sup
brain = _load("v10_brain_observer_for_partial", "scripts/ai_brain_observer.py")
UNIVERSE = base.UNIVERSE
board = base.board
JST = base.JST


def partial(payload):
    payload = dict(payload)
    payload["aggregate_basis"] = "FRESH_ROWS_ONLY"
    return payload


class PartialAvailabilityRule(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-partial-"))
        base.write_watchlist(self.tmp)
        self.universe = sup.load_expected_universe(self.tmp)
        self.now = base.datetime(2026, 10, 21, 10, 0, 5, tzinfo=JST)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _avail(self, payload):
        return base.availability_of(payload, self.now, self.universe)

    def test_all_fresh_stays_full_available(self):
        got = self._avail(partial(board(self.now)))
        self.assertEqual(got["availability_status"], "AVAILABLE")
        self.assertIs(got["decision_available"], True)
        self.assertIs(got["partial_rows"], False)

    def test_one_stale_row_with_fresh_only_aggregates_is_partial(self):
        got = self._avail(partial(board(self.now, stale={"SYN50.T"})))
        self.assertEqual(got["availability_status"], "AVAILABLE_PARTIAL")
        self.assertIs(got["decision_available"], True)
        self.assertEqual(got["reasons"], [])
        self.assertIs(got["partial_rows"], True)
        self.assertIn("ROW_STALE_SOURCE_QUOTE", got["partial_reasons"])
        self.assertEqual(got["state_counts"]["FRESH"], 99)
        self.assertEqual(got["state_counts"]["STALE"], 1)
        self.assertIs(got["real_submit_allowed"], False)
        self.assertIs(got["order_allowed"], False)

    def test_without_collector_declaration_stays_blocked(self):
        got = self._avail(board(self.now, stale={"SYN50.T"}))
        self.assertEqual(got["availability_status"], "BLOCKED_ROW_QUOTES")
        self.assertIs(got["decision_available"], False)
        self.assertIs(got["partial_rows"], False)
        wrong = board(self.now, stale={"SYN50.T"})
        wrong["aggregate_basis"] = "ALL_ROWS"
        self.assertIs(self._avail(wrong)["decision_available"], False)

    def test_threshold_is_95_percent_of_expected(self):
        five = set(UNIVERSE[95:])
        six = set(UNIVERSE[94:])
        self.assertEqual(self._avail(partial(board(self.now, stale=five)))["availability_status"], "AVAILABLE_PARTIAL")
        got = self._avail(partial(board(self.now, stale=six)))
        self.assertEqual(got["availability_status"], "BLOCKED_ROW_QUOTES")
        self.assertIs(got["decision_available"], False)
        self.assertIn("ROW_QUOTE_NOT_FRESH", got["reasons"])

    def test_unknown_rows_count_against_threshold(self):
        got = self._avail(partial(board(self.now, unknown={"SYN10.T", "SYN11.T"})))
        self.assertEqual(got["availability_status"], "AVAILABLE_PARTIAL")
        got = self._avail(partial(board(self.now, unknown=set(UNIVERSE[1:]))))
        self.assertIs(got["decision_available"], False)

    def test_startup_with_nothing_observed_stays_blocked(self):
        got = self._avail(partial(board(self.now, unknown=set(UNIVERSE))))
        self.assertIs(got["decision_available"], False)
        self.assertNotEqual(got["availability_status"], "AVAILABLE_PARTIAL")

    def test_identity_stale_is_never_partial(self):
        got = self._avail(partial(board(self.now, identity_at=self.now - timedelta(minutes=5))))
        self.assertEqual(got["availability_status"], "BLOCKED_IDENTITY_QUOTE")
        self.assertIs(got["decision_available"], False)

    def test_missing_or_unexpected_row_is_never_partial(self):
        got = self._avail(partial(board(self.now, drop={"SYN42.T"}, declared=100)))
        self.assertEqual(got["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
        got = self._avail(partial(board(self.now, replace=("SYN13.T", "OTHER.T"))))
        self.assertEqual(got["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
        self.assertIs(got["decision_available"], False)

    def test_quote_pending_rows_do_not_block(self):
        # OWNER 2026-10-26 「特別気配の直し」: rows with no price yet (特別気配) listed by the Collector
        pending = [base._pending("SYN42.T"), base._pending("SYN43.T")]
        payload = partial(board(self.now, drop={"SYN42.T", "SYN43.T"}, declared=100))
        payload["missing_rows"] = pending
        got = self._avail(payload)
        self.assertEqual(got["availability_status"], "AVAILABLE_PARTIAL")
        self.assertIs(got["decision_available"], True)
        self.assertEqual(got["reasons"], [])
        self.assertEqual((got["quote_pending_count"], got["quote_pending_sample"]), (2, ["SYN42.T", "SYN43.T"]))
        self.assertIn("UNIVERSE_QUOTE_PENDING", got["partial_reasons"])
        self.assertEqual(got["missing_count"], 2)                       # still reported, never used
        self.assertIs(got["real_submit_allowed"], False)
        # without the Collector's PRICE_MISSING listing, a missing row still blocks
        payload["missing_rows"] = [pending[0]]
        self.assertEqual(self._avail(payload)["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
        # more than 5 rows, or a wrong sheet code, still blocks
        many = partial(board(self.now, drop=set(UNIVERSE[94:]), declared=100))
        many["missing_rows"] = [base._pending(t) for t in UNIVERSE[94:]]
        self.assertIs(self._avail(many)["decision_available"], False)
        wrong = partial(board(self.now, drop={"SYN42.T"}, declared=100))
        wrong["missing_rows"] = [dict(base._pending("SYN42.T"), sheet_code_matches=False)]
        self.assertIs(self._avail(wrong)["decision_available"], False)
        # with stale rows too, >= 95% of expected rows must still be FRESH
        mixed = partial(board(self.now, drop={"SYN42.T", "SYN43.T"}, stale=set(UNIVERSE[96:]), declared=100))
        mixed["missing_rows"] = pending
        self.assertIs(self._avail(mixed)["decision_available"], False)
        # without the Collector's FRESH_ROWS_ONLY declaration, it stays blocked
        bare = board(self.now, drop={"SYN42.T", "SYN43.T"}, declared=100)
        bare["missing_rows"] = pending
        self.assertIs(self._avail(bare)["decision_available"], False)

    def test_invalid_row_is_never_partial(self):
        # A row observed in the future is INVALID; one INVALID row blocks.
        future = self.now + timedelta(seconds=60)
        payload = partial(board(self.now, row_extra={"SYN20.T": base._quote(future)}))
        got = self._avail(payload)
        self.assertEqual(got["state_counts"]["INVALID"], 1)
        self.assertIs(got["decision_available"], False)
        self.assertEqual(got["availability_status"], "BLOCKED_ROW_QUOTES")
        self.assertIs(got["partial_rows"], False)
        # A row from another JST day never makes the board usable either.
        yesterday = self.now - timedelta(days=1)
        got = self._avail(partial(board(self.now, row_extra={"SYN21.T": base._quote(yesterday)})))
        self.assertIs(got["decision_available"], False)


class PartialShadowDecision(unittest.TestCase):
    """The Shadow supervisor acts on fresh rows of a partial board only."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-partial-shadow-"))
        base.write_watchlist(self.tmp)
        self.data = self.tmp / "ai_shadow"
        self.live = self.tmp / "live_ms2.json"
        self.status = self.tmp / "ai_shadow_status.json"
        self.t0 = base.datetime(2026, 10, 21, 10, 0, 5, tzinfo=JST)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cycle(self, payload, now):
        self.live.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(self.live, (now.timestamp(), now.timestamp()))
        engine = sup.run_once(self.data, self.live, self.status, now=now)
        return engine, json.loads(self.status.read_text(encoding="utf-8"))

    @staticmethod
    def _events(engine, kind):
        return [e for e in engine["ledger"] if e.get("event_type") == kind]

    @staticmethod
    def _buy(price=512.5):
        return {"signal": base.BUY, "price": price, "entry_price": price, "stop_price": price - 10}

    def test_fresh_row_enters_on_partial_board(self):
        payload = partial(board(self.t0, stale={"SYN50.T"}, row_extra={"SYN03.T": self._buy()}))
        engine, status = self._cycle(payload, self.t0)
        entries = self._events(engine, "virtual_entry")
        self.assertEqual([e["ticker"] for e in entries], ["SYN03.T"])
        self.assertEqual(status["board_availability"]["availability_status"], "AVAILABLE_PARTIAL")
        self.assertIs(status["real_submit_allowed"], False)

    def test_stale_row_never_enters_on_partial_board(self):
        payload = partial(board(self.t0, stale={"SYN50.T"}, row_extra={"SYN50.T": self._buy(654.5)}))
        engine, _ = self._cycle(payload, self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        judgment = self._events(engine, "board_judgment")[-1]
        row = [j for j in judgment["judgments"] if j["ticker"] == "SYN50.T"][0]
        self.assertEqual(row["row_quote_state"], "STALE")
        self.assertIs(row["entry_candidate"], False)

    def test_open_position_is_not_closed_on_a_stale_row(self):
        engine, _ = self._cycle(partial(board(self.t0, row_extra={"SYN03.T": self._buy()})), self.t0)
        self.assertEqual(len(self._events(engine, "virtual_entry")), 1)
        t1 = self.t0 + timedelta(seconds=5)
        # SYN03 left the buy set but its quote is stale: no exit price is taken.
        engine, status = self._cycle(partial(board(t1, stale={"SYN03.T"})), t1)
        self.assertEqual(status["board_availability"]["availability_status"], "AVAILABLE_PARTIAL")
        self.assertEqual(self._events(engine, "virtual_exit"), [])
        t2 = self.t0 + timedelta(seconds=10)
        engine, _ = self._cycle(partial(board(t2)), t2)
        self.assertEqual(len(self._events(engine, "virtual_exit")), 1)

    def test_below_threshold_decides_nothing(self):
        payload = partial(board(self.t0, stale=set(UNIVERSE[90:]), row_extra={"SYN03.T": self._buy()}))
        engine, status = self._cycle(payload, self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        self.assertEqual(status["decision_state"], "DECISION_BLOCKED")


class BrainObserverSkipsNonFreshRows(unittest.TestCase):
    def _snapshot(self, now, rows):
        return {
            "schema_version": "ms2-common-1.0", "source": brain.SOURCE, "source_mode": "MS2_RSS_WORKBOOK",
            "real_submit_allowed": False, "data_conflict": False, "stale": False, "live_values_available": True,
            "price_source_status": "OK", "timestamp_timezone": "Asia/Tokyo",
            "observed_at_offset": now.isoformat(timespec="seconds"),
            "live_price_diagnostics": {"workbook_name": brain.WORKBOOK, "workbook_identity_verified": True,
                                       "source_mode": "MS2_RSS_WORKBOOK", "price_source_status": "OK",
                                       "data_conflict": False, "live_values_available": True,
                                       "collector_count": 1, "watcher_count": 1},
            "valid": len(rows), "all_targets": rows,
        }

    def test_only_fresh_rows_are_observed(self):
        now = base.datetime(2026, 10, 21, 10, 0, 5, tzinfo=JST)
        rows = []
        for i in range(100):
            ticker = "%04d.T" % (1000 + i)
            rows.append({"ticker": ticker, "sheet_code": ticker, "data": "LIVE", "price": 110.0, "vwap": 100.0,
                         "or_high": 105.0, "or_low": 95.0, "aggregate_row_fresh": i != 7})
        got = brain.analyze(self._snapshot(now, rows), now=now, file_modified_at=now)
        self.assertEqual(got["state"], "OBSERVATION_ONLY")
        self.assertEqual(got["non_fresh_rows_skipped"], 1)
        self.assertEqual(got["observed_rows"], 99)
        self.assertNotIn("1007.T", [w["symbol"] for w in got["watch_observations"]])
        self.assertEqual(sum(got["watch_counts"].values()), 99)

    def test_rows_without_freshness_flag_are_not_observed(self):
        now = base.datetime(2026, 10, 21, 10, 0, 5, tzinfo=JST)
        rows = [{"ticker": "%04d.T" % (1000 + i), "sheet_code": "%04d.T" % (1000 + i), "data": "LIVE",
                 "price": 110.0, "vwap": 100.0, "or_high": 105.0, "or_low": 95.0} for i in range(100)]
        got = brain.analyze(self._snapshot(now, rows), now=now, file_modified_at=now)
        self.assertEqual(got["non_fresh_rows_skipped"], 100)
        self.assertEqual(sum(got["watch_counts"].values()), 0)


class CollectorSourceContract(unittest.TestCase):
    """Static checks on the Collector: aggregates from FRESH rows, stale rows blocked."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1").read_text(encoding="utf-8-sig")

    def test_breadth_and_sector_breadth_use_fresh_rows_only(self):
        self.assertIn("$breadthBase=@($aggregateRows|Where-Object{$_.vwap -gt 0})", self.src)
        self.assertIn("foreach($sectorGroup in @($aggregateRows|Where-Object{$_.vwap -gt 0}|Group-Object sector)){",
                      self.src)
        self.assertNotIn("$breadthBase=@($results|Where-Object{$_.vwap -gt 0})", self.src)
        # The fresh set is judged with the Gateway's own row rule.
        self.assertRegex(self.src, r"\$aggregateVerdict=Get-RowQuoteFreshness -Row \$result -Now \$aggregateNow "
                                   r"-BoardQuoteAt \$aggregateBoardQuoteAt")

    def test_non_fresh_rows_get_no_trading_signal_in_session(self):
        self.assertIn('elseif($inSession -and $result.aggregate_row_fresh -ne $true){$result.signal="鮮度不足・売買禁止"}',
                      self.src)
        self.assertIn('$holdSignal="鮮度不足・持ち越し判定不可"', self.src)

    def test_payload_declares_fresh_only_aggregates(self):
        self.assertIn("aggregate_basis='FRESH_ROWS_ONLY';aggregate_fresh_count=$aggregateFreshCount", self.src)
        self.assertRegex(self.src, r"real_submit_allowed=\$false;live_price_diagnostics=")

    def test_partial_rule_text_is_identical_in_gateway_and_collector(self):
        gateway = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1").read_text(encoding="utf-8-sig")
        pattern = re.compile(r"^function Get-BoardAvailability\b.*?^}\n", re.MULTILINE | re.DOTALL)
        a = pattern.search(self.src.replace("\r\n", "\n")).group(0)
        b = pattern.search(gateway.replace("\r\n", "\n")).group(0)
        self.assertEqual(a, b)
        self.assertIn('$status = "AVAILABLE_PARTIAL"', a)
        self.assertIn("$partialMinFreshPct = 95.0", a)


if __name__ == "__main__":
    unittest.main()
