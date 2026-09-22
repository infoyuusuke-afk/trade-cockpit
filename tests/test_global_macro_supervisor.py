import unittest
from scripts import global_macro_supervisor as m


def obs(instrument, value, observed_at, source="TEST", correlation_id=None):
    return {
        "schema_version": m.SCHEMA_VERSION,
        "instrument": instrument,
        "value": value,
        "observed_at": observed_at,
        "source": source,
        "correlation_id": correlation_id,
    }


class ValidateObservationTests(unittest.TestCase):
    def good(self):
        return obs("US_10Y", 4.25, "2026-09-21T09:10:00+09:00")

    def test_valid(self):
        self.assertTrue(m.validate_observation(self.good()))

    def test_unknown_field_rejected(self):
        x = self.good(); x["position_qty"] = 100
        self.assertFalse(m.validate_observation(x))

    def test_missing_required_rejected(self):
        x = self.good(); del x["source"]
        self.assertFalse(m.validate_observation(x))

    def test_unknown_instrument_rejected(self):
        x = self.good(); x["instrument"] = "FED_FUNDS_RATE"
        self.assertFalse(m.validate_observation(x))

    def test_naive_timestamp_rejected(self):
        x = self.good(); x["observed_at"] = "2026-09-21T09:10:00"
        self.assertFalse(m.validate_observation(x))

    def test_bool_value_rejected(self):
        x = self.good(); x["value"] = True
        self.assertFalse(m.validate_observation(x))

    def test_non_numeric_value_rejected(self):
        x = self.good(); x["value"] = "4.25"
        self.assertFalse(m.validate_observation(x))

    def test_empty_source_rejected(self):
        x = self.good(); x["source"] = ""
        self.assertFalse(m.validate_observation(x))

    def test_non_string_correlation_id_rejected(self):
        x = self.good(); x["correlation_id"] = 123
        self.assertFalse(m.validate_observation(x))

    def test_wrong_schema_version_rejected(self):
        x = self.good(); x["schema_version"] = "global-macro-observation-0.9"
        self.assertFalse(m.validate_observation(x))


class FreshnessStateTests(unittest.TestCase):
    def test_fresh(self):
        self.assertEqual(m.freshness_state("2026-09-21T09:00:00+09:00", "2026-09-21T10:00:00+09:00"), "FRESH")

    def test_stale(self):
        self.assertEqual(m.freshness_state("2026-09-21T00:00:00+09:00", "2026-09-21T10:00:00+09:00"), "STALE")

    def test_future_observation_is_unknown_not_accepted(self):
        self.assertEqual(m.freshness_state("2026-09-21T12:00:00+09:00", "2026-09-21T10:00:00+09:00"), "UNKNOWN")

    def test_naive_timestamp_is_unknown(self):
        self.assertEqual(m.freshness_state("2026-09-21T09:00:00", "2026-09-21T10:00:00+09:00"), "UNKNOWN")


class ClassifyCurveRegimeTests(unittest.TestCase):
    def test_bull_steepener_short_falls_faster(self):
        # short 2.0->1.5 (-0.5), long 4.0->3.9 (-0.1): spread 2.0->2.4, widening, yields net falling.
        self.assertEqual(m.classify_curve_regime(-0.5, -0.1, 2.4, 2.0), "BULL_STEEPENER")

    def test_bear_steepener_long_rises_faster(self):
        self.assertEqual(m.classify_curve_regime(0.05, 0.5, 2.45, 2.0), "BEAR_STEEPENER")

    def test_bull_flattener_long_falls_faster(self):
        self.assertEqual(m.classify_curve_regime(-0.1, -0.5, 1.6, 2.0), "BULL_FLATTENER")

    def test_bear_flattener_short_rises_faster(self):
        self.assertEqual(m.classify_curve_regime(0.5, 0.05, 1.55, 2.0), "BEAR_FLATTENER")

    def test_inverted_and_deepening(self):
        self.assertEqual(m.classify_curve_regime(0.5, 0.2, -0.5, -0.2), "INVERTED")

    def test_normalizing_while_still_negative(self):
        self.assertEqual(m.classify_curve_regime(-0.2, 0.1, -0.2, -0.5), "NORMALIZING")

    def test_normalizing_crossing_to_non_negative(self):
        self.assertEqual(m.classify_curve_regime(-0.15, 0.0, 0.05, -0.1), "NORMALIZING")

    def test_unknown_on_missing_change(self):
        self.assertEqual(m.classify_curve_regime(None, -0.1, 2.4, 2.0), "UNKNOWN")

    def test_unknown_on_zero_spread_change(self):
        self.assertEqual(m.classify_curve_regime(-0.1, -0.1, 2.0, 2.0), "UNKNOWN")

    def test_unknown_on_missing_prior(self):
        self.assertEqual(m.classify_curve_regime(-0.1, -0.1, 2.0, None), "UNKNOWN")

    def test_result_always_in_declared_regime_set(self):
        for args in [(-0.5,-0.1,2.4,2.0),(0.05,0.5,2.45,2.0),(-0.1,-0.5,1.6,2.0),
                     (0.5,0.05,1.55,2.0),(0.5,0.2,-0.5,-0.2),(-0.2,0.1,-0.2,-0.5),
                     (None,None,None,None)]:
            self.assertIn(m.classify_curve_regime(*args), m.CURVE_REGIMES)


