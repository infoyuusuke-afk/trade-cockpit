import json
import unittest
from unittest import mock

from scripts import build_ai_strategy_live as b
from scripts import strategy_router
from scripts.ai_strategy_live import SUPERVISORS


NOW = "2026-09-22T20:30:00+09:00"


def fixture_signals():
    return {
        "updated_at": "2026-09-22 20:23:54 JST",
        "overnight_long": [
            {"ticker": "285A.T", "trigger": 55000, "stop": 53500, "target1": 57000,
             "score": 80, "signal_date": "2026-09-22"},
        ],
        "overnight_short": [
            {"ticker": "6902.T", "trigger": 1914, "stop": 1959, "target1": 1846,
             "score": 75, "signal_date": "2026-09-22"},
        ],
        "speculative_theme_watch": [
            {"ticker": "485A.T", "score": 73},
        ],
        "monthly_weekly_hammers": [
            {"ticker": "6501.T", "trigger": 5580, "stop": 5035, "target1": 6400,
             "score": 87, "signal_date": "2026-09-22"},
        ],
        "prepared": [
            {"ticker": "3132.T", "trigger": 4125, "stop": 3990, "target1": 4250,
             "score": 95, "signal_date": "2026-09-22"},
        ],
        "large_lot_accumulation": [
            {"ticker": "6920.T", "trigger": 39850, "stop": 33150, "target1": 49900,
             "score": 88, "signal_date": "2026-09-22"},
        ],
        "long_term_ma_rebounds_unverified": [
            {"ticker": "6481.T", "trigger": 6280, "stop": 5650, "target1": 7225,
             "score": 100, "signal_date": "2026-09-22"},
        ],
    }


