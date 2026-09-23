import unittest
from scripts import ai_strategy_live as live
from scripts import strategy_router as router
from scripts import ai_strategy_live_view as view


def state(supervisor, symbol, direction, as_of, **extra):
    return live.build_supervisor_state(supervisor=supervisor, symbol=symbol, direction=direction, as_of=as_of, **extra)


NOW = "2026-09-22T10:05:00+09:00"


class BuildSupervisorRowTests(unittest.TestCase):
    def test_known_direction_labelled(self):
        s = {**state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"), "last_update_age_seconds": 30.0}
        row = view.build_supervisor_row(s, stale_after_seconds=300)
        self.assertEqual(row["direction_label"], "LONG")
        self.assertEqual(row["css_class"], "long")
        self.assertFalse(row["is_stale"])

    def test_stale_row_flagged(self):
        s = {**state("SCALP", "285A.T", "LONG", "2026-09-22T09:00:00+09:00"), "last_update_age_seconds": 3600.0}
        row = view.build_supervisor_row(s, stale_after_seconds=300)
        self.assertTrue(row["is_stale"])

    def test_future_age_flagged_stale(self):
        s = {**state("SCALP", "285A.T", "LONG", "2026-09-22T10:10:00+09:00"), "last_update_age_seconds": -300.0}
        row = view.build_supervisor_row(s, stale_after_seconds=300)
        self.assertTrue(row["is_stale"])

    def test_all_direction_labels_covered(self):
        for direction in live.DIRECTIONS:
            s = {**state("SCALP", "285A.T", direction, "2026-09-22T10:00:00+09:00"), "last_update_age_seconds": 1.0}
            row = view.build_supervisor_row(s, stale_after_seconds=300)
            self.assertEqual(row["direction_label"], view.DIRECTION_LABELS[direction]["label"])
            self.assertEqual(row["css_class"], view.DIRECTION_LABELS[direction]["css_class"])


class BuildSymbolCardViewTests(unittest.TestCase):
    def test_card_never_an_entry_trigger(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"])
        self.assertFalse(card["is_entry_trigger"])
        self.assertFalse(card["real_submit_allowed"])
        self.assertFalse(card["router"]["feature_flag_enabled"])

    def test_card_preserves_all_reported_supervisors(self):
        states = [
            state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
            state("OVERNIGHT", "285A.T", "BLOCK", "2026-09-22T10:00:00+09:00"),
            state("SWING", "285A.T", "LONG_WATCH", "2026-09-22T10:00:00+09:00"),
        ]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"])
        self.assertEqual({r["supervisor"] for r in card["rows"]}, {"SCALP", "OVERNIGHT", "SWING"})

    def test_supervisor_order_is_respected(self):
        states = [
            state("SWING", "285A.T", "NEUTRAL", "2026-09-22T10:00:00+09:00"),
            state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
        ]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"],
                                            supervisor_order=["SCALP", "SWING"])
        self.assertEqual([r["supervisor"] for r in card["rows"]], ["SCALP", "SWING"])

    def test_router_state_and_reasons_surfaced(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW)  # no data_quality_ok supplied -> UNKNOWN
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"])
        self.assertEqual(card["router"]["state"], "UNKNOWN")
        self.assertIn("DATA_QUALITY_UNKNOWN", card["router"]["reasons"])

    def test_router_data_quality_ok_and_as_of_surfaced(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"])
        self.assertTrue(card["router"]["data_quality_ok"])
        self.assertEqual(card["router"]["as_of"], NOW)

    def test_row_carries_exact_as_of_and_correlation_id(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00", correlation_id="corr-9")]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"])
        row = card["rows"][0]
        self.assertEqual(row["as_of"], "2026-09-22T10:00:00+09:00")
        self.assertEqual(row["correlation_id"], "corr-9")

    def test_conflict_state_passthrough(self):
        states = [state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00"),
                  state("OVERNIGHT", "285A.T", "SHORT", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW, data_quality_ok_by_symbol={"285A.T": True})
        card = view.build_symbol_card_view("285A.T", snap["285A.T"], decisions["285A.T"])
        self.assertTrue(card["conflict_state"]["conflict"])


class BuildLiveBoardViewTests(unittest.TestCase):
    def test_sorted_by_symbol(self):
        states = [state("SCALP", "9984.T", "WATCH", "2026-09-22T10:00:00+09:00"),
                  state("SCALP", "285A.T", "LONG", "2026-09-22T10:00:00+09:00")]
        snap = live.strategy_live_snapshot(states, NOW)
        decisions = router.route_snapshot(snap, NOW)
        board = view.build_live_board_view(snap, decisions)
        self.assertEqual([c["symbol"] for c in board], ["285A.T", "9984.T"])

    def test_empty_board(self):
        self.assertEqual(view.build_live_board_view({}, {}), [])


if __name__ == "__main__":
    unittest.main()
