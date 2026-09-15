import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location('rp', Path(__file__).parents[1] / 'scripts/regime_policy.py')
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)

JST = timezone(timedelta(hours=9))


def at(y, m, d, h=9, mi=0, s=0):
    return datetime(y, m, d, h, mi, s, tzinfo=JST)


class ClassifyBaseRegimeTests(unittest.TestCase):
    def test_up_requires_all_three_conditions(self):
        regime = rp.classify_base_regime(price=105, vwap=100, ema20_last3=[98, 99, 100], breadth_up_ratio=65)
        self.assertEqual(regime, 'UP')

    def test_down_requires_all_three_conditions(self):
        regime = rp.classify_base_regime(price=95, vwap=100, ema20_last3=[102, 101, 100], breadth_up_ratio=35)
        self.assertEqual(regime, 'DOWN')

    def test_price_above_vwap_but_ema_flat_is_range(self):
        regime = rp.classify_base_regime(price=105, vwap=100, ema20_last3=[100, 100, 100], breadth_up_ratio=65)
        self.assertEqual(regime, 'RANGE')

    def test_price_above_vwap_but_breadth_weak_is_range(self):
        regime = rp.classify_base_regime(price=105, vwap=100, ema20_last3=[98, 99, 100], breadth_up_ratio=50)
        self.assertEqual(regime, 'RANGE')

    def test_missing_price_is_unknown(self):
        self.assertEqual(rp.classify_base_regime(None, 100, [98, 99, 100], 65), 'UNKNOWN')

    def test_missing_breadth_is_unknown(self):
        self.assertEqual(rp.classify_base_regime(105, 100, [98, 99, 100], None), 'UNKNOWN')

    def test_fewer_than_three_ema_bars_is_unknown(self):
        self.assertEqual(rp.classify_base_regime(105, 100, [99, 100], 65), 'UNKNOWN')

    def test_data_not_ok_forces_unknown_even_with_values_present(self):
        regime = rp.classify_base_regime(105, 100, [98, 99, 100], 65, data_ok=False)
        self.assertEqual(regime, 'UNKNOWN')


class EventLockTests(unittest.TestCase):
    def test_within_t_minus_10_to_t_plus_15_is_locked(self):
        events = [{'tier': 'A', 'event_id': 'boj-x', 'scheduled_at_utc': at(2026, 9, 15, 12, 0, 0).isoformat()}]
        locked, event_id = rp.event_lock_active(events, at(2026, 9, 15, 12, 10, 0))
        self.assertTrue(locked)
        self.assertEqual(event_id, 'boj-x')

    def test_outside_window_is_not_locked(self):
        events = [{'tier': 'A', 'event_id': 'boj-x', 'scheduled_at_utc': at(2026, 9, 15, 12, 0, 0).isoformat()}]
        locked, _ = rp.event_lock_active(events, at(2026, 9, 15, 13, 0, 0))
        self.assertFalse(locked)

    def test_tier_b_does_not_lock(self):
        events = [{'tier': 'B', 'event_id': 'x', 'scheduled_at_utc': at(2026, 9, 15, 12, 0, 0).isoformat()}]
        locked, _ = rp.event_lock_active(events, at(2026, 9, 15, 12, 5, 0))
        self.assertFalse(locked)

    def test_no_scheduled_time_never_locks(self):
        # 架空の時刻を基準にロックしない
        events = [{'tier': 'A', 'event_id': 'x', 'scheduled_at_utc': None}]
        locked, _ = rp.event_lock_active(events, at(2026, 9, 15, 12, 5, 0))
        self.assertFalse(locked)


class ResolveRawRegimeTests(unittest.TestCase):
    def test_unknown_wins_over_everything(self):
        self.assertEqual(rp.resolve_raw_regime('UNKNOWN', event_locked=True, high_vol=True), 'UNKNOWN')

    def test_event_lock_wins_over_high_vol_and_base(self):
        self.assertEqual(rp.resolve_raw_regime('UP', event_locked=True, high_vol=True), 'EVENT_LOCK')

    def test_base_passes_through_when_nothing_active(self):
        self.assertEqual(rp.resolve_raw_regime('UP', event_locked=False, high_vol=False), 'UP')