class BuildStatesTests(unittest.TestCase):
    def test_overnight_long_and_short_directions(self):
        states, unresolved = b.build_states(fixture_signals(), NOW)
        self.assertEqual(unresolved, [])
        by_symbol = {(s["supervisor"], s["symbol"]): s["direction"] for s in states}
        self.assertEqual(by_symbol[("OVERNIGHT", "285A.T")], "LONG")
        self.assertEqual(by_symbol[("OVERNIGHT", "6902.T")], "SHORT")

    def test_event_is_always_watch_never_long_or_short(self):
        states, _ = b.build_states(fixture_signals(), NOW)
        event_states = [s for s in states if s["supervisor"] == "EVENT"]
        self.assertTrue(event_states)
        self.assertTrue(all(s["direction"] == "WATCH" for s in event_states))

    def test_swing_is_long_watch(self):
        states, _ = b.build_states(fixture_signals(), NOW)
        swing = [s for s in states if s["supervisor"] == "SWING"]
        self.assertEqual(swing[0]["direction"], "LONG_WATCH")

    def test_rows_missing_ticker_are_skipped_not_guessed(self):
        signals = fixture_signals()
        signals["overnight_long"].append({"trigger": 100, "stop": 90, "score": 50})
        states, unresolved = b.build_states(signals, NOW)
        overnight = [s for s in states if s["supervisor"] == "OVERNIGHT" and s["direction"] == "LONG"]
        self.assertEqual(len(overnight), 1)
        self.assertEqual(unresolved, [])  # a missing ticker is simply dropped, not an "issue" row

    def test_provenance_names_exact_upstream_field(self):
        states, _ = b.build_states(fixture_signals(), NOW)
        by_symbol = {s["symbol"]: s["provenance"] for s in states if s["supervisor"] == "OVERNIGHT" and s["direction"] == "LONG"}
        self.assertEqual(by_symbol["285A.T"], "signals.json:overnight_long")

    def test_empty_signals_produces_no_states(self):
        self.assertEqual(b.build_states({}, NOW), ([], []))

    def test_scalp_is_long_watch_not_a_firm_long(self):
        states, _ = b.build_states(fixture_signals(), NOW)
        scalp = [s for s in states if s["supervisor"] == "SCALP"]
        self.assertEqual(scalp[0]["direction"], "LONG_WATCH")
        self.assertEqual(scalp[0]["provenance"], "signals.json:prepared")

    def test_value_long_catalyst_accumulation_is_long_watch(self):
        states, _ = b.build_states(fixture_signals(), NOW)
        vlc = {s["symbol"]: s for s in states if s["supervisor"] == "VALUE_LONG_CATALYST"}
        self.assertEqual(vlc["6920.T"]["direction"], "LONG_WATCH")
        self.assertEqual(vlc["6920.T"]["provenance"], "signals.json:large_lot_accumulation")

    def test_value_long_catalyst_unverified_rebound_is_watch_not_long_watch(self):
        states, _ = b.build_states(fixture_signals(), NOW)
        vlc = {s["symbol"]: s for s in states if s["supervisor"] == "VALUE_LONG_CATALYST"}
        self.assertEqual(vlc["6481.T"]["direction"], "WATCH")
        self.assertEqual(vlc["6481.T"]["provenance"], "signals.json:long_term_ma_rebounds_unverified")

    def test_value_long_catalyst_overlap_resolves_to_more_cautious_watch(self):
        signals = fixture_signals()
        # same ticker in both sources -- must not silently drop one
        signals["long_term_ma_rebounds_unverified"].append(
            {"ticker": "6920.T", "trigger": 40000, "stop": 35000, "target1": 45000,
             "score": 90, "signal_date": "2026-09-22"}
        )
        states, _ = b.build_states(signals, NOW)
        vlc_6920 = [s for s in states if s["supervisor"] == "VALUE_LONG_CATALYST" and s["symbol"] == "6920.T"]
        self.assertEqual(len(vlc_6920), 1)  # one Supervisor, one state per symbol -- not silently two
        self.assertEqual(vlc_6920[0]["direction"], "WATCH")

    def test_event_as_of_uses_signals_updated_at_not_now(self):
        signals = fixture_signals()
        states, _ = b.build_states(signals, "2026-09-25T09:00:00+09:00")  # a different "now"
        event = [s for s in states if s["supervisor"] == "EVENT"][0]
        self.assertEqual(event["as_of"], "2026-09-22T20:23:54+09:00")

    def test_malformed_updated_at_never_falls_back_to_now(self):
        # No usable timestamp anywhere for EVENT rows (they have no
        # per-row signal_date of their own) -> excluded as a data issue,
        # never silently stamped with "now" to look artificially fresh.
        signals = fixture_signals()
        signals["updated_at"] = "not a timestamp"
        states, unresolved = b.build_states(signals, NOW)
        self.assertFalse([s for s in states if s["supervisor"] == "EVENT"])
        event_issues = [u for u in unresolved if u["supervisor"] == "EVENT"]
        self.assertEqual(len(event_issues), 1)
        self.assertEqual(event_issues[0]["reason"], "TIMESTAMP_UNAVAILABLE")
        self.assertEqual(event_issues[0]["symbol"], "485A.T")

    def test_row_missing_signal_date_falls_back_to_signals_as_of(self):
        # OVERNIGHT/SWING/SCALP/VALUE_LONG_CATALYST rows *do* have their
        # own signal_date normally; if a row is missing it but
        # signals.json's own updated_at is valid, that's still an honest
        # timestamp, not "now".
        signals = fixture_signals()
        del signals["overnight_long"][0]["signal_date"]
        states, unresolved = b.build_states(signals, NOW)
        row = next(s for s in states if s["supervisor"] == "OVERNIGHT" and s["symbol"] == "285A.T")
        self.assertEqual(row["as_of"], "2026-09-22T20:23:54+09:00")
        self.assertEqual(unresolved, [])

    def test_row_and_updated_at_both_missing_becomes_data_issue(self):
        signals = fixture_signals()
        del signals["overnight_long"][0]["signal_date"]
        signals["updated_at"] = ""
        states, unresolved = b.build_states(signals, NOW)
        self.assertFalse([s for s in states if s["supervisor"] == "OVERNIGHT" and s["symbol"] == "285A.T"])
        issue = next(u for u in unresolved if u["supervisor"] == "OVERNIGHT" and u["symbol"] == "285A.T")
        self.assertEqual(issue["reason"], "TIMESTAMP_UNAVAILABLE")
        self.assertEqual(issue["provenance"], "signals.json:overnight_long")


