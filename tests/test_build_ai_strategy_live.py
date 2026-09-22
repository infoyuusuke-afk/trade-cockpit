import json
import unittest
from unittest import mock

from scripts import build_ai_strategy_live as b
from scripts import strategy_router


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
    }


class BuildStatesTests(unittest.TestCase):
    def test_overnight_long_and_short_directions(self):
        states = b.build_states(fixture_signals(), NOW)
        by_symbol = {(s["supervisor"], s["symbol"]): s["direction"] for s in states}
        self.assertEqual(by_symbol[("OVERNIGHT", "285A.T")], "LONG")
        self.assertEqual(by_symbol[("OVERNIGHT", "6902.T")], "SHORT")

    def test_event_is_always_watch_never_long_or_short(self):
        states = b.build_states(fixture_signals(), NOW)
        event_states = [s for s in states if s["supervisor"] == "EVENT"]
        self.assertTrue(event_states)
        self.assertTrue(all(s["direction"] == "WATCH" for s in event_states))

    def test_swing_is_long_watch(self):
        states = b.build_states(fixture_signals(), NOW)
        swing = [s for s in states if s["supervisor"] == "SWING"]
        self.assertEqual(swing[0]["direction"], "LONG_WATCH")

    def test_rows_missing_ticker_are_skipped_not_guessed(self):
        signals = fixture_signals()
        signals["overnight_long"].append({"trigger": 100, "stop": 90, "score": 50})
        states = b.build_states(signals, NOW)
        overnight = [s for s in states if s["supervisor"] == "OVERNIGHT" and s["direction"] == "LONG"]
        self.assertEqual(len(overnight), 1)

    def test_provenance_names_exact_upstream_field(self):
        states = b.build_states(fixture_signals(), NOW)
        by_symbol = {s["symbol"]: s["provenance"] for s in states if s["supervisor"] == "OVERNIGHT" and s["direction"] == "LONG"}
        self.assertEqual(by_symbol["285A.T"], "signals.json:overnight_long")

    def test_empty_signals_produces_no_states(self):
        self.assertEqual(b.build_states({}, NOW), [])

    def test_event_as_of_uses_signals_updated_at_not_now(self):
        signals = fixture_signals()
        states = b.build_states(signals, "2026-09-25T09:00:00+09:00")  # a different "now"
        event = [s for s in states if s["supervisor"] == "EVENT"][0]
        self.assertEqual(event["as_of"], "2026-09-22T20:23:54+09:00")

    def test_malformed_updated_at_falls_back_to_now_not_a_guessed_date(self):
        signals = fixture_signals()
        signals["updated_at"] = "not a timestamp"
        states = b.build_states(signals, NOW)
        event = [s for s in states if s["supervisor"] == "EVENT"][0]
        self.assertEqual(event["as_of"], NOW)


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
        self.assertEqual(len(artifact["board"]), 4)

    def test_json_serializable(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        json.dumps(artifact, ensure_ascii=False)  # must not raise

    def test_data_quality_unknown_by_default_never_fabricated_ok(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
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
