import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("shadow_live_observation", ROOT / "scripts" / "shadow_live_observation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


obs = _load()
NOW = datetime(2026, 10, 5, 16, 58, 0, tzinfo=timezone(timedelta(hours=9)))


def _live(signal="監視"):
    return {
        "updated_at": "2026-10-05 16:57:55",
        "real_submit_allowed": False,
        "live_price_diagnostics": {"symbol": "285A.T", "current_price": 19120},
        "all_targets": [{
            "ticker": "285A.T",
            "signal": signal,
            "strategy": "OR15",
            "price": 19120.0,
            "entry_price": 19120.0,
            "stop_price": 19000.0,
            "source_timestamp": "16:57:50",
            "data": "LIVE",
        }],
    }


def _status():
    return {"state": "RUNNING", "updated_at": NOW.isoformat(), "real_submit_allowed": False}


def _lock():
    return {"heartbeat_at": (NOW - timedelta(seconds=4)).isoformat(), "real_submit_allowed": False}


class ObservationTests(unittest.TestCase):
    def test_running_without_an_entry_signal_is_condition_not_met(self):
        report = obs.classify_observation(_status(), _lock(), _live("監視"), [
            {"event_type": "board_judgment", "at": NOW.isoformat(), "real_submit_allowed": False},
        ], now=NOW)
        self.assertEqual(report["observation"], "FRESH")
        self.assertEqual(report["live_roundtrip"], "NOT_RUN/LIVE_CONDITION_NOT_MET")
        self.assertEqual(report["price"], 19120)
        self.assertEqual(report["board_judgment_count"], 1)
        self.assertEqual(report["virtual_entry"], 0)
        self.assertEqual(report["virtual_exit"], 0)
        self.assertFalse(report["real_submit_allowed"])
        text = obs.format_report(report)
        self.assertIn("LIVE_ROUNDTRIP=NOT_RUN/LIVE_CONDITION_NOT_MET", text)
        self.assertNotIn("PASS", text)

    def test_visible_entry_without_a_ledger_row_is_not_a_live_pass(self):
        report = obs.classify_observation(_status(), _lock(), _live("買いサイン"), [], now=NOW)
        self.assertEqual(report["identity_entry_candidate_count"], 1)
        self.assertEqual(report["live_roundtrip"], "NOT_RUN/ENTRY_VISIBLE_NOT_RECORDED")
        self.assertNotIn("PASS", obs.format_report(report))

    def test_stale_heartbeat_is_not_a_live_round_trip(self):
        lock = _lock()
        lock["heartbeat_at"] = (NOW - timedelta(seconds=120)).isoformat()
        report = obs.classify_observation(_status(), lock, _live(), [], now=NOW)
        self.assertEqual(report["observation"], "STALE")
        self.assertEqual(report["live_roundtrip"], "NOT_RUN/HEARTBEAT_STALE")

    def test_real_submit_true_fails_closed(self):
        live = _live()
        live["real_submit_allowed"] = True
        report = obs.classify_observation(_status(), _lock(), live, [], now=NOW)
        self.assertEqual(report["observation"], "REAL_SUBMIT_NOT_FALSE")
        self.assertFalse(report["real_submit_allowed"])

    def test_reader_source_does_not_submit_or_loosen_entries(self):
        text = (ROOT / "scripts" / "shadow_live_observation.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", text)
        self.assertNotIn("shadow_execution", text)
        self.assertIn("NOT_RUN/LIVE_CONDITION_NOT_MET", text)
        self.assertNotIn("LIVE_ROUNDTRIP=PASS", text)