class BuildArtifactTests(unittest.TestCase):
    def test_refuses_to_run_if_feature_flag_ever_flips_on(self):
        with mock.patch.object(b, "FEATURE_FLAG_LIVE_INFLUENCE_ENABLED", True):
            with self.assertRaises(AssertionError):
                b.build_artifact(fixture_signals(), NOW)

    def test_top_level_shape(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        self.assertEqual(artifact["schema_version"], "ai-strategy-live-board-1.0")
        self.assertFalse(artifact["feature_flag_enabled"])
        self.assertFalse(artifact["is_entry_trigger"])
        self.assertFalse(artifact["real_submit_allowed"])
        self.assertEqual(len(artifact["board"]), 7)

    def test_json_serializable(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        json.dumps(artifact, ensure_ascii=False)  # must not raise

    def test_data_quality_unknown_by_default_never_fabricated_ok(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        self.assertFalse(artifact["data_quality_connected"])
        for card in artifact["board"]:
            self.assertIsNone(card["router"]["data_quality_ok"])

    def test_stale_daily_signal_reported_unknown_not_hidden(self):
        signals = fixture_signals()
        signals["overnight_long"][0]["signal_date"] = "2026-09-10"  # far in the past
        artifact = b.build_artifact(signals, NOW)
        card = next(c for c in artifact["board"] if c["symbol"] == "285A.T")
        self.assertEqual(card["router"]["state"], "UNKNOWN")
        self.assertIn("STALE_SUPERVISOR_DATA", card["router"]["reasons"])

    def test_never_produces_a_buy_or_short_router_state(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        for card in artifact["board"]:
            self.assertIn(card["router"]["state"], strategy_router.STATES)

    def test_connected_and_unconnected_supervisors_are_disjoint_and_complete(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        connected = set(artifact["connected_supervisors"])
        unconnected = set(artifact["unconnected_supervisors"])
        self.assertEqual(connected, b.CONNECTED_SUPERVISORS)
        self.assertEqual(connected | unconnected, set(SUPERVISORS))
        self.assertEqual(connected & unconnected, set())

    def test_data_issues_surfaced_in_artifact(self):
        signals = fixture_signals()
        signals["updated_at"] = "garbage"
        artifact = b.build_artifact(signals, NOW)
        self.assertTrue(artifact["data_issues"])
        self.assertTrue(all(i["reason"] == "TIMESTAMP_UNAVAILABLE" for i in artifact["data_issues"]))

    def test_per_lane_freshness_distinguishes_overnight_from_swing(self):
        # Same age (~53h), different lanes: OVERNIGHT's 20h window must
        # flag it stale; SWING's 5-day (120h) window must not.
        signals = fixture_signals()
        signals["overnight_long"][0]["signal_date"] = "2026-09-20"
        signals["monthly_weekly_hammers"][0]["signal_date"] = "2026-09-20"
        artifact = b.build_artifact(signals, NOW)
        overnight_card = next(c for c in artifact["board"] if c["symbol"] == "285A.T")
        swing_card = next(c for c in artifact["board"] if c["symbol"] == "6501.T")
        self.assertIn("OVERNIGHT", overnight_card["router"]["stale_supervisors"])
        self.assertNotIn("SWING", swing_card["router"]["stale_supervisors"])

    def test_no_execution_module_imported(self):
        import scripts.build_ai_strategy_live as mod
        with open(mod.__file__, encoding="utf-8") as f:
            import_lines = [ln for ln in f if ln.startswith("import ") or ln.startswith("from ")]
        joined = "".join(import_lines)
        for forbidden in ("execution_permission", "shadow_execution", "shadow_position",
                           "conflict_resolver", "rss_order", "broker"):
            self.assertNotIn(forbidden, joined.lower())


if __name__ == "__main__":
    unittest.main()