class YieldCurveStateTests(unittest.TestCase):
    def test_unknown_curve_raises(self):
        with self.assertRaises(ValueError):
            m.yield_curve_state("US_1S2S", 1.0, 0.9, 2.0, 1.9)

    def test_missing_level_is_unknown(self):
        state = m.yield_curve_state("US_2S10S", None, None, 4.0, 3.9)
        self.assertEqual(state["regime"], "UNKNOWN")
        self.assertIsNone(state["spread"])

    def test_is_never_an_entry_trigger(self):
        state = m.yield_curve_state("US_2S10S", 1.5, 2.0, 3.9, 4.0)
        self.assertFalse(state["is_entry_trigger"])
        self.assertTrue(state["regime_modifier"])


class BuildRegimeModifierTests(unittest.TestCase):
    def _all_instruments_at(self, value, observed_at):
        return {i: [obs(i, value, observed_at)] for i in m.INSTRUMENTS}

    def test_real_submit_allowed_always_false(self):
        result = m.build_regime_modifier({}, "2026-09-21T10:00:00+09:00")
        self.assertFalse(result["real_submit_allowed"])
        self.assertFalse(result["is_entry_trigger"])

    def test_missing_instruments_marked_and_curves_insufficient(self):
        result = m.build_regime_modifier({}, "2026-09-21T10:00:00+09:00")
        self.assertEqual(set(result["stale_or_missing_instruments"]), m.INSTRUMENTS)
        for curve in result["curves"].values():
            self.assertEqual(curve["status"], "INSUFFICIENT_SAMPLE")
            self.assertEqual(curve["regime"], "UNKNOWN")

    def test_single_observation_per_instrument_is_insufficient_sample(self):
        as_of = "2026-09-21T10:00:00+09:00"
        result = m.build_regime_modifier(self._all_instruments_at(1.0, "2026-09-21T09:00:00+09:00"), as_of)
        for curve in result["curves"].values():
            self.assertEqual(curve["status"], "INSUFFICIENT_SAMPLE")

    def test_stale_observation_excluded(self):
        as_of = "2026-09-21T20:00:00+09:00"
        observations = {
            "US_2Y": [obs("US_2Y", 4.0, "2026-09-20T09:00:00+09:00"), obs("US_2Y", 3.9, "2026-09-20T09:00:00+09:00")],
            "US_10Y": [obs("US_10Y", 4.2, "2026-09-21T09:00:00+09:00"), obs("US_10Y", 4.1, "2026-09-21T09:00:00+09:00")],
        }
        result = m.build_regime_modifier(observations, as_of)
        self.assertIn("US_2Y", result["stale_or_missing_instruments"])
        self.assertEqual(result["curves"]["US_2S10S"]["status"], "INSUFFICIENT_SAMPLE")

    def test_bull_steepener_end_to_end(self):
        as_of = "2026-09-21T10:00:00+09:00"
        observations = {
            "US_2Y": [obs("US_2Y", 2.0, "2026-09-20T09:00:00+09:00"), obs("US_2Y", 1.5, "2026-09-21T09:00:00+09:00")],
            "US_10Y": [obs("US_10Y", 4.0, "2026-09-20T09:00:00+09:00"), obs("US_10Y", 3.9, "2026-09-21T09:00:00+09:00")],
        }
        result = m.build_regime_modifier(observations, as_of)
        curve = result["curves"]["US_2S10S"]
        self.assertEqual(curve["status"], "OK")
        self.assertEqual(curve["regime"], "BULL_STEEPENER")
        self.assertAlmostEqual(curve["spread"], 2.4)

    def test_one_bad_observation_disqualifies_whole_instrument(self):
        as_of = "2026-09-21T10:00:00+09:00"
        bad = obs("US_2Y", 2.0, "2026-09-20T09:00:00+09:00")
        bad["instrument"] = "NOT_A_REAL_INSTRUMENT"
        observations = {
            "US_2Y": [bad, obs("US_2Y", 1.5, "2026-09-21T09:00:00+09:00")],
            "US_10Y": [obs("US_10Y", 4.0, "2026-09-20T09:00:00+09:00"), obs("US_10Y", 3.9, "2026-09-21T09:00:00+09:00")],
        }
        result = m.build_regime_modifier(observations, as_of)
        self.assertIn("US_2Y", result["stale_or_missing_instruments"])
        self.assertEqual(result["curves"]["US_2S10S"]["status"], "INSUFFICIENT_SAMPLE")

    def test_no_curve_ever_reports_a_causal_narrative_field(self):
        result = m.build_regime_modifier({}, "2026-09-21T10:00:00+09:00")
        for curve in result["curves"].values():
            self.assertNotIn("causal_reason", curve)
            self.assertIn(curve["regime"], m.CURVE_REGIMES)


if __name__ == "__main__":
    unittest.main()
