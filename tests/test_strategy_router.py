import unittest
from scripts import strategy_router as router
from scripts import ai_strategy_live as live


def state(supervisor, symbol, direction, as_of, **extra):
    return live.build_supervisor_state(supervisor=supervisor, symbol=symbol, direction=direction, as_of=as_of, **extra)


NOW = "2026-09-22T10:05:00+09:00"


class FeatureFlagTripwireTests(unittest.TestCase):
    def test_feature_flag_is_off_in_phase1(self):
        self.assertFalse(router.FEATURE_FLAG_LIVE_INFLUENCE_ENABLED)


class RouteSymbolTests(unittest.TestCase):
    def test_no_supervisor_data_is_unknown(self):
        d = router.route_symbol("285A.T", None, now=NOW)
        self.assertEqual(d["state"], "NO_ACTION")
        self.assertIn("PHASE1_FEATURE_FLAG_OFF", d["reasons"])
        self.assertIn("NO_SUPERVISOR_DATA", d["reasons"])

    def test_state_always_in_closed_vocabulary(self):
        cases = [
            (None, None),
            (live.strategy_live_snapshot([state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)["285A.T"], True),
            (live.strategy_live_snapshot([state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)["285A.T"], False),
        ]
        for entry, dq in cases:
            d = router.route_symbol("285A.T", entry, now=NOW, data_quality_ok=dq)
            self.assertIn(d["state"], router.STATES)

    def test_never_returns_buy_or_short(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=True)
        self.assertNotIn(d["state"], {"LONG", "SHORT", "BUY", "SELL", "CANDIDATE"})

    def test_feature_flag_off_forces_no_action_even_when_everything_looks_fine(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=True)
        self.assertEqual(d["state"], "NO_ACTION")
        self.assertFalse(d["feature_flag_enabled"])

    def test_stale_supervisor_data_is_unknown_reason_present(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T09:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=True, stale_after_seconds=60)
        self.assertIn("STALE_SUPERVISOR_DATA", d["reasons"])

    def test_data_quality_not_ok_reason_present(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=False)
        self.assertIn("DATA_QUALITY_SUPERVISOR_NOT_OK", d["reasons"])

    def test_data_quality_unknown_reason_present(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW)
        self.assertIn("DATA_QUALITY_UNKNOWN", d["reasons"])

    def test_conflict_reason_present(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
             state("OVERNIGHT", "285A.T", "SHORT", "2026-09-22T10:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=True)
        self.assertIn("CROSS_HORIZON_CONFLICT", d["reasons"])
        self.assertTrue(d["conflict"])

    def test_supervisor_directions_are_read_only_passthrough(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=True)
        self.assertEqual(d["supervisor_directions"], {"SCALP": "LONG"})

    def test_never_an_entry_trigger(self):
        d = router.route_symbol("285A.T", None, now=NOW)
        self.assertFalse(d["is_entry_trigger"])
        self.assertFalse(d["real_submit_allowed"])

    def test_unknown_reasons_have_priority_over_hold_reasons(self):
        # Stale data should short-circuit before conflict/data-quality checks run.
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T09:00:00+09:00"),
             state("OVERNIGHT", "285A.T", "SHORT", "2026-09-22T09:00:00+09:00")], NOW)
        d = router.route_symbol("285A.T", snap["285A.T"], now=NOW, data_quality_ok=False, stale_after_seconds=60)
        self.assertIn("STALE_SUPERVISOR_DATA", d["reasons"])
        self.assertNotIn("DATA_QUALITY_SUPERVISOR_NOT_OK", d["reasons"])
        self.assertNotIn("CROSS_HORIZON_CONFLICT", d["reasons"])


class RouteSnapshotTests(unittest.TestCase):
    def test_routes_every_symbol(self):
        snap = live.strategy_live_snapshot(
            [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
             state("SCALP", "9984.T", "WATCH", "2026-09-22T10:00:00+09:00")], NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        self.assertEqual(set(decisions), {"285A.T", "9984.T"})
        self.assertIn("DATA_QUALITY_UNKNOWN", decisions["9984.T"]["reasons"])

    def test_empty_snapshot_returns_empty(self):
        self.assertEqual(router.route_snapshot({}, NOW), {})


if __name__ == "__main__":
    unittest.main()
