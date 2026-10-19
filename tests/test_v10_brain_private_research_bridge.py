"""Synthetic-only live/virtual research bridge negative tests. No market account data."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.v10_brain_private_research_bridge import (
    STATUS_NAME, _universe, _trusted_file, evaluate_context, run_once, blocked,
)
from scripts.v10_brain_virtual_outcome_audit import audit

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 19, 10, 0, 5, tzinfo=JST)
QUOTE = "2026-10-19T10:00:03+09:00"
OBS = "2026-10-19T10:00:04+09:00"
TICKERS = [f"{n:04d}.T" for n in range(1000, 1100)]


def row(t):
    return {
        "ticker": t, "sheet_code": t, "data": "LIVE",
        "signal": "監視", "strategy": "OR15押し目",
        "price": 100.0, "vwap": 99.0, "or_high": 101.0, "or_low": 98.0,
        "source_timestamp": "10:00:03", "source_timestamp_at": QUOTE,
        "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
        "source_timestamp_observed_at": OBS,
    }


def market():
    return {
        "schema_version": "ms2-common-1.0",
        "source": "MarketSpeed II RSS / local PC",
        "source_mode": "MS2_RSS_WORKBOOK",
        "timestamp_timezone": "Asia/Tokyo",
        "observed_at_offset": OBS,
        "updated_at": "2026-10-19 10:00:04",
        "data_conflict": False, "stale": False,
        "real_submit_allowed": False,
        "price_source_status": "OK", "live_values_available": True,
        "universe": 100, "valid": 100,
        "live_price_diagnostics": {
            "workbook_name": "Kioxia_MS2_RSS_Live_Signals.xlsx",
            "workbook_identity_verified": True,
            "source_mode": "MS2_RSS_WORKBOOK",
            "price_source_status": "OK", "data_conflict": False,
            "live_values_available": True, "stale_reason": "",
            "duplicate_collector": False, "duplicate_watcher": False,
            "collector_count": 1, "watcher_count": 1,
            "source_timestamp": "10:00:03", "source_timestamp_at": QUOTE,
            "source_timestamp_basis": "COLLECTOR_OBSERVED_CHANGE",
            "source_timestamp_observed_at": OBS,
        },
        "all_targets": [row(t) for t in TICKERS],
    }


def watchlist():
    return {"stocks": {f"synthetic{i}": {"ticker": t} for i, t in enumerate(TICKERS)}}


def ledger():
    a = {
        "record_class": "shadow_observation", "schema_version": "ai-shadow-supervisor-1",
        "seq": 1, "event_type": "virtual_entry",
        "at": "2026-10-19T09:10:00+09:00",
        "pricing": "collector_published_price_not_fill_model",
        "quantity": None, "real_submit_allowed": False,
        "position_key": "1000.T|LONG", "ticker": "1000.T", "side": "LONG",
        "strategy": "OR15押し目", "entry_price": 100.0, "stop_price": 98.0,
        "source_timestamp_at": "2026-10-19T09:09:59+09:00",
        "performance_bucket": "open_unrealized_not_marked",
    }
    b = {
        "record_class": "shadow_observation", "schema_version": "ai-shadow-supervisor-1",
        "seq": 2, "event_type": "virtual_exit",
        "at": "2026-10-19T09:20:00+09:00",
        "pricing": "collector_published_price_not_fill_model",
        "quantity": None, "real_submit_allowed": False,
        "position_key": "1000.T|LONG", "ticker": "1000.T", "side": "LONG",
        "strategy": "OR15押し目", "entry_price": 100.0, "exit_price": 102.0,
        "pnl_per_share_yen": 2.0, "r_multiple": 1.0,
        "related_entry_seq": 1, "performance_bucket": "clean_strategy",
    }
    return [a,b]


def virtual():
    return audit(ledger(), now=NOW)


def composed(snapshot=None, source_universe=None, v=None, mtime=None):
    return evaluate_context(
        snapshot if snapshot is not None else market(),
        mtime if mtime is not None else NOW,
        source_universe if source_universe is not None else _universe(watchlist()),
        v if v is not None else virtual(), now=NOW
    )


class BrainPrivateResearchBridgeTests(unittest.TestCase):
    def test_healthy_market_and_complete_virtual_outcome_yield_only_research(self):
        result = composed()
        self.assertEqual(result["state"], "RESEARCH_OBSERVATION_ONLY", result)
        self.assertEqual(result["verified_board_row_count"], 100)
        self.assertEqual(result["market_data_gate"], "PASS")
        self.assertEqual(result["virtual_outcome_gate"], "PASS")
        self.assertEqual(result["strategy_statistics"][0]["strategy_id"], "OR15押し目")
        self.assertEqual(result["strategy_statistics"][0]["virtual_mean_r"], 1.0)
        self.assertFalse(result["brain_trade_decision_eligible"])
        self.assertFalse(result["tested_expectancy_available"])
        self.assertFalse(result["costs_verified"])
        self.assertFalse(result["source_authenticated"])
        self.assertFalse(result["real_submit_allowed"])
        for private in ("1000.T", "100.0", "ledger.jsonl", "account_id", "broker"):
            self.assertNotIn(private, str(result))

    def test_live_observer_watch_is_count_only(self):
        p = market()
        p["all_targets"][0]["price"] = 102
        out = composed(snapshot=p)
        self.assertEqual(out["state"], "RESEARCH_OBSERVATION_ONLY")
        self.assertEqual(out["research_observation_counts"]["OR15_ABOVE_VWAP_WATCH"], 1)

    def test_friday_quote_rewritten_monday_blocks(self):
        p = market()
        old = "2026-10-16T15:30:00+09:00"
        p["live_price_diagnostics"].update(
            source_timestamp="15:30:00", source_timestamp_at=old,
            source_timestamp_observed_at="2026-10-16T15:30:01+09:00")
        self.assertEqual(composed(snapshot=p)["state"], "BLOCKED")

    def test_one_stale_quote_blocks_all(self):
        p = market()
        p["all_targets"][99]["source_timestamp_at"] = "2026-10-16T15:30:00+09:00"
        self.assertIn("BOARD_OR_UNIVERSE_UNVERIFIED", composed(snapshot=p)["reasons"])

    def test_incomplete_99_rows_blocks(self):
        p = market()
        p["all_targets"].pop()
        p["universe"] = 99
        p["valid"] = 99
        self.assertIn("BOARD_OR_UNIVERSE_UNVERIFIED", composed(snapshot=p)["reasons"])

    def test_universe_identity_swap_blocks(self):
        u = _universe(watchlist())
        u["tickers"][0] = "9999.T"
        self.assertIn("BOARD_OR_UNIVERSE_UNVERIFIED", composed(source_universe=u)["reasons"])

    def test_duplicate_collector_blocks(self):
        p = market()
        p["live_price_diagnostics"]["collector_count"] = 2
        self.assertEqual(composed(snapshot=p)["state"], "BLOCKED")

    def test_live_real_submit_toggle_blocks(self):
        p = market()
        p["real_submit_allowed"] = True
        self.assertEqual(composed(snapshot=p)["reasons"], ["REAL_ORDER_FLAG_UNSAFE"])

    def test_undated_quote_blocks(self):
        p = market()
        p["live_price_diagnostics"]["source_timestamp_at"] = None
        self.assertEqual(composed(snapshot=p)["state"], "BLOCKED")

    def test_writer_not_recent_blocks(self):
        self.assertEqual(
            composed(mtime=NOW-timedelta(minutes=5))["state"], "BLOCKED")

    def test_unknown_or_missing_ledger_blocks(self):
        broken = blocked("LEDGER_INVALID")
        out = composed(v=broken)
        self.assertIn("VIRTUAL_LEDGER_UNVERIFIED", out["reasons"])
        self.assertEqual(out["strategy_statistics"], [])

    def test_fake_provenance_or_ev_promotion_blocks(self):
        for key in ("real_submit_allowed", "tested_expectancy_available",
                    "source_authenticated", "promotion_eligible", "broker_fills_verified", "costs_verified"):
            v = virtual()
            v[key] = True
            self.assertEqual(composed(v=v)["state"], "BLOCKED", key)

    def test_malformed_source_universe_blocks(self):
        data = watchlist()
        data["stocks"].pop("synthetic0")
        self.assertFalse(_universe(data)["verified"])
        data = watchlist()
        data["stocks"]["synthetic1"]["ticker"] = "1000.T"
        self.assertFalse(_universe(data)["verified"])

    def test_naive_clock_blocks(self):
        out = evaluate_context(market(), NOW, _universe(watchlist()), virtual(),
                               now=datetime(2026,10,19,10,0,5))
        self.assertEqual(out["state"], "BLOCKED")

    def test_no_raw_records_are_exported(self):
        out = composed()
        data = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("all_targets", data)
        self.assertNotIn("live_price_diagnostics", data)
        self.assertNotIn("entry_price", data)
        self.assertNotIn("ticker", data)

    def _files(self, td):
        root = Path(td)
        shadow = root/"private_shadow"
        shadow.mkdir()
        live = root/"live_ms2.json"
        watch = root/"watchlist_100.json"
        lgr = shadow/"ledger.jsonl"
        status = shadow/STATUS_NAME
        live.write_text(json.dumps(market(), ensure_ascii=False),encoding="utf-8")
        watch.write_text(json.dumps(watchlist()),encoding="utf-8")
        lgr.write_text("".join(json.dumps(e,ensure_ascii=False)+"\n" for e in ledger()),encoding="utf-8")
        os.utime(live,(NOW.timestamp(), NOW.timestamp()))
        return live,watch,lgr,status

    def test_private_one_shot_writes_aggregate_status_only(self):
        with tempfile.TemporaryDirectory() as td:
            live,watch,lgr,status = self._files(td)
            raw = (live.read_bytes(),watch.read_bytes(),lgr.read_bytes())
            out = run_once(live_path=live,watchlist_path=watch,
                           ledger_path=lgr,status_path=status,now=NOW)
            self.assertEqual(out["state"],"RESEARCH_OBSERVATION_ONLY",out)
            self.assertEqual(json.loads(status.read_text())["state"],"RESEARCH_OBSERVATION_ONLY")
            self.assertEqual((live.read_bytes(),watch.read_bytes(),lgr.read_bytes()),raw)
            self.assertNotIn("1000.T",status.read_text())

    def test_corrupt_ledger_writes_only_blocked_status(self):
        with tempfile.TemporaryDirectory() as td:
            live,watch,lgr,status = self._files(td)
            lgr.write_text('{"account":"secret-local-data"}\n',encoding="utf-8")
            out = run_once(live_path=live,watchlist_path=watch,
                           ledger_path=lgr,status_path=status,now=NOW)
            self.assertEqual(out["state"],"BLOCKED")
            self.assertNotIn("secret",status.read_text())
            self.assertNotIn("1000.T",status.read_text())

    def test_reject_status_outside_shadow_directory(self):
        with tempfile.TemporaryDirectory() as td:
            live,watch,lgr,status = self._files(td)
            out = run_once(live_path=live,watchlist_path=watch,
                           ledger_path=lgr,status_path=Path(td)/STATUS_NAME,now=NOW)
            self.assertEqual(out["reasons"],["STATUS_PRIVATE_BOUNDARY_UNVERIFIED"])
            self.assertFalse((Path(td)/STATUS_NAME).exists())

    def test_local_symlink_rejected_without_reading_private_source(self):
        with tempfile.TemporaryDirectory() as td:
            live,watch,lgr,status = self._files(td)
            fake = Path(td)/"elsewhere.json"
            fake.write_text('{"sensitive":"do-not-read"}')
            live.unlink()
            try:
                live.symlink_to(fake)
            except (OSError,NotImplementedError):
                self.skipTest("symlink unavailable on this runner")
            out = run_once(live_path=live,watchlist_path=watch,
                           ledger_path=lgr,status_path=status,now=NOW)
            self.assertEqual(out["state"],"BLOCKED")
            self.assertNotIn("sensitive",status.read_text())

    def test_untrusted_output_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            live,watch,lgr,status = self._files(td)
            target=Path(td)/"unrelated.txt"
            target.write_text("DO_NOT_CHANGE")
            try: status.symlink_to(target)
            except (OSError,NotImplementedError):
                self.skipTest("symlink unavailable on this runner")
            out=run_once(live_path=live,watchlist_path=watch,
                         ledger_path=lgr,status_path=status,now=NOW)
            self.assertEqual(out["state"],"BLOCKED")
            self.assertEqual(target.read_text(),"DO_NOT_CHANGE")

    def test_invalid_publication_time_blocks_with_fresh_mtime(self):
        p=market()
        p["observed_at_offset"]="2026-10-16T15:30:00+09:00"
        self.assertEqual(composed(snapshot=p)["state"],"BLOCKED")


if __name__=="__main__":
    unittest.main()
