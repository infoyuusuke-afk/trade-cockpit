"""P0-V10-ROW-GATE-OPERABILITY-20261019: observe every row, decide only on a complete fresh board.

Synthetic data only. CI PASS is not a real-machine acceptance, says nothing
about real market behaviour, and approves no deployment.

What is checked here:
- The Collector bridge (127.0.0.1:28580, the UI's primary live source) carries
  byte-identical copies of the Gateway's quote, row and availability functions.
- The 100-symbol universe is checked against watchlist_100.json: a missing,
  duplicate, unexpected or unverifiable row is never "99-symbol monitoring".
- The Shadow supervisor mirrors the Gateway's availability verdict, records an
  observation for every cycle (fresh rows counted, stale/unknown/invalid and
  missing rows written down as missing data, contiguous seq), and opens or
  closes no virtual trade while the board is not decision-available.
- The dashboard's own fail-closed code (index.html + card_system.js, run
  unmodified in Node) shows "stopped" and no candidates for every refusal.
- Windows PowerShell 5.1 only: Gateway/Shadow availability parity, the real
  Collector bridge listener, and a 3-hour continuous 100-symbol synthetic run.
"""
import importlib.util
import json
import os
import random
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V10.ps1"
COLLECTOR = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
JST = timezone(timedelta(hours=9))
IDENTITY = "285A.T"
WORKBOOK = "Kioxia_MS2_RSS_Live_Signals.xlsx"
BUY = "買いサイン"
WAIT = "待機"
UNIVERSE = [IDENTITY] + ["SYN%02d.T" % i for i in range(1, 100)]
SHARED_FUNCTIONS = (
    "ConvertFrom-OffsetTimestamp", "Get-MarketSession", "New-QuoteFreshnessVerdict", "Get-QuoteFreshness",
    "Get-RowQuoteFreshness", "Get-BoardRowFreshness", "Get-ExpectedUniverse", "Get-BoardAvailability",
    "Get-AvailabilitySummary",
)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load("v10_shadow_supervisor_operability", "scripts/ai_shadow_supervisor.py")


def _windows_powershell():
    # Production host is Windows PowerShell 5.1; pwsh 7 parses JSON dates
    # differently, so these classes run only on Windows (and must not skip there).
    if os.name != "nt":
        return None
    return shutil.which("powershell")


def _iso(moment):
    return moment.astimezone(JST).isoformat(timespec="seconds")


def _quote(at, *, basis="COLLECTOR_OBSERVED_CHANGE"):
    if at is None:
        return {"source_timestamp": "15:00:00", "source_timestamp_at": None,
                "source_timestamp_basis": "UNOBSERVED_SINCE_START", "source_timestamp_observed_at": None}
    return {"source_timestamp": at.astimezone(JST).strftime("%H:%M:%S"), "source_timestamp_at": _iso(at),
            "source_timestamp_basis": basis, "source_timestamp_observed_at": _iso(at)}


def _row(ticker, quote, **extra):
    row = {"ticker": ticker, "name": "synthetic " + ticker, "price": 100.0, "signal": WAIT, "strategy": "synthetic",
           "data": "LIVE"}
    row.update(quote)
    row.update(extra)
    return row


def write_watchlist(directory, tickers=UNIVERSE):
    stocks = {"synthetic %03d" % i: {"ticker": t, "sector": "synthetic"} for i, t in enumerate(tickers)}
    (Path(directory) / "watchlist_100.json").write_text(json.dumps({"stocks": stocks}), encoding="utf-8")


def board(now, *, stale=(), unknown=(), drop=(), duplicate=None, replace=None, identity_at=None,
          row_extra=None, quote_at=None, declared=None):
    """A synthetic 100-row payload that passes every non-freshness source check."""
    fresh = quote_at or (now - timedelta(seconds=2))
    rows = []
    for ticker in UNIVERSE:
        if ticker in drop:
            continue
        if ticker in stale:
            quote = _quote(now - timedelta(minutes=5))
        elif ticker in unknown:
            quote = _quote(None)
        else:
            quote = _quote(fresh)
        rows.append(_row(ticker, quote, **((row_extra or {}).get(ticker) or {})))
    if duplicate:
        rows.append(_row(duplicate, _quote(fresh)))
    if replace:
        old, new = replace
        rows = [_row(new, _quote(fresh)) if r["ticker"] == old else r for r in rows]
    identity_quote = _quote(identity_at or fresh) if IDENTITY not in unknown else _quote(None)
    if identity_at is not None:
        rows = [dict(r, **_quote(identity_at)) if r["ticker"] == IDENTITY else r for r in rows]
    diag = {"price_source_status": "OK", "source_mode": "MS2_RSS_WORKBOOK", "workbook_name": WORKBOOK,
            "data_conflict": False, "duplicate_collector": False, "duplicate_watcher": False, "collector_count": 1,
            "watcher_count": 1, "stale_reason": "", "symbol": IDENTITY, "current_price": 1000.0,
            "live_values_available": True}
    diag.update(identity_quote)
    return {
        "updated_at": now.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S"),
        "source": "MarketSpeed II RSS / local PC", "source_mode": "MS2_RSS_WORKBOOK", "stale": False,
        "stale_reason": "", "data_conflict": False, "price_source_status": "OK", "live_values_available": True,
        "real_submit_allowed": False, "universe": len(rows) if declared is None else declared,
        "valid": len(rows), "live_price_diagnostics": diag, "all_targets": rows,
    }


def availability_of(payload, now, universe):
    quote = sup.assess_quote_freshness(payload, now=now)
    rows = sup.board_row_freshness(payload, now=now, board_quote_at=quote.get("quote_at"))
    return sup.assess_board_availability(payload, quote, rows, universe)


def _function_text(text, name):
    match = re.search(r"^function " + re.escape(name) + r"\b", text, re.MULTILINE)
    if match is None:
        raise AssertionError("FUNCTION_MISSING " + name)
    end = text.index("\n}\n", match.start())
    return text[match.start():end + 2]


class SharedFunctionCopies(unittest.TestCase):
    """The bridge on 28580 applies the Gateway's gate, not a second version of it."""

    @classmethod
    def setUpClass(cls):
        cls.gateway = GATEWAY.read_text(encoding="utf-8-sig")
        cls.collector = COLLECTOR.read_text(encoding="utf-8-sig")

    def test_collector_copies_are_byte_identical(self):
        for name in SHARED_FUNCTIONS:
            with self.subTest(function=name):
                self.assertEqual(_function_text(self.collector, name), _function_text(self.gateway, name))

    def test_collector_clock_is_explicit_jst(self):
        for text in (self.gateway, self.collector):
            self.assertIn("return [DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(9))",
                          _function_text(text, "Get-JstNow"))

    def test_bridge_job_receives_and_applies_the_gate(self):
        # PS 5.1 puts -InitializationScript on the child command line; the
        # gate functions there made the 28580 job fail to start. They are
        # loaded inside the job from the Collector file instead.
        init = _function_text(self.collector, "Get-WorkbookIdentityInitialization")
        for name in SHARED_FUNCTIONS + ("Get-JstNow",):
            self.assertNotIn('"' + name + '"', init)
        bridge = _function_text(self.collector, "Start-LocalJsonBridge")
        for name in SHARED_FUNCTIONS + ("Get-JstNow",):
            self.assertIn('"' + name + '"', bridge)
        self.assertIn("[Management.Automation.Language.Parser]::ParseFile($GateSource", bridge)
        self.assertIn('throw ("V10_BRIDGE_GATE_FUNCTION_MISSING " + $gateName)', bridge)
        self.assertIn("$WatchlistPath))) $PSCommandPath", self.collector)
        self.assertIn("Get-BoardAvailability -LiveObj $obj", bridge)
        self.assertIn("-Universe (Get-ExpectedUniverse $UniverseDirectory)", bridge)
        self.assertIn("-PreviousRowQuotes $bridgeServed.rows", bridge)
        # Served history moves only after a 200, and the checked text is served.
        ok_branch = bridge[bridge.index('$status = "200 OK"'):]
        self.assertLess(ok_branch.index("$bridgeServed.identity = $bridgeServed.pending.identity"),
                        ok_branch.index("$contentType"))
        self.assertIn("$bodyBytes = $utf8.GetBytes($raw)", bridge)
        self.assertIn("Start-LocalJsonBridge $jsonPath 28580 $script:canonicalWorkbookPath (Split-Path -Parent",
                      self.collector)

    def test_no_order_route_added(self):
        for text in (self.gateway, self.collector):
            self.assertNotIn("RssOrder(", text)