class HysteresisTests(unittest.TestCase):
    def test_first_observation_confirms_immediately(self):
        state = {'confirmed_regime': None, 'confirmed_at': None,
                  'candidate_regime': None, 'candidate_streak': 0, 'candidate_first_at': None}
        new_state = rp.apply_hysteresis(state, 'RANGE', at(2026, 9, 15, 9, 0, 0))
        self.assertEqual(new_state['confirmed_regime'], 'RANGE')

    def test_single_new_reading_does_not_switch(self):
        # 受入基準#5: RANGE→UPが1回だけ→切替なし
        state = rp.apply_hysteresis(
            {'confirmed_regime': None, 'confirmed_at': None, 'candidate_regime': None,
             'candidate_streak': 0, 'candidate_first_at': None},
            'RANGE', at(2026, 9, 15, 9, 0, 0))
        # 最短保持15分を過ぎた時点でUPが1回だけ来ても切り替わらない
        state = rp.apply_hysteresis(state, 'UP', at(2026, 9, 15, 9, 20, 0))
        self.assertEqual(state['confirmed_regime'], 'RANGE')

    def test_two_consecutive_readings_after_min_hold_switches(self):
        # 受入基準#5: 2回＋保持条件成立→UP
        state = rp.apply_hysteresis(
            {'confirmed_regime': None, 'confirmed_at': None, 'candidate_regime': None,
             'candidate_streak': 0, 'candidate_first_at': None},
            'RANGE', at(2026, 9, 15, 9, 0, 0))
        state = rp.apply_hysteresis(state, 'UP', at(2026, 9, 15, 9, 20, 0))
        state = rp.apply_hysteresis(state, 'UP', at(2026, 9, 15, 9, 25, 0))
        self.assertEqual(state['confirmed_regime'], 'UP')

    def test_within_min_hold_window_candidate_not_counted(self):
        state = rp.apply_hysteresis(
            {'confirmed_regime': None, 'confirmed_at': None, 'candidate_regime': None,
             'candidate_streak': 0, 'candidate_first_at': None},
            'RANGE', at(2026, 9, 15, 9, 0, 0))
        # 最短保持15分未満でのUP連続は無視される
        state = rp.apply_hysteresis(state, 'UP', at(2026, 9, 15, 9, 5, 0))
        state = rp.apply_hysteresis(state, 'UP', at(2026, 9, 15, 9, 10, 0))
        self.assertEqual(state['confirmed_regime'], 'RANGE')

    def test_unknown_switches_immediately_regardless_of_streak(self):
        # 受入基準#5: UNKNOWNは即停止
        state = rp.apply_hysteresis(
            {'confirmed_regime': 'UP', 'confirmed_at': at(2026, 9, 15, 9, 0, 0).isoformat(),
             'candidate_regime': None, 'candidate_streak': 0, 'candidate_first_at': None},
            'UNKNOWN', at(2026, 9, 15, 9, 1, 0))
        self.assertEqual(state['confirmed_regime'], 'UNKNOWN')

    def test_event_lock_switches_immediately(self):
        state = rp.apply_hysteresis(
            {'confirmed_regime': 'UP', 'confirmed_at': at(2026, 9, 15, 9, 0, 0).isoformat(),
             'candidate_regime': None, 'candidate_streak': 0, 'candidate_first_at': None},
            'EVENT_LOCK', at(2026, 9, 15, 9, 1, 0))
        self.assertEqual(state['confirmed_regime'], 'EVENT_LOCK')

    def test_matching_current_regime_resets_candidate(self):
        state = {'confirmed_regime': 'UP', 'confirmed_at': at(2026, 9, 15, 9, 0, 0).isoformat(),
                  'candidate_regime': 'DOWN', 'candidate_streak': 1, 'candidate_first_at': 'x'}
        new_state = rp.apply_hysteresis(state, 'UP', at(2026, 9, 15, 9, 30, 0))
        self.assertIsNone(new_state['candidate_regime'])
        self.assertEqual(new_state['candidate_streak'], 0)


class ResolvePolicyTests(unittest.TestCase):
    def test_up_allows_long(self):
        policy = rp.resolve_policy('UP', high_vol=False)
        self.assertIn('LONG_TREND', policy['allowed'])
        self.assertEqual(policy['risk_multiplier'], 1.0)

    def test_high_vol_caps_risk_multiplier_at_half(self):
        policy = rp.resolve_policy('UP', high_vol=True)
        self.assertEqual(policy['risk_multiplier'], 0.5)

    def test_high_vol_does_not_raise_an_already_lower_multiplier(self):
        policy = rp.resolve_policy('DOWN', high_vol=True)
        self.assertEqual(policy['risk_multiplier'], 0.5)

    def test_unknown_allows_nothing(self):
        policy = rp.resolve_policy('UNKNOWN', high_vol=False)
        self.assertEqual(policy['allowed'], [])
        self.assertEqual(policy['risk_multiplier'], 0.0)


class HighVolTests(unittest.TestCase):
    def test_no_history_is_not_high_vol(self):
        self.assertFalse(rp.high_vol_active(2.0, []))

    def test_below_95th_percentile_is_not_high_vol(self):
        history = [0.1 * i for i in range(1, 101)]  # 0.1..10.0
        self.assertFalse(rp.high_vol_active(1.0, history))

    def test_above_95th_percentile_is_high_vol(self):
        history = [0.1 * i for i in range(1, 101)]
        self.assertTrue(rp.high_vol_active(15.0, history))


if __name__ == '__main__':
    unittest.main()
