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
            {"ticker": "285A.T", "name": "キオクシアHD（285A）", "trigger": 55000, "stop": 53500, "target1": 57000,
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
        "long_term_ma_rebounds": [
            {"ticker": "6481.T", "trigger": 6280, "stop": 5650, "target1": 7225,
             "score": 100, "signal_date": "2026-09-22"},
        ],
        "prepared": [
            {"ticker": "3132.T", "name": "マクニカHD（3132）", "trigger": 4125, "stop": 3990, "target1": 4250,
             "score": 95, "signal_date": "2026-09-22"},
        ],
        "large_lot_accumulation": [
            {"ticker": "6920.T", "name": "レーザーテック（6920）", "trigger": 39850, "stop": 33150, "target1": 49900,
             "score": 88, "signal_date": "2026-09-22"},
            # same ticker as an OVERNIGHT TOP5 pick -- must merge into that
            # one card's lanes, never spawn a separate watchlist row.
            {"ticker": "285A.T", "trigger": 54000, "stop": 52000, "target1": 58000,
             "score": 70, "signal_date": "2026-09-22"},
        ],
    }


class BuildStatesTests(unittest.TestCase):
    def test_overnight_long_and_short_directions(self):
        states, unresolved, card_symbols, _ = b.build_states(fixture_signals(), NOW)
        self.assertEqual(unresolved, [])
        by_symbol = {(s["supervisor"], s["symbol"]): s["direction"] for s in states}
        self.assertEqual(by_symbol[("OVERNIGHT", "285A.T")], "LONG")
        self.assertEqual(by_symbol[("OVERNIGHT", "6902.T")], "SHORT")

    def test_event_is_always_watch_never_long_or_short(self):
        states, _, _, _ = b.build_states(fixture_signals(), NOW)
        event_states = [s for s in states if s["supervisor"] == "EVENT"]
        self.assertTrue(event_states)
        self.assertTrue(all(s["direction"] == "WATCH" for s in event_states))

    def test_swing_is_not_mapped(self):
        # No verified existing-TOP5 source was found for the real SWING 5
        # tab (see module docstring) -- this module must not emit SWING
        # states or claim SWING as connected.
        states, _, _, _ = b.build_states(fixture_signals(), NOW)
        self.assertFalse([s for s in states if s["supervisor"] == "SWING"])
        self.assertNotIn("SWING", b.CONNECTED_SUPERVISORS)

    def test_rows_missing_ticker_are_skipped_not_guessed(self):
        signals = fixture_signals()
        signals["overnight_long"].append({"trigger": 100, "stop": 90, "score": 50})
        states, unresolved, _, _ = b.build_states(signals, NOW)
        overnight = [s for s in states if s["supervisor"] == "OVERNIGHT" and s["direction"] == "LONG"]
        self.assertEqual(len(overnight), 1)
        self.assertEqual(unresolved, [])  # a missing ticker is simply dropped, not an "issue" row

    def test_provenance_names_exact_upstream_field(self):
        states, _, _, _ = b.build_states(fixture_signals(), NOW)
        by_symbol = {s["symbol"]: s["provenance"] for s in states if s["supervisor"] == "OVERNIGHT" and s["direction"] == "LONG"}
        self.assertEqual(by_symbol["285A.T"], "signals.json:overnight_long")

    def test_empty_signals_produces_no_states(self):
        states, unresolved, card_symbols, symbol_names = b.build_states({}, NOW)
        self.assertEqual((states, unresolved), ([], []))
        self.assertEqual(card_symbols, set())
        self.assertEqual(symbol_names, {})

    def test_symbol_names_collected_from_signals_json_name_field(self):
        # signals.json rows already carry a verified display name (e.g.
        # "キオクシアHD（285A）") -- reuse it rather than showing a bare
        # ticker code, and never invent one for a row that lacks it.
        _, _, _, symbol_names = b.build_states(fixture_signals(), NOW)
        self.assertEqual(symbol_names["285A.T"], "キオクシアHD（285A）")
        self.assertEqual(symbol_names["3132.T"], "マクニカHD（3132）")
        self.assertEqual(symbol_names["6920.T"], "レーザーテック（6920）")
        self.assertNotIn("6902.T", symbol_names)  # fixture row has no "name"

    def test_prepared_is_realtime_daytrade_not_scalp(self):
        # signals.json:prepared is update.py's "⑨ 本日準備点灯銘柄 上位30"
        # section, which scripts/weekly_tabs.py's own routing
        # (t.includes("準備点灯")) sends to the real REALTIME 5 tab -- not
        # SCALP, which has no signals.json source at all (the real SCALP 5
        # panel is a hardcoded 5-ticker list whose live values come only
        # from local MS2 RSS, never committed to this repo). A prepared-
        # only symbol must never become a card merely because it is
        # labeled REALTIME_DAYTRADE, since prepared is a 30-wide pool, not
        # an existing TOP5.
        states, _, card_symbols, _ = b.build_states(fixture_signals(), NOW)
        self.assertFalse([s for s in states if s["supervisor"] == "SCALP"])
        realtime = [s for s in states if s["supervisor"] == "REALTIME_DAYTRADE"]
        self.assertEqual(realtime[0]["direction"], "LONG_WATCH")
        self.assertEqual(realtime[0]["provenance"], "signals.json:prepared")
        self.assertNotIn("3132.T", card_symbols)
        self.assertNotIn("SCALP", b.CONNECTED_SUPERVISORS)
        self.assertIn("REALTIME_DAYTRADE", b.CONNECTED_SUPERVISORS)

    def test_value_long_catalyst_hammer_and_ma_rebound_are_card_worthy(self):
        states, _, card_symbols, _ = b.build_states(fixture_signals(), NOW)
        vlc = {s["symbol"]: s for s in states if s["supervisor"] == "VALUE_LONG_CATALYST"}
        self.assertEqual(vlc["6501.T"]["provenance"], "signals.json:monthly_weekly_hammers")
        self.assertEqual(vlc["6481.T"]["provenance"], "signals.json:long_term_ma_rebounds")
        self.assertIn("6501.T", card_symbols)
        self.assertIn("6481.T", card_symbols)

    def test_value_long_catalyst_accumulation_only_is_not_card_worthy(self):
        states, _, card_symbols, _ = b.build_states(fixture_signals(), NOW)
        vlc = {s["symbol"]: s for s in states if s["supervisor"] == "VALUE_LONG_CATALYST"}
        self.assertEqual(vlc["6920.T"]["direction"], "LONG_WATCH")
        self.assertEqual(vlc["6920.T"]["provenance"], "signals.json:large_lot_accumulation")
        self.assertNotIn("6920.T", card_symbols)

    def test_value_long_catalyst_overlap_prefers_card_worthy_provenance(self):
        # same ticker in both a card-worthy source (hammer) and the
        # list-only accumulation pool -- must not silently drop one, and
        # the surviving single VALUE_LONG_CATALYST state must be the
        # card-worthy one, not whichever was built last.
        signals = fixture_signals()
        signals["large_lot_accumulation"].append(
            {"ticker": "6501.T", "trigger": 5600, "stop": 5000, "target1": 6300,
             "score": 90, "signal_date": "2026-09-22"}
        )
        states, _, card_symbols, _ = b.build_states(signals, NOW)
        vlc_6501 = [s for s in states if s["supervisor"] == "VALUE_LONG_CATALYST" and s["symbol"] == "6501.T"]
        self.assertEqual(len(vlc_6501), 1)  # one Supervisor, one state per symbol -- not silently two
        self.assertEqual(vlc_6501[0]["provenance"], "signals.json:monthly_weekly_hammers")
        self.assertIn("6501.T", card_symbols)

    def test_overnight_card_absorbs_accumulation_lane_for_same_symbol(self):
        # 285A.T is both an OVERNIGHT TOP5 pick and a large_lot_accumulation
        # row -- the symbol must be card-worthy (via OVERNIGHT) and still
        # carry its VALUE_LONG_CATALYST lane from the accumulation row.
        states, _, card_symbols, _ = b.build_states(fixture_signals(), NOW)
        by_symbol_supervisor = {(s["symbol"], s["supervisor"]) for s in states}
        self.assertIn("285A.T", card_symbols)
        self.assertIn(("285A.T", "OVERNIGHT"), by_symbol_supervisor)
        self.assertIn(("285A.T", "VALUE_LONG_CATALYST"), by_symbol_supervisor)

    def test_event_as_of_uses_signals_updated_at_not_now(self):
        signals = fixture_signals()
        states, _, _, _ = b.build_states(signals, "2026-09-25T09:00:00+09:00")  # a different "now"
        event = [s for s in states if s["supervisor"] == "EVENT"][0]
        self.assertEqual(event["as_of"], "2026-09-22T20:23:54+09:00")

    def test_malformed_updated_at_never_falls_back_to_now(self):
        # No usable timestamp anywhere for EVENT rows (they have no
        # per-row signal_date of their own) -> excluded as a data issue,
        # never silently stamped with "now" to look artificially fresh.
        signals = fixture_signals()
        signals["updated_at"] = "not a timestamp"
        states, unresolved, _, _ = b.build_states(signals, NOW)
        self.assertFalse([s for s in states if s["supervisor"] == "EVENT"])
        event_issues = [u for u in unresolved if u["supervisor"] == "EVENT"]
        self.assertEqual(len(event_issues), 1)
        self.assertEqual(event_issues[0]["reason"], "TIMESTAMP_UNAVAILABLE")
        self.assertEqual(event_issues[0]["symbol"], "485A.T")

    def test_row_missing_signal_date_falls_back_to_signals_as_of(self):
        # OVERNIGHT/REALTIME_DAYTRADE/VALUE_LONG_CATALYST rows *do* have their own
        # signal_date normally; if a row is missing it but signals.json's
        # own updated_at is valid, that's still an honest timestamp, not
        # "now".
        signals = fixture_signals()
        del signals["overnight_long"][0]["signal_date"]
        states, unresolved, _, _ = b.build_states(signals, NOW)
        row = next(s for s in states if s["supervisor"] == "OVERNIGHT" and s["symbol"] == "285A.T")
        self.assertEqual(row["as_of"], "2026-09-22T20:23:54+09:00")
        self.assertEqual(unresolved, [])

    def test_row_and_updated_at_both_missing_becomes_data_issue(self):
        signals = fixture_signals()
        del signals["overnight_long"][0]["signal_date"]
        signals["updated_at"] = ""
        states, unresolved, _, _ = b.build_states(signals, NOW)
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
        # card-worthy: 285A.T, 6902.T, 485A.T, 6501.T, 6481.T
        self.assertEqual(len(artifact["board"]), 5)
        # watchlist-only: 3132.T (prepared), 6920.T (accumulation only)
        self.assertEqual(len(artifact["watchlist"]), 2)

    def test_symbol_name_present_on_card_and_watchlist_entry(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        card_285a = next(c for c in artifact["board"] if c["symbol"] == "285A.T")
        self.assertEqual(card_285a["symbol_name"], "キオクシアHD（285A）")
        watch_3132 = next(w for w in artifact["watchlist"] if w["symbol"] == "3132.T")
        self.assertEqual(watch_3132["symbol_name"], "マクニカHD（3132）")
        # 6902.T's fixture row has no "name" -- never invent one.
        card_6902 = next(c for c in artifact["board"] if c["symbol"] == "6902.T")
        self.assertIsNone(card_6902["symbol_name"])

    def test_card_symbols_never_duplicated_into_watchlist(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        card_symbols = {c["symbol"] for c in artifact["board"]}
        watchlist_symbols = {w["symbol"] for w in artifact["watchlist"]}
        self.assertEqual(card_symbols & watchlist_symbols, set())
        self.assertIn("3132.T", watchlist_symbols)
        self.assertIn("6920.T", watchlist_symbols)
        self.assertNotIn("285A.T", watchlist_symbols)

    def test_watchlist_entry_is_not_duplicated_and_carries_router_state(self):
        artifact = b.build_artifact(fixture_signals(), NOW)
        prepared = [w for w in artifact["watchlist"] if w["symbol"] == "3132.T"]
        self.assertEqual(len(prepared), 1)
        self.assertIn(prepared[0]["router_state"], strategy_router.STATES)
        self.assertFalse(prepared[0]["is_entry_trigger"])
        self.assertFalse(prepared[0]["real_submit_allowed"])

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
        self.assertNotIn("SWING", connected)

    def test_data_issues_surfaced_in_artifact(self):
        signals = fixture_signals()
        signals["updated_at"] = "garbage"
        artifact = b.build_artifact(signals, NOW)
        self.assertTrue(artifact["data_issues"])
        self.assertTrue(all(i["reason"] == "TIMESTAMP_UNAVAILABLE" for i in artifact["data_issues"]))

    def test_per_lane_freshness_distinguishes_overnight_from_value_long_catalyst(self):
        # Same age (~53h), different lanes: OVERNIGHT's 20h window must
        # flag it stale; VALUE_LONG_CATALYST's 10-day (240h) window must not.
        signals = fixture_signals()
        signals["overnight_long"][0]["signal_date"] = "2026-09-20"
        signals["monthly_weekly_hammers"][0]["signal_date"] = "2026-09-20"
        artifact = b.build_artifact(signals, NOW)
        overnight_card = next(c for c in artifact["board"] if c["symbol"] == "285A.T")
        vlc_card = next(c for c in artifact["board"] if c["symbol"] == "6501.T")
        self.assertIn("OVERNIGHT", overnight_card["router"]["stale_supervisors"])
        self.assertNotIn("VALUE_LONG_CATALYST", vlc_card["router"]["stale_supervisors"])

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
