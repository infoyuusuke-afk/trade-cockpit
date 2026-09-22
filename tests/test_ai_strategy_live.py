import unittest
from scripts import ai_strategy_live as live
from scripts import event_bus
from scripts import journal_projection
from scripts import public_event_sanitizer


def state(supervisor, symbol, direction, as_of, **extra):
    return live.build_supervisor_state(supervisor=supervisor, symbol=symbol, direction=direction, as_of=as_of, **extra)


class BuildSupervisorStateTests(unittest.TestCase):
    def test_valid(self):
        s = state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00", entry=1000, stop=980)
        self.assertEqual(s["direction"], "LONG")
        self.assertFalse(s["is_entry_trigger"])
        self.assertFalse(s["real_submit_allowed"])

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            live.build_supervisor_state(supervisor="SCALP", symbol="285A.T", direction="LONG",
                                         as_of="2026-09-22T10:00:00+09:00", account_id="123")

    def test_missing_required_rejected(self):
        with self.assertRaises(ValueError):
            live.build_supervisor_state(supervisor="SCALP", symbol="285A.T", direction="LONG")

    def test_unknown_supervisor_rejected(self):
        with self.assertRaises(ValueError):
            state("MYSTERY_SUPERVISOR", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")

    def test_unknown_direction_rejected(self):
        with self.assertRaises(ValueError):
            state("SCALP", "285A.T", "MOON", "2026-09-22T10:00:00+09:00")

    def test_naive_as_of_rejected(self):
        with self.assertRaises(ValueError):
            state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00")

    def test_optional_fields_default_none(self):
        s = state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")
        self.assertIsNone(s["entry"])
        self.assertIsNone(s["historical_ev"])

    def test_all_sixteen_supervisors_accepted(self):
        for key in live.SUPERVISORS:
            state(key, "285A.T", "NEUTRAL", "2026-09-22T10:00:00+09:00")


class StrategyLiveSnapshotTests(unittest.TestCase):
    NOW = "2026-09-22T10:05:00+09:00"

    def test_coexisting_directions_are_preserved_not_collapsed(self):
        states = [
            state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
            state("REALTIME_DAYTRADE", "285A.T", "WATCH", "2026-09-22T10:00:00+09:00"),
            state("OVERNIGHT", "285A.T", "BLOCK", "2026-09-22T10:00:00+09:00"),
            state("SWING", "285A.T", "LONG_WATCH", "2026-09-22T10:00:00+09:00"),
            state("VALUE_LONG_CATALYST", "285A.T", "NEUTRAL", "2026-09-22T10:00:00+09:00"),
        ]
        snap = live.strategy_live_snapshot(states, self.NOW)
        supervisors = snap["285A.T"]["supervisors"]
        self.assertEqual(supervisors["SCALP"]["direction"], "LONG")
        self.assertEqual(supervisors["OVERNIGHT"]["direction"], "BLOCK")
        self.assertEqual(len(supervisors), 5)

    def test_no_conflict_when_horizons_agree(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
                  state("SWING", "285A.T", "LONG_WATCH", "2026-09-22T10:00:00+09:00")]
        self.assertFalse(live.strategy_live_snapshot(states, self.NOW)["285A.T"]["conflict"])

    def test_conflict_on_long_vs_short(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
                  state("OVERNIGHT", "285A.T", "SHORT_WATCH", "2026-09-22T10:00:00+09:00")]
        self.assertTrue(live.strategy_live_snapshot(states, self.NOW)["285A.T"]["conflict"])

    def test_conflict_on_long_vs_block(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
                  state("OVERNIGHT", "285A.T", "BLOCK", "2026-09-22T10:00:00+09:00")]
        self.assertTrue(live.strategy_live_snapshot(states, self.NOW)["285A.T"]["conflict"])

    def test_non_horizon_supervisor_does_not_trigger_conflict(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
                  state("RISK_SAFETY", "285A.T", "BLOCK", "2026-09-22T10:00:00+09:00")]
        self.assertFalse(live.strategy_live_snapshot(states, self.NOW)["285A.T"]["conflict"])

    def test_last_update_age_seconds(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, "2026-09-22T10:05:00+09:00")
        self.assertAlmostEqual(snap["285A.T"]["supervisors"]["SCALP"]["last_update_age_seconds"], 300.0)

    def test_snapshot_never_an_entry_trigger(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, self.NOW)
        self.assertFalse(snap["285A.T"]["real_submit_allowed"])
        self.assertFalse(snap["285A.T"]["is_entry_trigger"])


class SupervisorStateEventsTests(unittest.TestCase):
    def test_first_report_of_candidate_direction_activates(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        events = live.supervisor_state_events(event_bus.build_event, states)
        types = [e["event_type"] for e in events]
        self.assertIn("SUPERVISOR_STATE_CHANGED", types)
        self.assertIn("STRATEGY_CANDIDATE_ACTIVATED", types)

    def test_unchanged_direction_emits_nothing(self):
        prev = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        cur = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:05:00+09:00")]
        self.assertEqual(live.supervisor_state_events(event_bus.build_event, cur, prev), [])

    def test_candidate_to_watch_invalidates(self):
        prev = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        cur = [state("SCALP", "285A.T", "WATCH", "2026-09-22T10:05:00+09:00")]
        events = live.supervisor_state_events(event_bus.build_event, cur, prev)
        types = [e["event_type"] for e in events]
        self.assertIn("STRATEGY_INVALIDATED", types)
        self.assertNotIn("STRATEGY_CANDIDATE_ACTIVATED", types)

    def test_conflict_detected_fires_once_on_transition_to_true(self):
        prev = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        cur = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:05:00+09:00"),
               state("OVERNIGHT", "285A.T", "SHORT", "2026-09-22T10:05:00+09:00")]
        events = live.supervisor_state_events(event_bus.build_event, cur, prev)
        conflict_events = [e for e in events if e["event_type"] == "CONFLICT_DETECTED"]
        self.assertEqual(len(conflict_events), 1)

    def test_conflict_does_not_refire_while_still_true(self):
        prev = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
                state("OVERNIGHT", "285A.T", "SHORT", "2026-09-22T10:00:00+09:00")]
        cur = [state("SCALP", "285A.T", "LONG_WATCH", "2026-09-22T10:05:00+09:00"),
               state("OVERNIGHT", "285A.T", "SHORT", "2026-09-22T10:05:00+09:00")]
        events = live.supervisor_state_events(event_bus.build_event, cur, prev)
        conflict_events = [e for e in events if e["event_type"] == "CONFLICT_DETECTED"]
        self.assertEqual(len(conflict_events), 0)

    def test_events_are_valid_event_bus_events(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        for e in live.supervisor_state_events(event_bus.build_event, states):
            self.assertTrue(event_bus.validate_event(e))
            self.assertFalse(e["real_submit_allowed"])
            self.assertFalse(e["external_publish_allowed"])

    def test_rich_events_flow_into_internal_journal_projection(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00", entry=1000, stop=980)]
        events = live.supervisor_state_events(event_bus.build_event, states)
        rows = journal_projection.journal_rows(events)
        self.assertTrue(any(r["category"] == "STRATEGY" for r in rows))


class ExternalJournalEventsTests(unittest.TestCase):
    def test_external_events_pass_sanitizer_unmodified(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        for e in live.external_journal_events(event_bus.build_event, states):
            sanitized = public_event_sanitizer.sanitize_event(e)
            self.assertTrue(public_event_sanitizer.validate_sanitized_event(sanitized))

    def test_external_events_carry_no_price_or_account_fields(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00", entry=1000, stop=980, target=1050)]
        for e in live.external_journal_events(event_bus.build_event, states):
            self.assertEqual(set(e["payload"]), {"summary"})

    def test_same_transitions_as_internal_events(self):
        prev = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        cur = [state("SCALP", "285A.T", "WATCH", "2026-09-22T10:05:00+09:00")]
        internal = live.supervisor_state_events(event_bus.build_event, cur, prev)
        external = live.external_journal_events(event_bus.build_event, cur, prev)
        self.assertEqual([e["event_type"] for e in internal], [e["event_type"] for e in external])


class DailyStrategySummaryEventTests(unittest.TestCase):
    def test_counts(self):
        states = [
            state("SCALP", "285A.T", "LONG", "2026-09-22T15:25:00+09:00"),
            state("OVERNIGHT", "9984.T", "SHORT", "2026-09-22T15:25:00+09:00"),
            state("SWING", "8035.T", "WATCH", "2026-09-22T15:25:00+09:00"),
        ]
        e = live.daily_strategy_summary_event(event_bus.build_event, states, "2026-09-22")
        self.assertEqual(e["event_type"], "DAILY_STRATEGY_SUMMARY")
        self.assertEqual(e["payload"]["symbol_count"], 3)
        self.assertEqual(e["payload"]["candidate_count"], 2)
        self.assertEqual(e["payload"]["watch_count"], 1)

    def test_empty_states_does_not_crash(self):
        e = live.daily_strategy_summary_event(event_bus.build_event, [], "2026-09-22")
        self.assertEqual(e["payload"]["symbol_count"], 0)

    def test_external_variant_is_summary_only(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T15:25:00+09:00")]
        e = live.external_daily_strategy_summary_event(event_bus.build_event, states, "2026-09-22")
        self.assertEqual(set(e["payload"]), {"summary"})
        sanitized = public_event_sanitizer.sanitize_event(e)
        self.assertTrue(public_event_sanitizer.validate_sanitized_event(sanitized))


if __name__ == "__main__":
    unittest.main()