class PythonAvailability(unittest.TestCase):
    """Shadow-side availability on synthetic 100-row boards."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-avail-"))
        write_watchlist(self.tmp)
        self.universe = sup.load_expected_universe(self.tmp)
        self.now = datetime(2026, 10, 19, 10, 0, 5, tzinfo=JST)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _avail(self, payload, universe=None):
        return availability_of(payload, self.now, universe or self.universe)

    def test_watchlist_universe_is_verified(self):
        self.assertIs(self.universe["verified"], True)
        self.assertEqual(self.universe["tickers"], UNIVERSE)

    def test_100_all_fresh_is_available(self):
        got = self._avail(board(self.now))
        self.assertIs(got["decision_available"], True)
        self.assertEqual(got["availability_status"], "AVAILABLE")
        self.assertEqual(got["state_counts"], {"FRESH": 100, "STALE": 0, "UNKNOWN": 0, "INVALID": 0, "MISSING": 0})
        self.assertEqual(got["fresh_coverage_pct"], 100.0)
        self.assertIs(got["real_submit_allowed"], False)

    def test_99_fresh_1_stale_blocks_decisions(self):
        got = self._avail(board(self.now, stale={"SYN07.T"}))
        self.assertIs(got["decision_available"], False)
        self.assertEqual(got["availability_status"], "BLOCKED_ROW_QUOTES")
        self.assertEqual(got["state_counts"]["FRESH"], 99)
        self.assertEqual(got["state_counts"]["STALE"], 1)
        self.assertEqual(got["fresh_coverage_pct"], 99.0)

    def test_90_10_coverage_and_quality_count_are_separate(self):
        stale = set(UNIVERSE[90:])
        got = self._avail(board(self.now, stale=stale))
        self.assertEqual(got["state_counts"]["FRESH"], 90)
        self.assertEqual(got["state_counts"]["STALE"], 10)
        self.assertEqual(got["fresh_coverage_pct"], 90.0)
        # valid>=90 is the Collector's quality count; it grants nothing.
        self.assertIs(got["collector_valid_quality_pass"], True)
        self.assertIs(got["decision_available"], False)

    def test_one_of_100_missing_fails_completeness(self):
        for declared in (None, 100):
            with self.subTest(declared=declared):
                got = self._avail(board(self.now, drop={"SYN42.T"}, declared=declared))
                self.assertIs(got["decision_available"], False)
                self.assertEqual(got["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
                self.assertIn("UNIVERSE_ROW_MISSING", got["reasons"])
                self.assertIn("UNIVERSE_DECLARED_MISMATCH", got["reasons"])
                self.assertEqual(got["missing_count"], 1)
                self.assertEqual(got["missing_sample"], ["SYN42.T"])
                self.assertEqual(got["state_counts"]["MISSING"], 1)
                # 99 present fresh rows are 99% of the universe, not a full board.
                self.assertEqual(got["fresh_coverage_pct"], 99.0)

    def test_duplicate_ticker_fails_closed(self):
        got = self._avail(board(self.now, drop={"SYN11.T"}, duplicate="SYN12.T", declared=100))
        self.assertIs(got["decision_available"], False)
        self.assertIn("ROW_TICKER_DUPLICATE", got["reasons"])
        self.assertIn("UNIVERSE_ROW_MISSING", got["reasons"])
        self.assertEqual(got["state_counts"]["INVALID"], 1)

    def test_unexpected_and_invalid_tickers_fail_closed(self):
        got = self._avail(board(self.now, replace=("SYN13.T", "OTHER.T")))
        self.assertIn("UNIVERSE_ROW_UNEXPECTED", got["reasons"])
        self.assertIn("UNIVERSE_ROW_MISSING", got["reasons"])
        self.assertEqual(got["unexpected_sample"], ["OTHER.T"])
        payload = board(self.now)
        payload["all_targets"][5]["ticker"] = " "
        got = self._avail(payload)
        self.assertIn("ROW_TICKER_MISSING", got["reasons"])
        self.assertIs(got["decision_available"], False)

    def test_unverifiable_universe_never_passes(self):
        cases = {
            "missing": (None, "UNIVERSE_WATCHLIST_MISSING"),
            "invalid": ('{"stocks": []}', "UNIVERSE_WATCHLIST_INVALID"),
            "duplicate": (json.dumps({"stocks": {"a": {"ticker": "X.T"}, "b": {"ticker": "X.T"}}}),
                          "UNIVERSE_WATCHLIST_DUPLICATE"),
            "count": (json.dumps({"stocks": {"a": {"ticker": "X.T"}}}), "UNIVERSE_WATCHLIST_COUNT"),
            "unreadable": ("{not json", "UNIVERSE_WATCHLIST_UNREADABLE"),
        }
        for name, (text, reason) in cases.items():
            with self.subTest(case=name):
                directory = self.tmp / name
                directory.mkdir()
                if text is not None:
                    (directory / "watchlist_100.json").write_text(text, encoding="utf-8")
                universe = sup.load_expected_universe(directory)
                self.assertIs(universe["verified"], False)
                self.assertEqual(universe["reason"], reason)
                got = self._avail(board(self.now), universe)
                self.assertIs(got["decision_available"], False)
                self.assertEqual(got["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
                self.assertIn("UNIVERSE_UNVERIFIED", got["reasons"])
                self.assertIn(reason, got["reasons"])

    def test_identity_stale_blocks_and_startup_unknown_stays_unknown(self):
        got = self._avail(board(self.now, identity_at=self.now - timedelta(minutes=5)))
        self.assertEqual(got["availability_status"], "BLOCKED_IDENTITY_QUOTE")
        self.assertIs(got["identity_quote_fresh"], False)
        got = self._avail(board(self.now, unknown=set(UNIVERSE)))
        self.assertIs(got["decision_available"], False)
        self.assertEqual(got["state_counts"]["UNKNOWN"], 100)
        self.assertEqual(got["fresh_coverage_pct"], 0.0)


class ShadowObservationAndDecision(unittest.TestCase):
    """run_once: observation continues; decisions only on a complete fresh board."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="v10-shadow-obs-"))
        write_watchlist(self.tmp)
        self.data = self.tmp / "ai_shadow"
        self.live = self.tmp / "live_ms2.json"
        self.status = self.tmp / "ai_shadow_status.json"
        self.t0 = datetime(2026, 10, 19, 10, 0, 5, tzinfo=JST)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cycle(self, payload, now):
        self.live.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(self.live, (now.timestamp(), now.timestamp()))
        engine = sup.run_once(self.data, self.live, self.status, now=now)
        return engine, json.loads(self.status.read_text(encoding="utf-8"))

    def _records(self):
        path = self.data / "board_availability.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _events(engine, kind):
        return [e for e in engine["ledger"] if e.get("event_type") == kind]

    def _buy(self, price=512.5):
        return {"signal": BUY, "price": price, "entry_price": price, "stop_price": price - 10}

    def test_all_fresh_board_opens_entry(self):
        engine, status = self._cycle(board(self.t0, row_extra={"SYN03.T": self._buy()}), self.t0)
        self.assertEqual(len(self._events(engine, "virtual_entry")), 1)
        self.assertEqual(status["decision_state"], "DECISION_AVAILABLE")
        self.assertIs(status["board_availability"]["decision_available"], True)
        self.assertIs(status["real_submit_allowed"], False)

    def test_99_fresh_1_stale_observes_but_does_not_decide(self):
        payload = board(self.t0, stale={"SYN50.T"}, row_extra={"SYN03.T": self._buy()})
        engine, status = self._cycle(payload, self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        judgment = self._events(engine, "board_judgment")[-1]
        self.assertIs(judgment["decision_available"], False)
        self.assertIn("ROW_STALE_SOURCE_QUOTE", judgment["decision_block_reasons"])
        # The fresh buy row is still judged and observed, only not acted on.
        row = [j for j in judgment["judgments"] if j["ticker"] == "SYN03.T"][0]
        self.assertEqual(row["row_quote_state"], "FRESH")
        self.assertIs(row["entry_candidate"], False)
        self.assertEqual(status["decision_state"], "DECISION_BLOCKED")
        record = self._records()[-1]
        self.assertEqual(record["state_counts"]["FRESH"], 99)
        self.assertEqual([r["ticker"] for r in record["non_fresh_rows"]], ["SYN50.T"])
        self.assertIs(record["decision_available"], False)

    def test_identity_fresh_but_top5_candidate_stale_is_not_used(self):
        payload = board(self.t0, stale={"SYN02.T"}, row_extra={"SYN02.T": self._buy(654.5)})
        payload["top5"] = [payload["all_targets"][2]]
        engine, _ = self._cycle(payload, self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])

    def test_missing_row_is_recorded_not_dropped(self):
        engine, status = self._cycle(board(self.t0, drop={"SYN42.T"}, declared=100,
                                           row_extra={"SYN03.T": self._buy()}), self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        record = self._records()[-1]
        self.assertEqual(record["missing_tickers"], ["SYN42.T"])
        self.assertEqual(record["availability_status"], "BLOCKED_UNIVERSE_INCOMPLETE")
        self.assertEqual(status["board_availability"]["missing_count"], 1)

    def test_startup_unknown_keeps_unknown(self):
        engine, status = self._cycle(board(self.t0, unknown=set(UNIVERSE), row_extra={"SYN03.T": self._buy()}),
                                     self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        self.assertEqual(status["state"], "PAUSED_FAIL_CLOSED")
        record = self._records()[-1]
        self.assertEqual(record["state_counts"]["UNKNOWN"], 100)
        self.assertIsNone(record["identity_quote_at"])

    def test_thin_row_keeps_observation_and_never_goes_live(self):
        quiet_since = self.t0 - timedelta(minutes=30)
        for step in range(6):
            now = self.t0 + timedelta(seconds=5 * step)
            payload = board(now, row_extra={"SYN99.T": _quote(quiet_since)})
            engine, status = self._cycle(payload, now)
            self.assertEqual(status["decision_state"], "DECISION_BLOCKED")
        records = self._records()
        self.assertEqual(len(records), 6)
        self.assertTrue(all(r["non_fresh_rows"] == [{"ticker": "SYN99.T", "state": "STALE",
                                                       "reasons": ["STALE_SOURCE_QUOTE"]}] for r in records))
        self.assertTrue(all(r["state_counts"]["FRESH"] == 99 for r in records))

    def test_records_are_contiguous_through_blocked_and_failed_cycles(self):
        plan = [board(self.t0), board(self.t0, stale={"SYN05.T"}),
                board(self.t0, identity_at=self.t0 - timedelta(minutes=10)), board(self.t0, drop={"SYN06.T"}),
                board(self.t0)]
        for step, payload in enumerate(plan):
            now = self.t0 + timedelta(seconds=step)
            payload = dict(payload, updated_at=now.strftime("%Y-%m-%d %H:%M:%S"))
            self._cycle(payload, now)
        records = self._records()
        self.assertEqual([r["seq"] for r in records], [1, 2, 3, 4, 5])
        self.assertEqual([r["decision_available"] for r in records], [True, False, False, False, True])
        self.assertTrue(all(r["real_submit_allowed"] is False for r in records))
        self.assertEqual(records[2]["source_checks_pass"], False)
        # A restarted supervisor continues the same sequence.
        self._cycle(board(self.t0 + timedelta(seconds=9)), self.t0 + timedelta(seconds=9))
        self.assertEqual(self._records()[-1]["seq"], 6)

    def test_recovery_uses_only_the_new_quote(self):
        engine, _ = self._cycle(board(self.t0, stale={"SYN03.T"}, row_extra={"SYN03.T": self._buy()}), self.t0)
        self.assertEqual(self._events(engine, "virtual_entry"), [])
        later = self.t0 + timedelta(seconds=10)
        engine, status = self._cycle(board(later, row_extra={"SYN03.T": self._buy(520.0)}), later)
        entries = self._events(engine, "virtual_entry")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["published_price"], 520.0)
        self.assertEqual(entries[0]["source_timestamp_at"], _iso(later - timedelta(seconds=2)))
        self.assertEqual(status["decision_state"], "DECISION_AVAILABLE")

    def test_no_exit_while_board_is_blocked(self):
        engine, _ = self._cycle(board(self.t0, row_extra={"SYN03.T": self._buy()}), self.t0)
        self.assertEqual(len(self._events(engine, "virtual_entry")), 1)
        t1 = self.t0 + timedelta(seconds=5)
        engine, _ = self._cycle(board(t1, stale={"SYN70.T"}), t1)  # SYN03 left the buy set, fresh row
        self.assertEqual(self._events(engine, "virtual_exit"), [])
        t2 = self.t0 + timedelta(seconds=10)
        engine, _ = self._cycle(board(t2), t2)
        self.assertEqual(len(self._events(engine, "virtual_exit")), 1)

    def test_restart_then_time_regression_is_detected_and_recorded(self):
        self._cycle(board(self.t0), self.t0)
        # A new supervisor process: state is reloaded from disk, not memory.
        later = self.t0 + timedelta(seconds=5)
        older = board(later, quote_at=self.t0 - timedelta(seconds=30))
        engine, status = self._cycle(older, later)
        self.assertIn("SOURCE_TIMESTAMP_REGRESSION", status["quote_freshness"]["reasons"])
        self.assertEqual(status["state"], "PAUSED_FAIL_CLOSED")
        record = self._records()[-1]
        self.assertIn("SOURCE_TIMESTAMP_REGRESSION", record["source_reasons"])
        self.assertIs(record["decision_available"], False)


NODE_HARNESS = ROOT / "tests" / "v10_ui_fail_closed_harness.mjs"


def run_ui_cases(cases):
    node = shutil.which("node")
    if node is None:
        return None
    env = dict(os.environ, TZ="UTC")
    proc = subprocess.run([node, str(NODE_HARNESS)], input=json.dumps(cases, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, timeout=60, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        raise AssertionError("UI harness failed: " + proc.stderr.decode("utf-8", errors="replace")[-2000:])
    return json.loads(proc.stdout.decode("utf-8"))


def utc_updated_at():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ui_live_body(top5_ticker="SYN01.T"):
    payload = board(datetime.now(timezone.utc).astimezone(JST))
    payload["updated_at"] = utc_updated_at()  # the harness runs with TZ=UTC
    payload["top5"] = [r for r in payload["all_targets"] if r["ticker"] == top5_ticker]
    # Strict dashboard LIVE gate requires the real Collector's explicit
    # workbook/source/observation evidence; no invented auth token.
    payload["observed_at_offset"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["connection_source"] = "自宅PC・MS2 RSS LIVE"
    payload["live_price_diagnostics"]["workbook_identity_verified"] = True
    payload["live_price_diagnostics"]["real_submit_allowed"] = False
    return payload


def rejection_body(reason, price_status="STALE"):
    return {"status": "stale", "reason": reason, "stale_reason": reason, "price_source_status": price_status,
            "current_price": None, "real_submit_allowed": False, "live_values_available": False,
            "data_conflict": False}


class UiFailClosed(unittest.TestCase):
    """index.html's own decision lines on synthetic refusals (Node, no network)."""

    @classmethod
    def setUpClass(cls):
        if os.name != "nt" and shutil.which("node") is None:
            raise unittest.SkipTest("node not installed; the Windows CI job runs this class")
        live = ui_live_body()
        healthy = {"runtime": {"fail_closed": False}}
        missing_identity = json.loads(json.dumps(live))
        del missing_identity["live_price_diagnostics"]["workbook_identity_verified"]
        outdated = json.loads(json.dumps(live))
        outdated["observed_at_offset"] = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        cases = [
            {"name": "http_200_without_workbook_identity", "bridge_status": 200,
             "bridge_body": json.dumps(missing_identity), "health": healthy},
            {"name": "http_200_with_30s_frozen_observation", "bridge_status": 200,
             "bridge_body": json.dumps(outdated), "health": healthy},
            {"name": "positive_control", "bridge_status": 200, "bridge_body": json.dumps(live), "health": healthy},
            {"name": "row_stale_503", "bridge_status": 503,
             "bridge_body": json.dumps(rejection_body("ROW_QUOTE_NOT_FRESH,ROW_STALE_SOURCE_QUOTE")), "health": healthy},
            {"name": "universe_incomplete_503", "bridge_status": 503,
             "bridge_body": json.dumps(rejection_body("UNIVERSE_ROW_MISSING")), "health": healthy},
            {"name": "identity_stale_503", "bridge_status": 503,
             "bridge_body": json.dumps(rejection_body("STALE_SOURCE_QUOTE")), "health": healthy},
            {"name": "history_unreadable_503", "bridge_status": 503,
             "bridge_body": json.dumps(rejection_body("SERVED_HISTORY_UNREADABLE")), "health": healthy},
            {"name": "source_mismatch_503", "bridge_status": 503,
             "bridge_body": json.dumps(rejection_body("WRONG_SOURCE_WORKBOOK", "PRICE_SOURCE_MISMATCH")),
             "health": healthy},
            # /health fail_closed (e.g. Shadow disagrees) overrides a 200 board.
            {"name": "health_fail_closed_overrides_200", "bridge_status": 200, "bridge_body": json.dumps(live),
             "health": {"runtime": {"fail_closed": True, "price_source_status": "FAIL_CLOSED",
                                    "live_current_price": None}}},
        ]
        cls.result = run_ui_cases(cases)
        if cls.result is None:
            raise AssertionError("node missing on Windows")

    def test_positive_control_is_live(self):
        got = self.result["positive_control"]
        self.assertNotIn("error", got)
        self.assertIs(got["stale"], False, got)
        self.assertEqual(got["xs_len"], 1)

    def test_every_refusal_shows_stopped_with_no_candidates(self):
        for name, got in self.result.items():
            if name == "positive_control":
                continue
            with self.subTest(case=name):
                self.assertNotIn("error", got)
                self.assertIs(got["stale"], True)
                self.assertEqual(got["xs_len"], 0)
                self.assertEqual(got["health_text"], "データ停止・売買禁止")


IMPORT_FUNCTIONS = r"""
function Import-Functions([string]$Path, [string[]]$Names) {
    $t = $null; $e = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile($Path, [ref]$t, [ref]$e)
    if ($e.Count) { throw "PARSE_FAILED $Path" }
    foreach ($name in $Names) {
        $defs = @($ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name }, $true))
        if ($defs.Count -ne 1) { throw "HELPER_MISSING $name" }
        . ([scriptblock]::Create($defs[0].Extent.Text))
        Set-Item -Path ("function:global:" + $name) -Value (Get-Item ("function:" + $name)).ScriptBlock
    }
}
"""

GATE_FUNCTIONS = "'Get-JstNow'," + ",".join("'%s'" % n for n in SHARED_FUNCTIONS)

PARITY_HARNESS = r"""
param([string]$Gateway, [string]$Cases)
$ErrorActionPreference = 'Stop'
""" + IMPORT_FUNCTIONS + r"""
Import-Functions $Gateway @(""" + GATE_FUNCTIONS + r""")
$fixture = [IO.File]::ReadAllText($Cases, [Text.Encoding]::UTF8) | ConvertFrom-Json
$out = [ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; cases = [ordered]@{} }
foreach ($case in $fixture.cases) {
    $now = [DateTimeOffset]::Parse($case.now, [Globalization.CultureInfo]::InvariantCulture)
    $live = [IO.File]::ReadAllText($case.payload_path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $universe = Get-ExpectedUniverse $case.universe_dir
    $q = Get-QuoteFreshness -LiveObj $live -Now $now
    $rows = Get-BoardRowFreshness -LiveObj $live -Now $now -BoardQuoteAt $q.quote_at
    $a = Get-BoardAvailability -LiveObj $live -QuoteFreshness $q -RowFreshness $rows -Universe $universe
    $out.cases[$case.name] = [ordered]@{ universe = $universe; availability = $a }
}
$out | ConvertTo-Json -Depth 8 -Compress
"""


def _run_powershell(exe, script_text, args, timeout=600, env=None):
    tmp = Path(tempfile.mkdtemp(prefix="v10-oper-ps-"))
    try:
        script = tmp / "harness.ps1"
        script.write_text(script_text, encoding="utf-8-sig")
        proc = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-File", str(script), *args], capture_output=True, timeout=timeout, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise AssertionError("PowerShell harness failed: " + stdout[-2000:] +
                             proc.stderr.decode("utf-8", errors="replace")[-2000:])
    return json.loads(stdout.splitlines()[-1].lstrip("﻿"))


class GatewayShadowAvailabilityParity(unittest.TestCase):
    """Get-ExpectedUniverse / Get-BoardAvailability (PS 5.1) == Shadow (Python)."""

    @classmethod
    def setUpClass(cls):
        exe = _windows_powershell()
        if exe is None:
            raise unittest.SkipTest("Windows PowerShell 5.1 not available; the Windows CI job runs this class")
        cls.tmp = Path(tempfile.mkdtemp(prefix="v10-avail-parity-"))
        now = datetime(2026, 10, 19, 10, 0, 5, tzinfo=JST)
        good = cls.tmp / "good"
        good.mkdir()
        write_watchlist(good)
        dup = cls.tmp / "dup"
        dup.mkdir()
        write_watchlist(dup, UNIVERSE[:99] + [UNIVERSE[0]])
        short = cls.tmp / "short"
        short.mkdir()
        write_watchlist(short, UNIVERSE[:99])
        missing = cls.tmp / "missing"
        missing.mkdir()
        payloads = {
            "all_fresh": (board(now), good),
            "one_stale": (board(now, stale={"SYN07.T"}), good),
            "ninety_ten": (board(now, stale=set(UNIVERSE[90:])), good),
            "one_missing": (board(now, drop={"SYN42.T"}, declared=100), good),
            "one_missing_declared_99": (board(now, drop={"SYN42.T"}), good),
            "duplicate": (board(now, drop={"SYN11.T"}, duplicate="SYN12.T", declared=100), good),
            "unexpected": (board(now, replace=("SYN13.T", "OTHER.T")), good),
            "identity_stale": (board(now, identity_at=now - timedelta(minutes=5)), good),
            "startup_unknown": (board(now, unknown=set(UNIVERSE)), good),
            "watchlist_duplicate": (board(now), dup),
            "watchlist_short": (board(now), short),
            "watchlist_missing": (board(now), missing),
            # Fresh-rows-only use (P0-V10-INTEGRATION-AND-LIVE-START-20261020).
            "partial_one_stale": (dict(board(now, stale={"SYN07.T"}), aggregate_basis="FRESH_ROWS_ONLY"), good),
            "partial_five_stale": (dict(board(now, stale=set(UNIVERSE[95:])), aggregate_basis="FRESH_ROWS_ONLY"), good),
            "partial_six_stale": (dict(board(now, stale=set(UNIVERSE[94:])), aggregate_basis="FRESH_ROWS_ONLY"), good),
            "partial_undeclared": (board(now, stale={"SYN07.T"}), good),
            "partial_identity_stale": (dict(board(now, identity_at=now - timedelta(minutes=5)),
                                            aggregate_basis="FRESH_ROWS_ONLY"), good),
            "partial_missing_row": (dict(board(now, drop={"SYN42.T"}, declared=100), aggregate_basis="FRESH_ROWS_ONLY"),
                                    good),
        }
        cases = []
        cls.expected = {}
        for name, (payload, directory) in payloads.items():
            path = cls.tmp / (name + ".json")
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cases.append({"name": name, "now": _iso(now), "payload_path": str(path), "universe_dir": str(directory)})
            cls.expected[name] = availability_of(payload, now, sup.load_expected_universe(directory))
        fixture = cls.tmp / "cases.json"
        fixture.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
        cls.result = _run_powershell(exe, PARITY_HARNESS, ["-Gateway", str(GATEWAY), "-Cases", str(fixture)])

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_runs_on_windows_powershell_5(self):
        self.assertEqual(self.result["ps_major"], 5)

    def test_every_case_matches(self):
        keys = ("decision_available", "availability_status", "reasons", "identity_quote_fresh", "universe_verified",
                "universe_expected_count", "universe_declared", "row_count", "state_counts", "fresh_coverage_pct",
                "missing_count", "missing_sample", "unexpected_count", "unexpected_sample", "collector_valid_count",
                "collector_valid_quality_pass", "partial_rows", "partial_reasons", "partial_min_fresh_pct",
                "order_allowed", "real_submit_allowed")
        self.assertEqual(set(self.result["cases"]), set(self.expected))
        for name, py in self.expected.items():
            with self.subTest(case=name):
                ps = self.result["cases"][name]["availability"]
                for key in keys:
                    got = ps[key]
                    if key in ("reasons", "missing_sample", "unexpected_sample", "partial_reasons"):
                        got = list(got or [])
                    self.assertEqual(got, py[key], key)
        self.assertIs(self.expected["all_fresh"]["decision_available"], True)
        self.assertIs(self.expected["one_missing"]["decision_available"], False)
        self.assertEqual(self.expected["partial_one_stale"]["availability_status"], "AVAILABLE_PARTIAL")
        self.assertEqual(self.expected["partial_five_stale"]["availability_status"], "AVAILABLE_PARTIAL")
        for blocked in ("partial_six_stale", "partial_undeclared", "partial_identity_stale", "partial_missing_row"):
            self.assertIs(self.expected[blocked]["decision_available"], False, blocked)


BRIDGE_HARNESS = r"""
param([string]$JsonFile, [int]$Port, [string]$RuntimeDir, [string]$StopFile)
$ErrorActionPreference = 'Stop'
""" + IMPORT_FUNCTIONS + r"""
# The Collector path comes from the environment so this harness's own
# command line does not look like a second Collector process.
$collector = $env:V10_TEST_COLLECTOR_SOURCE
Import-Functions $collector @('Get-NormalizedLocalWorkbookPath','Get-CollectorFileIdentityType','Test-SameCanonicalWorkbookFile','Get-WorkbookPublicationId','Get-PublishedWorkbookGate','Get-WorkbookIdentityInitialization','Start-LocalJsonBridge')
# The gate functions are not imported here: the job must load them itself.
$canonical = Join-Path $RuntimeDir 'Kioxia_MS2_RSS_Live_Signals.xlsx'
$job = Start-LocalJsonBridge $JsonFile $Port $canonical $RuntimeDir $collector
try {
    $until = (Get-Date).AddMinutes(10)
    while (-not (Test-Path -LiteralPath $StopFile) -and (Get-Date) -lt $until) {
        if ($job.State -ne 'Running') {
            $detail = (Receive-Job $job 2>&1 | Out-String) + ' ' + ($job.ChildJobs[0].JobStateInfo.Reason | Out-String)
            throw ('BRIDGE_JOB_' + $job.State + ': ' + $detail)
        }
        Start-Sleep -Milliseconds 200
    }
} finally {
    # The job blocks in AcceptTcpClient; one connection lets it see the stop.
    try { $c = [Net.Sockets.TcpClient]::new('127.0.0.1', $Port); $c.Close() } catch {}
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}
"""

ENV_HARNESS = r"""
param([string]$Gateway, [string]$RuntimeDir)
$ErrorActionPreference = 'Stop'
""" + IMPORT_FUNCTIONS + r"""
Import-Functions $Gateway @('Get-NormalizedLocalWorkbookPath','Get-WorkbookPublicationId')
$canonical = Join-Path $RuntimeDir 'Kioxia_MS2_RSS_Live_Signals.xlsx'
[ordered]@{
    ps_major = $PSVersionTable.PSVersion.Major
    utc_offset_seconds = [int][TimeZoneInfo]::Local.GetUtcOffset([DateTime]::UtcNow).TotalSeconds
    workbook_identity_id = (Get-WorkbookPublicationId $canonical)
} | ConvertTo-Json -Compress
"""


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_get(port, path):
    request = (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n").encode("ascii")
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.settimeout(20)
        sock.sendall(request)
        raw = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            raw.extend(chunk)
    head, _, body = bytes(raw).partition(b"\r\n\r\n")
    return head.split(b"\r\n", 1)[0].decode("ascii", errors="replace"), body


@unittest.skipUnless(os.name == "nt", "Collector bridge job needs Windows PowerShell 5.1; the Windows CI job runs this class")
class CollectorBridgeHttp(unittest.TestCase):
    """The real Start-LocalJsonBridge job (28580 code path) on a free port."""

    @classmethod
    def setUpClass(cls):
        cls.exe = _windows_powershell()
        if cls.exe is None:
            raise AssertionError("powershell.exe missing on Windows")
        cls.processes = []
        cls.tmp = tempfile.TemporaryDirectory(prefix="v10-bridge-http-")
        cls.runtime = Path(cls.tmp.name) / "runtime"
        cls.runtime.mkdir()
        write_watchlist(cls.runtime)
        env = _run_powershell(cls.exe, ENV_HARNESS, ["-Gateway", str(GATEWAY), "-RuntimeDir", str(cls.runtime)])
        assert env["ps_major"] == 5, env
        cls.utc_offset = timedelta(seconds=int(env["utc_offset_seconds"]))
        cls.workbook_id = env["workbook_identity_id"]
        fake_dir = Path(cls.tmp.name) / "fake-process"
        fake_dir.mkdir()
        fake = fake_dir / "MS2_RSS_100_Collector.ps1"
        fake.write_text("Start-Sleep -Seconds 900\n", encoding="utf-8")
        cls.processes.append(subprocess.Popen(
            [cls.exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(fake)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        cls.live = cls.runtime / "live_ms2.json"
        cls.stop = Path(cls.tmp.name) / "stop.flag"
        cls.port, cls.bridge = cls._start_bridge(cls.live)
        # A second bridge that is only ever sent refused boards. It has no
        # served history, so an old quote is reported as stale there, not as
        # a regression against what the first bridge already served.
        cls.cold_live = cls.runtime / "cold" / "live_ms2.json"
        cls.cold_live.parent.mkdir()
        cls.cold_port, cls.cold_bridge = cls._start_bridge(cls.cold_live)
        deadline = time.monotonic() + 30
        while True:
            status, written, body = cls._serve(cls._payload())
            if "200" in status or time.monotonic() > deadline:
                break
            time.sleep(0.5)
        cls.warmup = (status, body)

    @classmethod
    def _start_bridge(cls, live):
        port = _free_port()
        script = Path(cls.tmp.name) / "bridge_harness.ps1"
        script.write_text(BRIDGE_HARNESS, encoding="utf-8-sig")
        child_env = dict(os.environ, V10_TEST_COLLECTOR_SOURCE=str(COLLECTOR))
        bridge = subprocess.Popen(
            [cls.exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
             "-JsonFile", str(live), "-Port", str(port), "-RuntimeDir", str(cls.runtime),
             "-StopFile", str(cls.stop)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_env)
        until = time.monotonic() + 60
        while time.monotonic() < until:
            if bridge.poll() is not None:
                raise AssertionError("bridge harness exited: " + bridge.stderr.read().decode("utf-8", "replace")[-2000:])
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("bridge failed to bind")
        return port, bridge

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "stop"):
            cls.stop.write_text("stop", encoding="utf-8")
        for bridge in (getattr(cls, "bridge", None), getattr(cls, "cold_bridge", None)):
            if bridge is None:
                continue
            try:
                bridge.wait(timeout=30)
            except Exception:
                bridge.kill()
        for process in getattr(cls, "processes", []):
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                pass
        if hasattr(cls, "tmp"):
            cls.tmp.cleanup()

    @classmethod
    def _payload(cls, **kwargs):
        now = datetime.now(timezone.utc).astimezone(JST)
        payload = board(now, **kwargs)
        local_now = datetime.now(timezone.utc).replace(tzinfo=None) + cls.utc_offset
        payload["updated_at"] = local_now.strftime("%Y-%m-%d %H:%M:%S")
        diag = payload["live_price_diagnostics"]
        diag.update({"workbook_identity_verified": True, "workbook_full_name": WORKBOOK,
                     "workbook_identity_id": cls.workbook_id})
        payload["top5"] = [r for r in payload["all_targets"] if r.get("signal") == BUY][:5]
        return payload

    @classmethod
    def _serve(cls, payload, cold=False):
        live, port = (cls.cold_live, cls.cold_port) if cold else (cls.live, cls.port)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        tmp = live.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, live)
        status, body = _http_get(port, "/live_ms2.json")
        return status, data, body

    def _rejected(self, status, body, *codes, hidden=()):
        self.assertIn("503", status, body[:1500])
        verdict = json.loads(body.decode("utf-8-sig"))
        reasons = str(verdict.get("stale_reason", "")).split(",")
        for code in codes:
            self.assertIn(code, reasons)
        for unrelated in ("COLLECTOR_PROCESS_UNVERIFIED", "DUPLICATE_COLLECTOR", "WRONG_SOURCE_WORKBOOK",
                          "CACHED_OR_SAMPLE_PAYLOAD", "STALE_OR_MISSING_TIMESTAMP"):
            self.assertNotIn(unrelated, reasons)
        self.assertIs(verdict["real_submit_allowed"], False)
        self.assertIsNone(verdict["current_price"])
        self.assertNotEqual(verdict["price_source_status"], "OK")
        for key in ("all_targets", "top5", "hold_top5", "kioxia", "market_state"):
            self.assertNotIn(key, verdict)
        text = body.decode("utf-8-sig")
        for needle in hidden:
            self.assertNotIn(needle, text)
        return verdict

    def test_00_harness_reaches_the_gate(self):
        status, body = self.warmup
        self.assertIn("200", status, body[:2000])

    def test_all_fresh_complete_board_is_served_byte_for_byte(self):
        status, written, body = self._serve(self._payload())
        self.assertIn("200 OK", status, body[:1500])
        self.assertEqual(body, written)

    def test_one_stale_row_refuses_the_board(self):
        extra = {"SYN03.T": {"signal": BUY, "price": 777.25}}
        status, _, body = self._serve(self._payload(stale={"SYN03.T"}, row_extra=extra), cold=True)
        verdict = self._rejected(status, body, "ROW_QUOTE_NOT_FRESH", "ROW_STALE_SOURCE_QUOTE", hidden=("777.25", BUY))
        self.assertEqual(verdict["availability"]["state_counts"]["FRESH"], 99)
        self.assertEqual(verdict["availability"]["availability_status"], "BLOCKED_ROW_QUOTES")

    def test_missing_row_refuses_the_board(self):
        status, _, body = self._serve(self._payload(drop={"SYN42.T"}, declared=100))
        verdict = self._rejected(status, body, "UNIVERSE_ROW_MISSING")
        self.assertEqual(verdict["availability"]["missing_sample"], ["SYN42.T"])

    def test_duplicate_row_refuses_the_board(self):
        status, _, body = self._serve(self._payload(drop={"SYN11.T"}, duplicate="SYN12.T", declared=100))
        self._rejected(status, body, "ROW_TICKER_DUPLICATE")

    def test_identity_stale_refuses_the_board(self):
        now = datetime.now(timezone.utc).astimezone(JST)
        status, _, body = self._serve(self._payload(identity_at=now - timedelta(minutes=5)), cold=True)
        self._rejected(status, body, "STALE_SOURCE_QUOTE", "IDENTITY_QUOTE_NOT_FRESH")

    def test_regression_after_a_served_board_is_refused(self):
        status, written, body = self._serve(self._payload())
        self.assertIn("200 OK", status, body[:1500])
        served = datetime.fromisoformat(json.loads(written)["all_targets"][1]["source_timestamp_at"])
        status, _, body = self._serve(self._payload(quote_at=served - timedelta(seconds=20)))
        self._rejected(status, body, "SOURCE_TIMESTAMP_REGRESSION")

    def test_recovery_serves_the_new_bytes_only(self):
        status, _, _ = self._serve(self._payload(stale={"SYN09.T"}))
        self.assertIn("503", status)
        status, written, body = self._serve(self._payload())
        self.assertIn("200 OK", status, body[:1500])
        self.assertEqual(body, written)


SIM_HARNESS = r"""
param([string]$Gateway, [string]$Collector, [string]$PlanPath, [string]$Output, [string]$UniverseDir)
$ErrorActionPreference = 'Stop'
""" + IMPORT_FUNCTIONS + r"""
Import-Functions $Gateway @(""" + GATE_FUNCTIONS + r""")
# Collector quote dating, the real functions.
Import-Functions $Collector @('Update-QuoteObservation','Get-RowQuoteObservation')
$universe = Get-ExpectedUniverse $UniverseDir
if (-not $universe.verified) { throw 'SIM_UNIVERSE_UNVERIFIED' }
$inv = [Globalization.CultureInfo]::InvariantCulture
$table = @{}
$servedIdentity = $null
$servedRows = @{}
$lastRows = $null
$lastWrite = $null
$writer = New-Object IO.StreamWriter($Output, $false, (New-Object Text.UTF8Encoding($false)))
$started = Get-Date
$cycles = 0
try {
    foreach ($line in [IO.File]::ReadLines($PlanPath)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $step = $line | ConvertFrom-Json
        $now = [DateTimeOffset]::ParseExact($step.now, 'yyyy-MM-ddTHH:mm:sszzz', $inv)
        if ($step.collector_writes -eq $true) {
            $rows = New-Object System.Collections.Generic.List[object]
            $absent = @($step.absent)
            for ($i = 0; $i -lt $universe.tickers.Count; $i++) {
                if ($absent -contains $i) { continue }  # no price: the Collector leaves the row out
                $ticker = $universe.tickers[$i]
                $obs = Get-RowQuoteObservation $table $ticker ([string]$step.times[$i]) $now
                [void]$rows.Add([pscustomobject]@{
                    ticker = $ticker
                    source_timestamp = $obs.source_time
                    source_timestamp_at = $obs.source_timestamp_at
                    source_timestamp_basis = $obs.basis
                    source_timestamp_observed_at = $obs.observed_at
                })
            }
            $lastRows = $rows.ToArray()
            $lastWrite = $now
        }
        if ($step.com_fail -eq $true) {
            # The Collector could not read Excel: it publishes no rows.
            $lastRows = @()
            $lastWrite = $now
        }
        $cycles++
        $identityRow = @($lastRows | Where-Object { $_.ticker -ceq '285A.T' })[0]
        $live = [pscustomobject]@{
            universe = 100
            valid = 100
            all_targets = $lastRows
            live_price_diagnostics = [pscustomobject]@{
                source_timestamp = $identityRow.source_timestamp
                source_timestamp_at = $identityRow.source_timestamp_at
                source_timestamp_basis = $identityRow.source_timestamp_basis
                source_timestamp_observed_at = $identityRow.source_timestamp_observed_at
            }
        }
        $writerAge = ($now - $lastWrite).TotalSeconds
        $q = Get-QuoteFreshness -LiveObj $live -Now $now -PreviousQuoteAt $servedIdentity
        $rowVerdict = Get-BoardRowFreshness -LiveObj $live -Now $now -BoardQuoteAt $q.quote_at -PreviousRowQuotes $servedRows
        $a = Get-BoardAvailability -LiveObj $live -QuoteFreshness $q -RowFreshness $rowVerdict -Universe $universe
        $reasons = New-Object System.Collections.Generic.List[string]
        foreach ($r in @($a.reasons)) { [void]$reasons.Add([string]$r) }
        if ($writerAge -gt 60) { [void]$reasons.Add('STALE_OR_MISSING_TIMESTAMP') }
        if ($step.com_fail -eq $true) { [void]$reasons.Add('EXCEL_COM_BUSY') }
        $status = $(if ($reasons.Count -eq 0) { 200 } else { 503 })
        if ($status -eq 200) {
            $servedIdentity = $q.quote_at
            foreach ($k in @($rowVerdict.accepted_quote_at.Keys)) { $servedRows[$k] = $rowVerdict.accepted_quote_at[$k] }
        }
        $compactRows = @($lastRows | ForEach-Object { [ordered]@{ t = $_.ticker; s = $_.source_timestamp; at = $_.source_timestamp_at; b = $_.source_timestamp_basis; o = $_.source_timestamp_observed_at } })
        $writer.WriteLine(([ordered]@{
            now = $now.ToString('yyyy-MM-ddTHH:mm:sszzz', $inv)
            written_at = $lastWrite.ToString('yyyy-MM-ddTHH:mm:sszzz', $inv)
            status = $status
            reasons = $reasons.ToArray()
            decision_available = $a.decision_available
            state_counts = $a.state_counts
            fresh_coverage_pct = $a.fresh_coverage_pct
            rows = $compactRows
        } | ConvertTo-Json -Depth 5 -Compress))
    }
} finally {
    $writer.Dispose()
}
[ordered]@{ ps_major = $PSVersionTable.PSVersion.Major; cycles = $cycles; seconds = [Math]::Round(((Get-Date) - $started).TotalSeconds, 1) } | ConvertTo-Json -Compress
"""

SIM_START = datetime(2026, 10, 19, 8, 58, 0, tzinfo=JST)  # Monday, before the open
SIM_STEP_SECONDS = 10
SIM_HOURS = 3
SIM_STALL = (datetime(2026, 10, 19, 10, 30, 0, tzinfo=JST), datetime(2026, 10, 19, 10, 32, 0, tzinfo=JST))
SIM_SHADOW_EVERY = 3  # Shadow cycle every 30 synthetic seconds (ledger replay cost)


SIM_PROFILES = {
    # name: (liquid tickers at 0.95, medium at 0.30, thin at 0.02 trade probability per step)
    "all_liquid": (100, 0, 0),
    "liquid_plus_7_medium": (93, 7, 0),
    "mixed_with_3_thin": (90, 7, 3),
    # Shaped after the aggregate pattern seen on 2026-10-19 (not market data):
    # 99 of 100 symbols ever priced, the identity untraded until 09:06, a
    # 16-second all-row freeze and a 30-second Excel COM failure.
    "market_like_99_of_100": (80, 15, 4),
}

# Extra events per profile. "absent": watchlist indices that never get a
# price (left out of the board, named in missing_rows). Times are JST clock.
SIM_SCENARIOS = {
    "market_like_99_of_100": {
        "absent": [99],
        "identity_first_trade": "09:06:10",
        "freeze": ("10:04:00", "10:04:16"),
        "com_fail": ("09:23:00", "09:23:30"),
    },
}


def simulation_plan(profile, seed=20261019):
    """Last-trade times (MS2 現在値詳細時刻) per ticker per step, synthetic.

    Liquid tickers trade in almost every 10-second step, medium ones in about
    a third of steps, thin ones rarely. Nothing trades before 09:00 or in the
    11:30-12:30 break. The Collector stops writing for two minutes at 10:30.
    """
    liquid, medium, _ = SIM_PROFILES[profile]
    scenario = SIM_SCENARIOS.get(profile, {})
    absent = set(scenario.get("absent", []))
    rng = random.Random(seed)
    liquidity = {}
    for index, ticker in enumerate(UNIVERSE):
        liquidity[ticker] = 0.95 if index < liquid else (0.30 if index < liquid + medium else 0.02)
        if index in absent:
            liquidity[ticker] = 0.0
    last = {t: "15:00:00" for t in UNIVERSE}  # previous session's close, carried at start
    steps = []
    total = SIM_HOURS * 3600 // SIM_STEP_SECONDS
    for n in range(total):
        now = SIM_START + timedelta(seconds=n * SIM_STEP_SECONDS)
        clock = now.strftime("%H:%M:%S")
        trading = "09:00:00" <= clock <= "11:30:00" or "12:30:00" <= clock <= "15:30:00"
        freeze = scenario.get("freeze")
        if freeze and freeze[0] <= clock < freeze[1]:
            trading = False
        if trading:
            for ticker in UNIVERSE:
                if ticker == IDENTITY and clock < scenario.get("identity_first_trade", "00:00:00"):
                    continue
                if rng.random() < liquidity[ticker]:
                    traded = now - timedelta(seconds=rng.randint(0, SIM_STEP_SECONDS - 1))
                    last[ticker] = traded.strftime("%H:%M:%S")
        writes = not (SIM_STALL[0] <= now < SIM_STALL[1])
        step = {"now": _iso(now), "collector_writes": writes, "times": [last[t] for t in UNIVERSE]}
        if absent:
            step["absent"] = sorted(absent)
        com_fail = scenario.get("com_fail")
        if com_fail and com_fail[0] <= clock < com_fail[1]:
            step["com_fail"] = True
        steps.append(step)
    return steps


def _transitions(values):
    return sum(1 for a, b in zip(values, values[1:]) if a != b)


@unittest.skipUnless(os.name == "nt", "Continuous synthetic run needs Windows PowerShell 5.1; the Windows CI job runs this class")
class ContinuousSynthetic100(unittest.TestCase):
    """3 synthetic hours, 100 symbols, 10-second steps, three liquidity profiles.

    Synthetic, not market results. The Collector's real quote dating
    (Get-RowQuoteObservation) and the Gateway's real gate functions run in
    Windows PowerShell 5.1; the Shadow supervisor runs on the same output.
    """

    @classmethod
    def setUpClass(cls):
        exe = _windows_powershell()
        if exe is None:
            raise AssertionError("powershell.exe missing on Windows")
        cls.tmp = Path(tempfile.mkdtemp(prefix="v10-continuous-"))
        cls.runs = {}
        for profile in SIM_PROFILES:
            cls.runs[profile] = cls._run_profile(exe, profile)
        cls.metrics = {"label": "SYNTHETIC_ONLY_NOT_MARKET_RESULTS",
                       "profiles": {name: run["metrics"] for name, run in cls.runs.items()}}
        print("\nV10_CONTINUOUS_SYNTHETIC_METRICS " + json.dumps(cls.metrics, ensure_ascii=False, sort_keys=True))
        target = os.environ.get("V10_SYNTHETIC_METRICS")
        if target:
            Path(target).write_text(json.dumps(cls.metrics, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmp"):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _run_profile(cls, exe, profile):
        work = cls.tmp / profile
        work.mkdir()
        write_watchlist(work)
        steps = simulation_plan(profile)
        plan = work / "plan.jsonl"
        plan.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")
        out = work / "gateway.jsonl"
        ps = _run_powershell(exe, SIM_HARNESS, ["-Gateway", str(GATEWAY), "-Collector", str(COLLECTOR),
                                                "-PlanPath", str(plan), "-Output", str(out),
                                                "-UniverseDir", str(work)], timeout=1800)
        gateway = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
        data = work / "ai_shadow"
        live = work / "live_ms2.json"
        status_path = work / "ai_shadow_status.json"
        shadow = []
        started = time.monotonic()
        for index, cycle in enumerate(gateway):
            if index % SIM_SHADOW_EVERY:
                continue
            now = datetime.fromisoformat(cycle["now"])
            written = datetime.fromisoformat(cycle["written_at"])
            rows = [{"ticker": r["t"], "signal": WAIT, "strategy": "synthetic", "price": 100.0, "data": "LIVE",
                     "source_timestamp": r["s"], "source_timestamp_at": r["at"], "source_timestamp_basis": r["b"],
                     "source_timestamp_observed_at": r["o"]} for r in cycle["rows"]]
            step = steps[index]
            payload = board(written)
            payload["all_targets"] = rows
            payload["universe"] = 100
            payload["valid"] = len(rows)
            identity = next((r for r in rows if r["ticker"] == IDENTITY), None)
            if identity is not None:
                payload["live_price_diagnostics"].update({k: identity[k] for k in sup.ROW_QUOTE_FIELDS})
            if step.get("absent"):
                payload["missing_rows"] = [{"ticker": UNIVERSE[i], "reason": "PRICE_MISSING", "sheet_code_matches": True,
                                            "source_time_text": None, "price": None} for i in step["absent"]]
            if step.get("com_fail"):
                for target in (payload, payload["live_price_diagnostics"]):
                    target.update({"price_source_status": "EXCEL_COM_BUSY", "stale_reason": "EXCEL_COM_BUSY",
                                   "live_values_available": False, "data_conflict": True})
                payload["stale"] = True
            live.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.utime(live, (written.timestamp(), written.timestamp()))
            sup.run_once(data, live, status_path, now=now)
            snap = json.loads(status_path.read_text(encoding="utf-8"))
            shadow.append({"index": index, "state": snap["state"], "decision_state": snap["decision_state"],
                           "decision_available": snap["board_availability"]["decision_available"]})
        shadow_seconds = round(time.monotonic() - started, 1)
        records = [json.loads(line) for line in (data / "board_availability.jsonl").read_text(
            encoding="utf-8").splitlines() if line.strip()]
        ledger = data / "ledger.jsonl"
        ledger_lines = len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.exists() else 0
        run = {"ps": ps, "gateway": gateway, "shadow": shadow, "records": records, "steps": steps}
        run["metrics"] = cls._metrics(run, profile, shadow_seconds, ledger_lines)
        return run

    @staticmethod
    def _metrics(run, profile, shadow_seconds, ledger_lines):
        gateway, shadow, records, steps = run["gateway"], run["shadow"], run["records"], run["steps"]
        total = len(gateway)
        ok = sum(1 for c in gateway if c["status"] == 200)
        counts = {k: sum(c["state_counts"][k] for c in gateway) for k in ("FRESH", "STALE", "UNKNOWN", "INVALID", "MISSING")}
        clock = lambda c: c["now"][11:19]
        market = [c for c in gateway if "09:00:00" <= clock(c) <= "11:30:00" or "12:30:00" <= clock(c) <= "15:30:00"]
        market_ok = sum(1 for c in market if c["status"] == 200)
        reason_cycles = {}
        for c in gateway:
            for r in c["reasons"]:
                reason_cycles[r] = reason_cycles.get(r, 0) + 1
        seqs = [r["seq"] for r in records]
        gaps = sum(1 for a, b in zip(seqs, seqs[1:]) if b != a + 1)
        agree = sum(1 for s in shadow if s["decision_available"] == gateway[s["index"]]["decision_available"])
        in_market = lambda at: "09:00:00" <= at[11:19] <= "11:30:00" or "12:30:00" <= at[11:19] <= "15:30:00"
        market_records = [r for r in records if in_market(r["at"])]
        pct = lambda part, whole: round(100.0 * part / whole, 1) if whole else None
        statuses = [c["status"] for c in gateway]
        recoveries = sum(1 for a, b in zip(statuses, statuses[1:]) if a == 503 and b == 200)
        written = sum(1 for s in steps if s["collector_writes"])
        liquid, medium, thin = SIM_PROFILES[profile]
        return {
            "synthetic_window_jst": [gateway[0]["now"], gateway[-1]["now"]],
            "step_seconds": SIM_STEP_SECONDS,
            "liquidity_model": {"liquid_p0.95": liquid, "medium_p0.30": medium, "thin_p0.02": thin},
            "cycles": total,
            "http_200": ok,
            "http_503": total - ok,
            "http_200_ratio_pct": round(100.0 * ok / total, 1),
            "decision_available_time_pct_all": round(100.0 * ok / total, 1),
            "market_hours_cycles": len(market),
            "decision_available_time_pct_market_hours": round(100.0 * market_ok / len(market), 1) if market else None,
            "row_state_totals": counts,
            "mean_fresh_rows_per_cycle": round(counts["FRESH"] / total, 2),
            "reason_cycles": dict(sorted(reason_cycles.items(), key=lambda kv: -kv[1])[:12]),
            "collector_write_cycles": written,
            "collector_stall_cycles": total - written,
            "collector_dating_cycles_processed": run["ps"]["cycles"],
            "powershell_seconds": run["ps"]["seconds"],
            "shadow_cycles": len(shadow),
            "shadow_seconds": shadow_seconds,
            "shadow_state_transitions": _transitions([s["state"] for s in shadow]),
            "shadow_decision_transitions": _transitions([s["decision_state"] for s in shadow]),
            "shadow_states": {k: sum(1 for s in shadow if s["state"] == k) for k in sorted({s["state"] for s in shadow})},
            "shadow_decision_states": {k: sum(1 for s in shadow if s["decision_state"] == k)
                                       for k in sorted({s["decision_state"] for s in shadow})},
            "shadow_gateway_decision_agreement_pct": round(100.0 * agree / len(shadow), 1) if shadow else None,
            "observation_records": len(records),
            "observation_seq_gaps": gaps,
            "observation_pass_pct": pct(sum(1 for r in records if r.get("observation_pass") is True), len(records)),
            "decision_pass_pct": pct(sum(1 for r in records if r.get("decision_pass") is True), len(records)),
            "decision_pass_pct_market_hours": pct(sum(1 for r in market_records if r.get("decision_pass") is True),
                                                  len(market_records)),
            "shadow_fresh_only_decidable_pct_market_hours": pct(
                sum(1 for r in market_records if r["shadow_fresh_only"]["would_be_decidable"] is True), len(market_records)),
            "missing_rate_pct": pct(counts["MISSING"], 100 * total),
            "not_fresh_rate_pct": pct(100 * total - counts["FRESH"], 100 * total),
            "recovery_count_503_to_200": recoveries,
            "ledger_lines": ledger_lines,
            "real_submit_allowed": False,
        }

    def test_runs_on_windows_powershell_5_for_three_synthetic_hours(self):
        for profile, run in self.runs.items():
            with self.subTest(profile=profile):
                self.assertEqual(run["ps"]["ps_major"], 5)
                self.assertEqual(run["ps"]["cycles"], SIM_HOURS * 3600 // SIM_STEP_SECONDS)
                self.assertEqual(len(run["gateway"]), run["ps"]["cycles"])

    def test_observation_never_stops_and_has_no_gaps(self):
        for profile, run in self.runs.items():
            with self.subTest(profile=profile):
                records = run["records"]
                self.assertEqual(len(records), len(run["shadow"]))
                self.assertEqual([r["seq"] for r in records], list(range(1, len(records) + 1)))
                for record in records:
                    # Every one of the 100 symbols is accounted for in every record.
                    self.assertEqual(sum(record["state_counts"].values()), 100)
                    self.assertIs(record["real_submit_allowed"], False)

    def test_no_200_without_a_complete_fresh_board(self):
        for profile, run in self.runs.items():
            with self.subTest(profile=profile):
                gateway = run["gateway"]
                for cycle in gateway:
                    if cycle["status"] == 200:
                        self.assertIs(cycle["decision_available"], True)
                        self.assertEqual(cycle["state_counts"]["FRESH"], 100)
                for start, end in (("08:58:00", "09:00:00"), ("10:31:10", "10:32:00"), ("11:33:00", "11:58:00")):
                    window = [c for c in gateway if start <= c["now"][11:19] < end]
                    self.assertTrue(window, (start, end))
                    self.assertTrue(all(c["status"] == 503 for c in window), (start, end))

    def test_liquid_board_is_decision_available_in_market_hours(self):
        # Positive control: with every symbol trading, the gate does not
        # block the open market except for the injected stall.
        metrics = self.runs["all_liquid"]["metrics"]
        self.assertGreaterEqual(metrics["decision_available_time_pct_market_hours"], 90.0)

    def test_market_like_99_of_100_is_never_reported_as_100(self):
        run = self.runs["market_like_99_of_100"]
        absent = UNIVERSE[99]
        self.assertTrue(all(c["status"] == 503 for c in run["gateway"]))  # whole-board rule kept
        shadow_steps = [run["steps"][x["index"]] for x in run["shadow"]]
        for record, step in zip(run["records"], shadow_steps):
            # A COM-failure cycle publishes no rows, so all 100 are missing.
            self.assertEqual(record["missing_tickers"], UNIVERSE if step.get("com_fail") else [absent])
            self.assertIs(record["decision_pass"], False)
            self.assertLessEqual(record["shadow_fresh_only"]["fresh_count"], 99)
            self.assertIs(record["shadow_fresh_only"]["applied_to_decision"], False)
        for step, cycle in zip(run["steps"], run["gateway"]):
            if step.get("com_fail"):
                self.assertIn("EXCEL_COM_BUSY", cycle["reasons"])
        # Before the identity's first trade nothing is decidable, not even in shadow.
        early = [r for r in run["records"] if "09:00:00" <= r["at"][11:19] < "09:06:00"]
        self.assertTrue(early)
        self.assertTrue(all(r["shadow_fresh_only"]["would_be_decidable"] is False for r in early))
        com = [r for r, s in zip(run["records"], shadow_steps) if s.get("com_fail")]
        self.assertTrue(com)
        self.assertTrue(all(r["observation_pass"] is False for r in com))

    def test_shadow_never_decides_on_a_blocked_board(self):
        for profile, run in self.runs.items():
            with self.subTest(profile=profile):
                for s in run["shadow"]:
                    if s["decision_available"] is not True:
                        self.assertEqual(s["decision_state"], "DECISION_BLOCKED")
                self.assertGreaterEqual(run["metrics"]["shadow_gateway_decision_agreement_pct"], 99.0)


if __name__ == "__main__":
    unittest.main()
