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

    def test_quote_fill_round_trip_saves_pnl_expectancy_and_excursions(self):
        engine = self._engine()
        entry = _live([_row(price=19120.0, entry_price=19120.0, stop_price=19000.0, bid=19110.0, ask=19130.0)])
        sup.apply_cycle(engine, entry, sup.assess_live_payload(entry, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        opened = [event for event in engine["ledger"] if event["event_type"] == "virtual_entry"][0]
        self.assertEqual(opened["fill_price"], 19130.0)
        self.assertEqual(opened["slippage_yen"], 10.0)
        self.assertIn("買いサイン", opened["decision_rationale"])
        self.assertIsNone(opened["quantity"])
        self.assertFalse(opened["real_submit_allowed"])

        down_at = NOW + timedelta(seconds=10)
        down = _live([_row(price=19050.0, entry_price=19120.0, stop_price=19000.0)], updated_at="2026-10-02 09:16:15")
        sup.apply_cycle(engine, down, sup.assess_live_payload(down, file_mtime=down_at, now=down_at), now=down_at, data_dir=self.data)
        up_at = NOW + timedelta(seconds=20)
        up = _live([_row(price=19300.0, entry_price=19120.0, stop_price=19000.0)], updated_at="2026-10-02 09:16:25")
        sup.apply_cycle(engine, up, sup.assess_live_payload(up, file_mtime=up_at, now=up_at), now=up_at, data_dir=self.data)

        flat_at = NOW + timedelta(seconds=30)
        flat = _live([_row(signal="監視", price=19180.0, bid=19170.0, ask=19190.0)], updated_at="2026-10-02 09:16:35")
        sup.apply_cycle(engine, flat, sup.assess_live_payload(flat, file_mtime=flat_at, now=flat_at), now=flat_at, data_dir=self.data)
        closed = [event for event in engine["ledger"] if event["event_type"] == "virtual_exit"][0]
        self.assertEqual(closed["fill_entry_price"], 19130.0)
        self.assertEqual(closed["fill_exit_price"], 19170.0)
        self.assertEqual(closed["fill_pnl_per_share_yen"], 40.0)
        self.assertEqual(closed["pnl_per_share_yen"], 60.0)
        self.assertEqual(closed["slippage_yen"], 20.0)
        self.assertEqual(closed["mae_yen"], 80.0)
        self.assertEqual(closed["mfe_yen"], 170.0)
        self.assertIn("監視", closed["decision_rationale"])
        self.assertEqual(closed["fill_model"], "collector_quote_simulation")
        self.assertFalse(closed["real_submit_allowed"])

        loss_at = NOW + timedelta(seconds=40)
        loss_entry = _live([_row(price=100.0, entry_price=100.0, stop_price=90.0, bid=100.0, ask=100.0)], updated_at="2026-10-02 09:16:45")
        sup.apply_cycle(engine, loss_entry, sup.assess_live_payload(loss_entry, file_mtime=loss_at, now=loss_at), now=loss_at, data_dir=self.data)
        loss_exit_at = NOW + timedelta(seconds=50)
        loss_exit = _live([_row(signal="監視", price=90.0, bid=90.0, ask=90.0)], updated_at="2026-10-02 09:16:55")
        sup.apply_cycle(engine, loss_exit, sup.assess_live_payload(loss_exit, file_mtime=loss_exit_at, now=loss_exit_at), now=loss_exit_at, data_dir=self.data)
        saved = json.loads((self.data / "shadow_performance.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["real_submit_allowed"])
        self.assertEqual(saved["closed_trade_count"], 2)
        self.assertEqual(saved["expectancy_yen_per_share"], 15.0)
        self.assertEqual(saved["profit_factor"], 4.0)
        self.assertEqual(saved["avg_mae_yen"], 45.0)
        self.assertEqual(saved["avg_mfe_yen"], 85.0)
        self.assertEqual(saved["avg_slippage_yen"], 10.0)
        self.assertEqual(sup.status_snapshot(engine, now=loss_exit_at)["trade_performance"]["expectancy_yen_per_share"], 15.0)
        source = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertNotIn("import shadow_execution", source)
        self.assertNotIn("submit_shadow_order", source)

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
        self.assertEqual(blocked["state"]["reason"], "INCIDENT_LOG_UNSAFE")

    def test_unresolved_excel_open_blocks_virtual_entry_on_fresh_prices(self):
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
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(engine["state"]["reason"], "EXCEL_OPEN_UNVERIFIED")
        self.assertFalse(engine["state"]["real_submit_allowed"])
        self.assertEqual(engine["ledger"], [])
        self.assertEqual(engine["open_positions"], {})
        self.assertIsNone(engine["incidents"][0]["recovery_at"])

        incident["component"] = "workbook_open"
        incident["recovery_at"] = None
        (self.data / "incidents.jsonl").write_text(json.dumps(incident) + "\n", encoding="utf-8")
        (self.data / "state.json").unlink()
        blocked = sup.load_engine(self.data, now=NOW)
        sup.apply_cycle(blocked, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(blocked["state"]["reason"], "EXCEL_OPEN_UNVERIFIED")
        self.assertEqual(blocked["ledger"], [])

        incident["recovery_at"] = NOW.isoformat()
        (self.data / "incidents.jsonl").write_text(json.dumps(incident) + "\n", encoding="utf-8")
        (self.data / "state.json").unlink()
        resumed = sup.load_engine(self.data, now=NOW)
        sup.apply_cycle(resumed, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(resumed["state"]["state"], "RUNNING")
        self.assertEqual(len(resumed["open_positions"]), 1)
        self.assertFalse(resumed["state"]["real_submit_allowed"])

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

    def test_unsafe_incident_beside_state_does_not_open_a_trade(self):
        state = sup.fresh_state(now=NOW)
        state["state"] = "RUNNING"
        state["last_seq"] = 0
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (self.data / "ledger.jsonl").write_text("", encoding="utf-8")
        incident = {
            "record_class": "operations_incident",
            "incident_id": "inc-unlocked",
            "occurrence_at": NOW.isoformat(),
            "recovery_at": None,
            "component": "ai_shadow",
            "error_code": "STALE_OR_MISSING_TIMESTAMP",
            "fail_closed": True,
            "real_submit_allowed": True,
            "recurrence_key": "ai_shadow|STALE_OR_MISSING_TIMESTAMP",
            "recurrence_count": 1,
        }
        (self.data / "incidents.jsonl").write_text(json.dumps(incident) + "\n", encoding="utf-8")
        engine = sup.load_engine(self.data, now=NOW)
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["reason"], "INCIDENT_LOG_UNSAFE")
        self.assertEqual(engine["ledger"], [])
        self.assertEqual(engine["open_positions"], {})
        self.assertFalse(engine["state"]["real_submit_allowed"])

    def test_changed_board_does_not_open_a_second_virtual_entry(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        later = NOW + timedelta(seconds=20)
        changed = _live([_row(price=1510.0)], updated_at="2026-10-02 09:16:25")
        sup.apply_cycle(engine, changed, sup.assess_live_payload(changed, file_mtime=later, now=later), now=later, data_dir=self.data)
        entries = [event for event in engine["ledger"] if event["event_type"] == "virtual_entry"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(engine["open_positions"]), 1)
        self.assertIsNone(entries[0]["quantity"])
        self.assertFalse(entries[0]["real_submit_allowed"])

    def test_short_exit_pnl_is_entry_minus_exit_and_stays_per_share(self):
        engine = self._engine()
        fresh = _live([_row(signal="空売りサイン", price=1500.0, entry_price=1500.0, stop_price=1550.0)])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        flat_at = NOW + timedelta(seconds=30)
        flat = _live([_row(signal="監視", price=1400.0)], updated_at="2026-10-02 09:16:35")
        sup.apply_cycle(engine, flat, sup.assess_live_payload(flat, file_mtime=flat_at, now=flat_at), now=flat_at, data_dir=self.data)
        exits = [event for event in engine["ledger"] if event["event_type"] == "virtual_exit"]
        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["side"], "SHORT")
        self.assertEqual(exits[0]["pnl_per_share_yen"], 100.0)
        self.assertEqual(exits[0]["r_multiple"], 2.0)
        self.assertIsNone(exits[0]["quantity"])
        self.assertFalse(exits[0]["real_submit_allowed"])
        self.assertEqual(exits[0]["performance_bucket"], "clean_strategy")
        ops = sup.summarize_operations(engine, now=flat_at)
        self.assertEqual(ops["daily"]["clean_strategy_pnl_per_share_yen"], 100.0)
        self.assertEqual(ops["weekly"]["clean_strategy_pnl_per_share_yen"], 100.0)
        self.assertEqual(ops["monthly"]["clean_strategy_pnl_per_share_yen"], 100.0)
        self.assertIsNone(ops["daily"]["contaminated_pnl_per_share_yen"])

    def test_weekly_window_keeps_an_exit_that_daily_drops(self):
        engine = {"state": sup.fresh_state(now=NOW), "ledger": [], "incidents": [], "open_positions": {}}
        engine["state"]["engine_started_at"] = (NOW - timedelta(days=10)).isoformat()
        engine["state"]["state"] = "RUNNING"
        old_at = NOW - timedelta(days=3)
        engine["ledger"] = [
            {
                "record_class": "shadow_observation",
                "event_type": "virtual_exit",
                "seq": 1,
                "at": old_at.isoformat(),
                "real_submit_allowed": False,
                "pnl_per_share_yen": 10.0,
                "performance_bucket": "clean_strategy",
                "quantity": None,
            },
            {
                "record_class": "shadow_observation",
                "event_type": "virtual_exit",
                "seq": 2,
                "at": NOW.isoformat(),
                "real_submit_allowed": False,
                "pnl_per_share_yen": -4.0,
                "performance_bucket": "clean_strategy",
                "quantity": None,
            },
        ]
        engine["incidents"] = [{
            "record_class": "operations_incident",
            "occurrence_at": old_at.isoformat(),
            "recovery_at": (old_at + timedelta(seconds=12)).isoformat(),
            "duration_seconds": "12",
            "recovery_mode": "AUTO",
            "error_code": "STALE_OR_MISSING_TIMESTAMP",
            "recurrence_key": "live_ms2|STALE_OR_MISSING_TIMESTAMP",
            "recurrence_count": "2",
            "fail_closed": True,
            "real_submit_allowed": False,
        }]
        ops = sup.summarize_operations(engine, now=NOW)
        self.assertEqual(ops["daily"]["clean_strategy_pnl_per_share_yen"], -4.0)
        self.assertEqual(ops["daily"]["clean_strategy_exit_count"], 1)
        self.assertEqual(ops["daily"]["error_count"], 0)
        self.assertEqual(ops["weekly"]["clean_strategy_pnl_per_share_yen"], 6.0)
        self.assertEqual(ops["weekly"]["clean_strategy_exit_count"], 2)
        self.assertEqual(ops["weekly"]["error_count"], 1)
        self.assertEqual(ops["weekly"]["recurrence"]["live_ms2|STALE_OR_MISSING_TIMESTAMP"], 0)
        self.assertEqual(ops["monthly"]["clean_strategy_exit_count"], 2)
        self.assertIsNone(ops["weekly"]["mttr_seconds"])

    def test_unreadable_recovery_file_does_not_resume_an_open_incident(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        stale = _live([_row()], updated_at="2026-10-02 08:00:00")
        paused_at = NOW + timedelta(seconds=90)
        sup.apply_cycle(engine, stale, sup.assess_live_payload(stale, file_mtime=paused_at, now=paused_at), now=paused_at, data_dir=self.data)
        (self.data / "manual_recovery.json").write_text("{", encoding="utf-8")
        self.assertEqual(sup.read_manual_recovery(self.data), "UNREADABLE")
        recovered = _live([_row(signal="監視", price=1520.0)], updated_at="2026-10-02 09:17:48")
        resume_at = NOW + timedelta(minutes=2)
        sup.apply_cycle(
            engine,
            recovered,
            sup.assess_live_payload(recovered, file_mtime=resume_at, now=resume_at),
            now=resume_at,
            data_dir=self.data,
            recovery_mode="UNREADABLE",
        )
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(engine["state"]["reason"], "RECOVERY_FILE_UNREADABLE")
        self.assertIsNone(engine["incidents"][-1]["recovery_at"])
        self.assertEqual([event for event in engine["ledger"] if event["event_type"] == "virtual_exit"], [])
        self.assertFalse(engine["state"]["real_submit_allowed"])

    def test_run_once_publishes_status_without_a_browser(self):
        live = self.data / "live_ms2.json"
        status = self.data / "ai_shadow_status.json"
        live.write_text(json.dumps(_live([_row()])), encoding="utf-8")
        os_utime = __import__("os").utime
        os_utime(live, (NOW.timestamp(), NOW.timestamp()))
        text = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertNotIn("card_system", text)
        self.assertNotIn("voice_client", text)
        self.assertNotIn("submit_shadow_order", text)
        engine = sup.run_once(self.data, live, status, now=NOW)
        published = json.loads(status.read_text(encoding="utf-8"))
        self.assertTrue(published["ui_independent"])
        self.assertFalse(published["real_submit_allowed"])
        self.assertEqual(published["state"], "RUNNING")
        self.assertEqual(len(engine["open_positions"]), 1)
        sample = _live([_row()], source="sample")
        live.write_text(json.dumps(sample), encoding="utf-8")
        os_utime(live, (NOW.timestamp(), NOW.timestamp()))
        blocked = sup.run_once(self.data, live, status, now=NOW + timedelta(seconds=5))
        self.assertEqual(blocked["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(len(blocked["open_positions"]), 1)
        self.assertFalse(json.loads(status.read_text(encoding="utf-8"))["real_submit_allowed"])
        self.assertNotIn("webbrowser", text)

    def test_unreadable_recovery_file_blocks_a_clean_entry(self):
        engine = self._engine()
        (self.data / "manual_recovery.json").write_text("{", encoding="utf-8")
        fresh = _live([_row()])
        sup.apply_cycle(
            engine,
            fresh,
            sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW),
            now=NOW,
            data_dir=self.data,
            recovery_mode="UNREADABLE",
        )
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(engine["state"]["reason"], "RECOVERY_FILE_UNREADABLE")
        self.assertEqual([event for event in engine["ledger"] if event["event_type"] == "virtual_entry"], [])
        self.assertEqual(engine["incidents"][-1]["error_code"], "RECOVERY_FILE_UNREADABLE")
        self.assertTrue(engine["incidents"][-1]["fail_closed"])
        self.assertFalse(engine["incidents"][-1]["real_submit_allowed"])
        again = NOW + timedelta(seconds=10)
        sup.apply_cycle(
            engine,
            fresh,
            sup.assess_live_payload(fresh, file_mtime=again, now=again),
            now=again,
            data_dir=self.data,
            recovery_mode="UNREADABLE",
        )
        self.assertEqual(len(engine["incidents"]), 1)
        self.assertIsNone(engine["incidents"][0]["recovery_at"])

    def test_opposite_sides_on_one_ticker_do_not_open(self):
        engine = self._engine()
        board = _live([
            _row(signal="買いサイン"),
            _row(signal="空売りサイン", stop_price=1550.0),
        ])
        sup.apply_cycle(engine, board, sup.assess_live_payload(board, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(engine["state"]["reason"], "DATA_CONFLICT")
        self.assertEqual([event for event in engine["ledger"] if event["event_type"] == "virtual_entry"], [])
        self.assertEqual(engine["open_positions"], {})
        self.assertFalse(engine["state"]["real_submit_allowed"])
        self.assertEqual(engine["incidents"][-1]["error_code"], "DATA_CONFLICT")

    def test_duplicate_entry_rows_do_not_open(self):
        engine = self._engine()
        board = _live([_row(price=1500.0), _row(price=1510.0)])
        sup.apply_cycle(engine, board, sup.assess_live_payload(board, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["reason"], "DATA_CONFLICT")
        self.assertEqual(engine["open_positions"], {})
        self.assertFalse(engine["state"]["real_submit_allowed"])

    def test_ledger_quantity_is_not_replayed_as_a_position(self):
        state = sup.fresh_state(now=NOW)
        state["state"] = "RUNNING"
        state["last_seq"] = 1
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        poisoned = {
            "record_class": "shadow_observation",
            "seq": 1,
            "event_type": "virtual_entry",
            "position_key": "285A.T|LONG",
            "real_submit_allowed": False,
            "quantity": 100,
        }
        (self.data / "ledger.jsonl").write_text(json.dumps(poisoned) + "\n", encoding="utf-8")
        (self.data / "incidents.jsonl").write_text("", encoding="utf-8")
        engine = sup.load_engine(self.data, now=NOW)
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["reason"], "LEDGER_CORRUPT")
        self.assertEqual(engine["open_positions"], {})
        self.assertFalse(engine["state"]["real_submit_allowed"])

    def test_overlapping_downtime_stays_inside_zero_and_one(self):
        started = NOW - timedelta(hours=1)
        engine = {"state": sup.fresh_state(now=started), "ledger": [], "incidents": [], "open_positions": {}}
        engine["state"]["engine_started_at"] = started.isoformat()
        engine["incidents"] = [
            {
                "occurrence_at": started.isoformat(),
                "recovery_at": NOW.isoformat(),
                "duration_seconds": 3600,
                "error_code": "STALE_OR_MISSING_TIMESTAMP",
                "recurrence_key": "live_ms2|STALE_OR_MISSING_TIMESTAMP",
                "recurrence_count": 1,
            },
            {
                "occurrence_at": started.isoformat(),
                "recovery_at": NOW.isoformat(),
                "duration_seconds": 3600,
                "error_code": "DATA_CONFLICT",
                "recurrence_key": "price_source|DATA_CONFLICT",
                "recurrence_count": 1,
            },
        ]
        ops = sup.summarize_operations(engine, now=NOW)
        self.assertEqual(ops["daily"]["shadow_uptime_ratio"], 0.0)
        self.assertGreater(ops["daily"]["total_downtime_seconds"], 3600)
        self.assertEqual(ops["weekly"]["shadow_uptime_ratio"], 0.0)
        self.assertEqual(ops["monthly"]["shadow_uptime_ratio"], 0.0)

    def test_state_machine_stops_pauses_recovers_and_runs(self):
        self.assertEqual(sup.STATES, ("RUNNING", "PAUSED_FAIL_CLOSED", "RECOVERING", "STOPPED"))
        engine = self._engine()
        self.assertEqual(engine["state"]["state"], "STOPPED")
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "RUNNING")
        stale = _live([_row()], updated_at="2026-10-02 08:00:00")
        paused_at = NOW + timedelta(seconds=90)
        sup.apply_cycle(engine, stale, sup.assess_live_payload(stale, file_mtime=paused_at, now=paused_at), now=paused_at, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        restarted = sup.load_engine(self.data, now=paused_at + timedelta(seconds=5))
        self.assertEqual(restarted["state"]["state"], "RECOVERING")
        self.assertEqual(len(restarted["open_positions"]), 1)
        resume_at = NOW + timedelta(minutes=2)
        recovered = _live([_row()], updated_at="2026-10-02 09:18:05")
        sup.apply_cycle(restarted, recovered, sup.assess_live_payload(recovered, file_mtime=resume_at, now=resume_at), now=resume_at, data_dir=self.data)
        self.assertEqual(restarted["state"]["state"], "RUNNING")
        self.assertEqual(len([event for event in restarted["ledger"] if event["event_type"] == "virtual_entry"]), 1)

    def test_unsafe_payloads_do_not_enter_or_exit(self):
        cases = [
            ("stale", _live([_row(price=1.0, signal="監視")], updated_at="2026-10-02 08:00:00"), "STALE_OR_MISSING_TIMESTAMP"),
            ("mismatch", _live([_row(price=1.0, signal="監視")], price_source_status="PRICE_SOURCE_MISMATCH"), "PRICE_SOURCE_MISMATCH"),
            ("conflict", _live([_row(price=1.0, signal="監視")], data_conflict=True), "DATA_CONFLICT"),
            ("sample", _live([_row(price=1.0, signal="監視")], source="sample"), "CACHED_OR_SAMPLE_PAYLOAD"),
            ("collector", _live([_row(price=1.0, signal="監視")], live_price_diagnostics=_diag(collector_count=None)), "COLLECTOR_PROCESS_UNVERIFIED"),
        ]
        for name, bad, reason in cases:
            with self.subTest(name=name, phase="entry"):
                engine = sup.load_engine(self.data, now=NOW)
                moment = NOW
                sup.apply_cycle(engine, bad, sup.assess_live_payload(bad, file_mtime=moment, now=moment), now=moment, data_dir=self.data)
                self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
                self.assertEqual(engine["state"]["reason"], reason)
                self.assertEqual(engine["open_positions"], {})
                self.assertEqual([event for event in engine["ledger"] if event["event_type"] in {"virtual_entry", "virtual_exit"}], [])
                self.assertFalse(engine["state"]["real_submit_allowed"])
                for child in self.data.iterdir():
                    child.unlink()
        for name, bad, reason in cases:
            with self.subTest(name=name, phase="exit"):
                engine = sup.load_engine(self.data, now=NOW)
                fresh = _live([_row()])
                sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
                self.assertEqual(len(engine["open_positions"]), 1)
                moment = NOW + timedelta(seconds=30)
                sup.apply_cycle(engine, bad, sup.assess_live_payload(bad, file_mtime=moment, now=moment), now=moment, data_dir=self.data)
                self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
                self.assertEqual(engine["state"]["reason"], reason)
                self.assertEqual(len(engine["open_positions"]), 1)
                self.assertEqual([event for event in engine["ledger"] if event["event_type"] == "virtual_exit"], [])
                self.assertEqual(len([event for event in engine["ledger"] if event["event_type"] == "virtual_entry"]), 1)
                self.assertFalse(engine["state"]["real_submit_allowed"])
                for child in self.data.iterdir():
                    child.unlink()

    def test_mismatched_or_missing_files_do_not_resume(self):
        fresh = _live([_row()])

        def refuse(reason: str):
            engine = sup.load_engine(self.data, now=NOW)
            self.assertTrue(engine["state"]["resume_blocked"])
            self.assertEqual(engine["state"]["reason"], reason)
            sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
            self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
            self.assertEqual(engine["open_positions"], {})
            self.assertEqual([event for event in engine["ledger"] if event["event_type"] == "virtual_entry"], [])
            self.assertFalse(engine["state"]["real_submit_allowed"])
            for child in self.data.iterdir():
                child.unlink()

        (self.data / "ledger.jsonl").write_text("", encoding="utf-8")
        refuse("STATE_MISSING")

        (self.data / "state.json").write_text("{", encoding="utf-8")
        refuse("STATE_UNREADABLE")

        state = sup.fresh_state(now=NOW)
        state["state"] = "RUNNING"
        state["last_seq"] = 2
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (self.data / "ledger.jsonl").write_text("", encoding="utf-8")
        refuse("LEDGER_STATE_MISMATCH")

        state["last_seq"] = 0
        state["open_incident_id"] = "inc-missing"
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (self.data / "ledger.jsonl").write_text("", encoding="utf-8")
        refuse("INCIDENT_LOG_MISSING")

        state = sup.fresh_state(now=NOW)
        state["state"] = "TRADING"
        state["last_seq"] = 0
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (self.data / "ledger.jsonl").write_text("", encoding="utf-8")
        (self.data / "incidents.jsonl").write_text("", encoding="utf-8")
        refuse("UNKNOWN_STATE")

        observation = {
            "record_class": "shadow_observation",
            "seq": 1,
            "event_type": "board_judgment",
            "real_submit_allowed": False,
            "quantity": None,
        }
        state = sup.fresh_state(now=NOW)
        state["state"] = "RUNNING"
        state["last_seq"] = 0
        (self.data / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (self.data / "ledger.jsonl").write_text(json.dumps(observation) + "\n", encoding="utf-8")
        (self.data / "incidents.jsonl").write_text("", encoding="utf-8")
        refuse("LEDGER_STATE_MISMATCH")

    def test_same_fingerprint_appends_nothing(self):
        engine = self._engine()
        fresh = _live([_row()])
        verdict = sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW)
        sup.apply_cycle(engine, fresh, verdict, now=NOW, data_dir=self.data)
        before = len(engine["ledger"])
        fingerprint = engine["state"]["seen_board_fingerprints"]
        sup.apply_cycle(engine, fresh, verdict, now=NOW + timedelta(seconds=5), data_dir=self.data)
        self.assertEqual(len(engine["ledger"]), before)
        self.assertEqual(engine["state"]["seen_board_fingerprints"], fingerprint)
        self.assertEqual(engine["state"]["state"], "RUNNING")
        self.assertEqual(len([event for event in engine["ledger"] if event["event_type"] == "virtual_entry"]), 1)

    def test_split_ticker_rows_do_not_exit_or_reenter(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        later = NOW + timedelta(seconds=20)
        split = _live([
            _row(signal="監視", price=1550.0),
            _row(signal="買いサイン", price=1500.0),
        ], updated_at="2026-10-02 09:16:25")
        sup.apply_cycle(engine, split, sup.assess_live_payload(split, file_mtime=later, now=later), now=later, data_dir=self.data)
        self.assertEqual(engine["state"]["state"], "PAUSED_FAIL_CLOSED")
        self.assertEqual(engine["state"]["reason"], "DATA_CONFLICT")
        self.assertEqual(len(engine["open_positions"]), 1)
        self.assertEqual([event for event in engine["ledger"] if event["event_type"] == "virtual_exit"], [])
        self.assertEqual(len([event for event in engine["ledger"] if event["event_type"] == "virtual_entry"]), 1)
        self.assertFalse(engine["state"]["real_submit_allowed"])

    def test_observation_and_incident_logs_stay_in_their_classes(self):
        engine = self._engine()
        fresh = _live([_row()])
        sup.apply_cycle(engine, fresh, sup.assess_live_payload(fresh, file_mtime=NOW, now=NOW), now=NOW, data_dir=self.data)
        entries = [event for event in engine["ledger"] if event["event_type"] == "virtual_entry"]
        self.assertEqual(entries[0]["record_class"], "shadow_observation")
        self.assertEqual(entries[0]["performance_bucket"], "open_unrealized_not_marked")
        self.assertIsNone(entries[0]["quantity"])
        self.assertFalse(entries[0]["real_submit_allowed"])
        for line in (self.data / "ledger.jsonl").read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            self.assertEqual(row["record_class"], "shadow_observation")
            self.assertFalse(row["real_submit_allowed"])
            self.assertIsNone(row["quantity"])
        stale = _live([_row()], updated_at="2026-10-02 08:00:00")
        paused_at = NOW + timedelta(seconds=90)
        sup.apply_cycle(engine, stale, sup.assess_live_payload(stale, file_mtime=paused_at, now=paused_at), now=paused_at, data_dir=self.data)
        incident_lines = (self.data / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(incident_lines), 1)
        incident = json.loads(incident_lines[0])
        self.assertEqual(incident["record_class"], "operations_incident")
        self.assertTrue(incident["fail_closed"])
        self.assertFalse(incident["real_submit_allowed"])
        self.assertIsNone(incident["recovery_at"])
        ops = sup.summarize_operations(engine, now=paused_at)
        for label in ("daily", "weekly", "monthly"):
            self.assertEqual(ops[label]["label"], label)
            self.assertEqual(ops[label]["error_count"], 1)
            self.assertIsNone(ops[label]["clean_strategy_pnl_per_share_yen"])
            self.assertEqual(ops[label]["clean_strategy_exit_count"], 0)
        self.assertTrue(sup.status_snapshot(engine, now=paused_at)["ui_independent"])


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
        supervisor = (ROOT / "scripts" / "ai_shadow_supervisor.py").read_text(encoding="utf-8")
        self.assertNotIn("submit_shadow_order", supervisor)
        self.assertNotIn("RssOrder", supervisor)
        self.assertNotIn("index.html", supervisor)
        self.assertNotIn('real_submit_allowed"] = True', supervisor)
        self.assertNotIn("real_submit_allowed = True", supervisor)
        self.assertIn('"-u", $scriptPath', controller)
        self.assertIn('"--live", (Join-Path $RuntimeDir "live_ms2.json")', controller)
        self.assertIn("-WindowStyle Hidden", controller)


if __name__ == "__main__":
    unittest.main()
