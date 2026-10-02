import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 2, 9, 16, 5, tzinfo=JST)


def _load():
    spec = importlib.util.spec_from_file_location("ai_shadow_supervisor", ROOT / "scripts" / "ai_shadow_supervisor.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sup = _load()


def _diag(**overrides):
    payload = {
        "price_source_status": "OK",
        "source_mode": "MS2_RSS_WORKBOOK",
        "workbook_name": "Kioxia_MS2_RSS_Live_Signals.xlsx",
        "data_conflict": False,
        "duplicate_collector": False,
        "duplicate_watcher": False,
        "collector_count": 1,
        "watcher_count": 1,
        "stale_reason": "",
        "real_submit_allowed": False,
    }
    payload.update(overrides)
    return payload


def _live(rows, **overrides):
    payload = {
        "updated_at": "2026-10-02 09:16:05",
        "source": "MarketSpeed II RSS / local PC",
        "source_mode": "MS2_RSS_WORKBOOK",
        "stale": False,
        "data_conflict": False,
        "price_source_status": "OK",
        "live_values_available": True,
        "real_submit_allowed": False,
        "live_price_diagnostics": _diag(),
        "all_targets": rows,
    }
    payload.update(overrides)
    return payload


def _row(**overrides):
    row = {
        "ticker": "285A.T",
        "signal": "買いサイン",
        "strategy": "OR15",
        "price": 1500.0,
        "entry_price": 1500.0,
        "stop_price": 1450.0,
        "target1": 1600.0,
        "target2": 1700.0,
        "source_timestamp": "09:16:00",
        "data": "LIVE",
    }
    row.update(overrides)
    return row


class SafetyTests(unittest.TestCase):
    def test_fresh_canonical_payload_passes_and_keeps_real_submit_false(self):
        verdict = sup.assess_live_payload(_live([_row()]), file_mtime=NOW - timedelta(seconds=2), now=NOW)
        self.assertTrue(verdict["ok"])
        self.assertFalse(verdict["real_submit_allowed"])

    def test_stale_sample_conflict_and_real_submit_true_fail_closed(self):
        stale = _live([_row()], updated_at="2026-10-02 09:00:00")
        self.assertIn("STALE_OR_MISSING_TIMESTAMP", sup.assess_live_payload(stale, file_mtime=NOW, now=NOW)["reasons"])
        sample = _live([_row()], source="公開スナップショット")
        self.assertIn("CACHED_OR_SAMPLE_PAYLOAD", sup.assess_live_payload(sample, file_mtime=NOW, now=NOW)["reasons"])
        conflict = _live([_row()], data_conflict=True)
        self.assertIn("DATA_CONFLICT", sup.assess_live_payload(conflict, file_mtime=NOW, now=NOW)["reasons"])
        mismatch = _live([_row()], price_source_status="PRICE_SOURCE_MISMATCH")
        self.assertFalse(sup.assess_live_payload(mismatch, file_mtime=NOW, now=NOW)["ok"])
        unlocked = _live([_row()], real_submit_allowed=True)
        self.assertIn("REAL_SUBMIT_NOT_FALSE", sup.assess_live_payload(unlocked, file_mtime=NOW, now=NOW)["reasons"])
        self.assertIn("MISSING_PAYLOAD", sup.assess_live_payload(None, file_mtime=NOW, now=NOW)["reasons"])

    def test_missing_diagnostics_and_duplicate_collector_fail_closed(self):
        missing = _live([_row()])
        del missing["live_price_diagnostics"]
        self.assertIn("MISSING_PRICE_DIAGNOSTICS", sup.assess_live_payload(missing, file_mtime=NOW, now=NOW)["reasons"])
        duplicate = _live([_row()])
        duplicate["live_price_diagnostics"] = _diag(collector_count=2, duplicate_collector=True)
        reasons = sup.assess_live_payload(duplicate, file_mtime=NOW, now=NOW)["reasons"]
        self.assertIn("DUPLICATE_COLLECTOR", reasons)


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.id().replace(".", "_"))
        root = Path("/tmp/ai_shadow_tests")
        root.mkdir(exist_ok=True)
        self.data = root / self.dir
        if self.data.exists():
            for child in self.data.iterdir():
                child.unlink()
        else:
            self.data.mkdir(parents=True)

    def _engine(self):
        return sup.load_engine(self.data, now=NOW)

    def test_ui_independent_entry_is_idempotent_and_exit_uses_published_price(self):
        engine = self._engine()
        fresh = _live([_row()])
        verdict = sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW)
        sup.apply_cycle(engine, fresh, verdict, now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "RUNNING")
        self.assertEqual(len(engine["open_positions"]), 1)
        sup.apply_cycle(engine, fresh, verdict, now=NOW + timedelta(seconds=5), data_dir=self.data)
        entries = [event for event in engine["ledger"] if event["event_type"] == "virtual_entry"]
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0]["quantity"])
        self.assertFalse(entries[0]["real_submit_allowed"])
        self.assertIn("買いサイン", entries[0]["decision_rationale"])

        flat_at = NOW + timedelta(seconds=20)
        flat = _live([_row(signal="監視", price=1550.0)], updated_at="2026-10-02 09:16:20")
        sup.apply_cycle(engine, flat, sup.assess_live_payload(flat, file_mtime=flat_at, now=flat_at), now=flat_at, data_dir=self.data)
        exits = [event for event in engine["ledger"] if event["event_type"] == "virtual_exit"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["pnl_per_share_yen"], 50.0)
        self.assertEqual(exits[0]["performance_bucket"], "clean_strategy")
        self.assertEqual(exits[0]["pricing"], "collector_published_price_not_fill_model")
        self.assertEqual(engine["open_positions"], {})

    def test_fail_closed_does_not_open_or_close_from_stale_prices(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        stale = _live([_row(price=1.0)], updated_at="2026-10-02 08:00:00")
        paused_at = NOW + timedelta(seconds=90)
        sup.apply_cycle(engine, stale, sup.assess_live_payload(stale, file_mtime=paused_at, now=paused_at), now=paused_at, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(len(engine["open_positions"]), 1)
        exits = [event for event in engine["ledger"] if event["event_type"] == "virtual_exit"]
        self.assertEqual(exits, [])
        incident = engine["incidents"][-1]
        self.assertTrue(incident["fail_closed"])
        self.assertEqual(incident["real_trade_impact"], "NONE_REAL_SUBMIT_REMAINS_FALSE")
        self.assertIsNone(incident["recovery_at"])
        self.assertGreaterEqual(incident["invalidated_signal_count"], 1)

        recovered = _live([_row(signal="監視", price=1520.0)], updated_at="2026-10-02 09:17:48")
        resume_at = NOW + timedelta(minutes=1, seconds=43)
        sup.apply_cycle(engine, recovered, sup.assess_live_payload(recovered, file_mtime=resume_at, now=resume_at), now=resume_at, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "RUNNING")
        self.assertEqual(engine["incidents"][-1]["recovery_mode"], "AUTO")
        self.assertEqual(engine["incidents"][-1]["duration_seconds"], 13)
        self.assertEqual(engine["incidents"][-1]["shadow_impact"], "AUTO_RESUMED")
        exits = [event for event in engine["ledger"] if event["event_type"] == "virtual_exit"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["exit_price"], 1520.0)
        self.assertEqual(exits[0]["performance_bucket"], "contaminated_by_data_outage")
        sup.apply_cycle(engine, recovered, sup.assess_live_payload(recovered, file_mtime=resume_at, now=resume_at), now=resume_at + timedelta(seconds=5), data_dir=self.data)
        self.assertEqual(len([event for event in engine["ledger"] if event["event_type"] == "virtual_exit"]), 1)

    def test_missing_ledger_is_not_treated_as_healthy(self):
        state = sup.fresh_state(now=NOW)
        state["last_seq"] = 2
        state["state"] = "RUNNING"
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        engine = sup.load_engine(self.data, now=NOW)
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertTrue(engine["state"]["resume_blocked"])
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(engine["ledger"], [])

    def test_restart_reopens_from_ledger_without_a_second_entry(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        restarted = sup.load_engine(self.data, now=NOW + timedelta(seconds=10))
        self.assertEqual(restarted["state"]["state"], "RECOVERING")
        self.assertEqual(len(restarted["open_positions"]), 1)
        sup.apply_cycle(restarted, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW + timedelta(seconds=10), data_dir=self.data)
        self.assertEqual(restarted["state"]["state"], "RUNNING")
        self.assertEqual(len([event for event in restarted["ledger"] if event["event_type"] == "virtual_entry"]), 1)

    def test_second_process_does_not_acquire_a_live_lock(self):
        lock = self.data / "supervisor.lock.json"
        first = sup.acquire_singleton(lock, pid=111, now=NOW, alive=lambda pid: pid == 111)
        second = sup.acquire_singleton(lock, pid=222, now=NOW + timedelta(seconds=5), alive=lambda pid: pid == 111)
        self.assertEqual(first, "ACQUIRED")
        self.assertEqual(second, "ALREADY_RUNNING")
        unknown = sup.acquire_singleton(lock, pid=333, now=NOW, alive=lambda pid: None)
        self.assertEqual(unknown, "REFUSED_LOCK_UNKNOWN")

    def test_ops_summary_separates_strategy_pnl_from_outage_pnl(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        stale = _live([_row()], updated_at="2026-10-02 08:00:00")
        paused_at = NOW + timedelta(seconds=30)
        sup.apply_cycle(engine, stale, sup.assess_live_payload(stale, file_mtime=paused_at, now=paused_at), now=paused_at, data_dir=self.data)
        recovered = _live([_row(signal="監視", price=1400.0)], updated_at="2026-10-02 09:16:40")
        resume_at = NOW + timedelta(seconds=40)
        sup.apply_cycle(engine, recovered, sup.assess_live_payload(recovered, file_mtime=resume_at, now=resume_at), now=resume_at, data_dir=self.data)
        ops = sup.summarize_operations(engine, now=resume_at)["daily"]
        self.assertEqual(ops["error_count"], 1)
        self.assertEqual(ops["auto_recovery_count"], 1)
        self.assertEqual(ops["manual_response_count"], 0)
        self.assertEqual(ops["freshness_anomaly_count"], 1)
        self.assertEqual(ops["contaminated_pnl_per_share_yen"], -100.0)
        self.assertEqual(ops["clean_strategy_exit_count"], 0)
        self.assertIsNotNone(ops["shadow_uptime_ratio"])
        self.assertLess(ops["shadow_uptime_ratio"], 1)
        snapshot = sup.status_snapshot(engine, now=resume_at)
        self.assertFalse(snapshot["real_submit_allowed"])
        self.assertTrue(snapshot["ui_independent"])
        self.assertEqual(snapshot["latest_incident"]["recovery_mode"], "AUTO")

    def test_excel_identity_incident_is_kept_without_opening_a_trade(self):
        incident = {
            "record_class": "operations_incident",
            "incident_id": "inc-excel",
            "occurrence_at": NOW.isoformat(),
            "recovery_at": None,
            "component": "excel_identity",
            "error_code": "EXCEL_IDENTITY_PROBE_FAILED",
            "symptom": "unmatched: rot_moniker,hwnd,pid,command_line,parent / last_error=ROT_MONIKER_NOT_REGISTERED",
            "suspected_cause": "ROT_MONIKER_NOT_REGISTERED",
            "confirmed_cause": None,
            "fail_closed": True,
            "real_submit_allowed": False,
            "real_trade_impact": "NONE_REAL_SUBMIT_REMAINS_FALSE",
            "shadow_impact": "STOPPED",
            "invalidated_signal_count": None,
            "recovery_mode": None,
            "recurrence_key": "excel_identity|EXCEL_IDENTITY_PROBE_FAILED",
            "recurrence_count": 1,
        }
        (self.data / "incidents.jsonl").write_text(json.dumps(incident) + "\n", encoding="utf-8")
        engine = sup.load_engine(self.data, now=NOW)
        self.assertIsNot(engine["state"].get("resume_blocked"), True)
        self.assertEqual(engine["ledger"], [])
        self.assertEqual(engine["open_positions"], {})
        self.assertEqual(engine["incidents"][0]["error_code"], "EXCEL_IDENTITY_PROBE_FAILED")
        unlocked = dict(incident)
        unlocked["real_submit_allowed"] = True
        (self.data / "incidents.jsonl").write_text(json.dumps(unlocked) + "\n", encoding="utf-8")
        blocked = sup.load_engine(self.data, now=NOW)
        self.assertTrue(blocked["state"]["resume_blocked"])
        self.assertEqual(blocked["state"]["reason"], "STATE_MISSING")

    def test_workbook_open_crash_incident_does_not_open_a_trade(self):
        incident = {
            "record_class": "operations_incident",
            "incident_id": "inc-open-crash",
            "occurrence_at": NOW.isoformat(),
            "recovery_at": None,
            "component": "workbook_open",
            "error_code": "EXCEL_PROCESS_EXITED",
            "symptom": "launched Excel PID 19860 exited before identity verification",
            "suspected_cause": "PREVIOUS_SERIOUS_ERROR_DIALOG",
            "confirmed_cause": None,
            "fail_closed": True,
            "real_submit_allowed": False,
            "real_trade_impact": "NONE_REAL_SUBMIT_REMAINS_FALSE",
            "shadow_impact": "STOPPED",
            "invalidated_signal_count": None,
            "recovery_mode": None,
            "recurrence_key": "workbook_open|EXCEL_PROCESS_EXITED",
            "recurrence_count": 1,
            "identity_checks": {"launched_excel_pid": 19860, "excel_exit_code": -1073741819, "process_exited": True},
        }
        (self.data / "incidents.jsonl").write_text(json.dumps(incident) + "\n", encoding="utf-8")
        engine = sup.load_engine(self.data, now=NOW)
        self.assertIsNot(engine["state"].get("resume_blocked"), True)
        self.assertEqual(engine["ledger"], [])
        self.assertEqual(engine["open_positions"], {})
        self.assertEqual(engine["state"]["real_submit_allowed"], False)
        self.assertEqual(engine["incidents"][0]["component"], "workbook_open")

    def test_manual_acknowledgement_marks_recovery_manual(self):
        engine = self._engine()
        stale = _live([_row()], updated_at="2026-10-02 08:00:00")
        sup.apply_cycle(engine, stale, sup.assess_live_payload(stale, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        (self.data / "manual_recovery.json").write_text(json.dumps({"action": "acknowledge"}), encoding="utf-8")
        fresh = _live([_row(signal="監視")])
        resume_at = NOW + timedelta(seconds=12)
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=resume_at, now=resume_at), now=resume_at, data_dir=self.data, recovery_mode=sup.read_manual_recovery(self.data))
        self.assertEqual(engine["incidents"][-1]["recovery_mode"], "MANUAL")


class ContractSourceTests(unittest.TestCase):
    def test_controller_and_gateway_keep_real_submit_locked(self):
        controller = (ROOT / "downloads" / "AI_COCKPIT_CONTROLLER_V9.ps1").read_text(encoding="utf-8")
        gateway = (ROOT / "downloads" / "AI_COCKPIT_GATEWAY_V9.ps1").read_text(encoding="utf-8")
        ui = (ROOT / "trade_control.js").read_text(encoding="utf-8")
        self.assertIn("ai_shadow_supervisor.py", controller)
        self.assertIn("shadow_supervisor_pid", controller)
        self.assertIn("real_submit_allowed        = $false", gateway)
        self.assertIn("shadow_positions_connected  = $false", gateway)
        self.assertIn("shadow_position_status      = 'NOT_PUBLISHED'", gateway)
        self.assertIn("Get-ShadowEnginePublication", gateway)
        self.assertIn("PAUSED_FAIL_CLOSED", ui)
        self.assertIn("shadow_engine_state", ui)
        self.assertNotIn("submit_shadow_order", (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
