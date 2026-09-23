import importlib.util,json,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).parents[1];spec=importlib.util.spec_from_file_location("fmc",ROOT/"scripts/fill_model_calibration.py");m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
AS_OF=datetime(2026,9,30,tzinfo=timezone.utc)
def rec(**kw):
 submitted_at=kw.pop("submitted_at",datetime(2026,9,20,23,59,59,tzinfo=timezone.utc));observed_at=kw.pop("observed_at",datetime(2026,9,21,tzinfo=timezone.utc));predicted_at=kw.pop("predicted_at",submitted_at)
 r={"shadow_order_id":kw.pop("shadow_order_id","order-default"),"submitted_at":submitted_at,"predicted_at":predicted_at,"model_version":"shadow-fill-model-0.1","observed_at":observed_at,"order_type":"LIMIT","side":"BUY","requested_qty":100,"predicted_fill_qty":100,"observed_fill_qty":40,"predicted_fill_price":1500.0,"observed_fill_price":1501.0};r.update(kw)
 if any(k in r for k in m.CONTEXT_FIELDS): r.setdefault("context_observed_at",predicted_at);r.setdefault("context_freshness","OK")
 return r
class CalibrationContractTest(unittest.TestCase):
 def test_small_sample_remains_unknown(self):
  o=m.evaluate([rec()]);self.assertEqual(o["status"],"INSUFFICIENT_SAMPLE");self.assertFalse(o["parameter_update_allowed"]);self.assertFalse(o["real_submit_allowed"])
 def test_metrics_are_descriptive(self):
  o=m.evaluate([rec()]);self.assertEqual(o["fill_qty_mae"],60);self.assertEqual(o["fill_rate_bias"],0);self.assertEqual(o["fill_price_mae_yen"],1)
 def test_naive_time_invalid(self):
  o=m.evaluate([rec(observed_at=datetime(2026,9,21))]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)
 def test_overfill_invalid(self):
  o=m.evaluate([rec(observed_fill_qty=101)]);self.assertEqual(o["sample_size"],0)
 def test_threshold_only_enables_review_not_parameter_update(self):
  o=m.evaluate([rec(shadow_order_id=f"threshold-{i}") for i in range(m.MIN_SAMPLE)],now=AS_OF);self.assertEqual(o["status"],"CALIBRATION_REVIEW_ELIGIBLE");self.assertFalse(o["parameter_update_allowed"]);self.assertFalse(o["real_submit_allowed"])

class StratifiedCalibrationTest(unittest.TestCase):
 def test_market_and_limit_do_not_share_stratum_threshold(self):
  rows=[rec(order_type="LIMIT",shadow_order_id=f"limit-{i}") for i in range(25)]+[rec(order_type="MARKET",shadow_order_id=f"market-{i}") for i in range(25)]
  o=m.evaluate(rows,now=AS_OF);self.assertEqual(o["status"],"CALIBRATION_REVIEW_ELIGIBLE");self.assertEqual(o["strata"]["shadow-fill-model-0.1|LIMIT|BUY"]["status"],"INSUFFICIENT_SAMPLE");self.assertEqual(o["strata"]["shadow-fill-model-0.1|MARKET|BUY"]["status"],"INSUFFICIENT_SAMPLE")
 def test_buy_and_sell_are_separate(self):
  o=m.evaluate([rec(side="BUY",shadow_order_id="buy-1"),rec(side="SELL",shadow_order_id="sell-1")]);self.assertEqual(len(o["strata"]),2)

class LiquidityContextStrataTest(unittest.TestCase):
 def test_spread_liquidity_time_context_is_separate(self):
  a=rec(shadow_order_id="liq-a",spread_yen=1.0,tick_size=1.0,visible_qty=50,visible_qty_side="ASK")
  b=rec(shadow_order_id="liq-b",spread_yen=4.0,tick_size=1.0,visible_qty=400,visible_qty_side="ASK")
  o=m.evaluate([a,b]);self.assertEqual(len(o["context_strata"]),2);self.assertTrue(all(v["status"]=="INSUFFICIENT_SAMPLE" for v in o["context_strata"].values()))
 def test_invalid_optional_context_is_rejected(self):
  o=m.evaluate([rec(spread_yen=-1.0,tick_size=1.0,visible_qty=100)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)

class CalibrationCoverageGateTest(unittest.TestCase):
 def test_total_n_does_not_hide_missing_base_strata(self):
  o=m.evaluate([rec(order_type="LIMIT",side="BUY",shadow_order_id=f"limit-buy-{i}") for i in range(200)],now=AS_OF)
  self.assertEqual(o["status"],"CALIBRATION_REVIEW_ELIGIBLE");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT");self.assertIn("shadow-fill-model-0.1|MARKET|SELL",o["insufficient_base_strata"])
 def test_all_base_strata_need_minimum_sample(self):
  rows=[]
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"): rows += [rec(order_type=ot,side=side,shadow_order_id=f"{ot}-{side}-{i}") for i in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows);self.assertTrue(all(o["strata"][f"shadow-fill-model-0.1|{ot}|{side}"]["status"]=="CALIBRATION_REVIEW_ELIGIBLE" for ot in ("MARKET","LIMIT") for side in ("BUY","SELL")));self.assertEqual(o["day_coverage_status"],"DAY_COVERAGE_INSUFFICIENT");self.assertFalse(o["parameter_update_allowed"])

class MultiSessionCoverageTest(unittest.TestCase):
 def test_one_day_cannot_satisfy_coverage(self):
  rows=[]
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"): rows += [rec(order_type=ot,side=side,shadow_order_id=f"one-day-{ot}-{side}-{i}") for i in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows);self.assertEqual(o["day_coverage_status"],"DAY_COVERAGE_INSUFFICIENT");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT")
 def test_five_days_plus_base_strata_can_satisfy_coverage(self):
  rows=[]
  base=datetime(2026,9,1,tzinfo=timezone.utc)
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"):
    rows += [rec(order_type=ot,side=side,shadow_order_id=f"{ot}-{side}-{i}",submitted_at=base+timedelta(days=i % m.MIN_SESSION_DAYS)-timedelta(seconds=1),observed_at=base+timedelta(days=i % m.MIN_SESSION_DAYS)) for i in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows,now=AS_OF);self.assertEqual(o["unique_session_days"],m.MIN_SESSION_DAYS);self.assertEqual(o["coverage_status"],"COVERAGE_SUFFICIENT");self.assertFalse(o["parameter_update_allowed"])
 def test_global_five_days_cannot_hide_one_day_base_strata(self):
  rows=[];base=datetime(2026,9,1,tzinfo=timezone.utc)
  for ot in ("MARKET","LIMIT"):
   for side in ("BUY","SELL"):
    for i in range(m.MIN_SAMPLE):
     day=i % m.MIN_SESSION_DAYS if (ot,side)==("LIMIT","BUY") else 0
     observed=base+timedelta(days=day);rows.append(rec(order_type=ot,side=side,shadow_order_id=f"imbalanced-{ot}-{side}-{i}",submitted_at=observed-timedelta(seconds=1),observed_at=observed))
  o=m.evaluate(rows,now=AS_OF);self.assertEqual(o["day_coverage_status"],"DAY_COVERAGE_SUFFICIENT");self.assertEqual(o["base_strata_day_coverage_status"],"BASE_STRATA_DAY_COVERAGE_INSUFFICIENT");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT");self.assertIn("shadow-fill-model-0.1|MARKET|SELL",o["insufficient_base_day_strata"])

class RegimeProvenanceTest(unittest.TestCase):
 def test_missing_regime_stays_unknown_without_inference(self):
  o=m.evaluate([rec()]);self.assertEqual(o["regime_diagnostic_status"],"REGIME_CONTEXT_UNKNOWN");self.assertEqual(o["known_regime_n"],0);self.assertTrue(any(k.endswith("|UNKNOWN") for k in o["context_strata"]))
 def test_explicit_point_in_time_regime_is_preserved(self):
  o=m.evaluate([rec(market_regime="HIGH_VOL")]);self.assertEqual(o["regime_diagnostic_status"],"REGIME_CONTEXT_AVAILABLE");self.assertTrue(any(k.endswith("|HIGH_VOL") for k in o["context_strata"]))
 def test_unrecognized_regime_is_not_guessed(self):
  o=m.evaluate([rec(market_regime="BULLISH_MAYBE")]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)

class CalibrationDeduplicationTest(unittest.TestCase):
 def test_same_shadow_order_cannot_inflate_sample_size(self):
  rows=[rec(shadow_order_id="same-order") for _ in range(100)]
  o=m.evaluate(rows);self.assertEqual(o["sample_size"],1);self.assertEqual(o["duplicate_record_n"],99);self.assertEqual(o["status"],"INSUFFICIENT_SAMPLE")
 def test_missing_order_identity_is_invalid(self):
  o=m.evaluate([rec(shadow_order_id="")]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)

class CalibrationDuplicateConflictTest(unittest.TestCase):
 def test_identical_duplicate_is_benign_dedupe(self):
  r=rec(shadow_order_id="same");o=m.evaluate([r,dict(r)]);self.assertEqual(o["duplicate_record_n"],1);self.assertEqual(o["conflicting_duplicate_n"],0);self.assertEqual(o["evidence_integrity_status"],"OK")
 def test_same_order_id_with_different_observed_fill_is_conflict(self):
  a=rec(shadow_order_id="collision",observed_fill_qty=40);b=rec(shadow_order_id="collision",observed_fill_qty=80)
  o=m.evaluate([a,b]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["conflicting_duplicate_n"],1);self.assertEqual(o["conflicting_order_id_n"],1);self.assertEqual(o["evidence_integrity_status"],"CONFLICTING_DUPLICATE")
 def test_conflicting_duplicate_is_permutation_invariant(self):
  a=rec(shadow_order_id="collision",observed_fill_qty=40);b=rec(shadow_order_id="collision",observed_fill_qty=80)
  self.assertEqual(m.evaluate([a,b,dict(a)]),m.evaluate([b,dict(a),a]))
 def test_optional_evidence_difference_is_a_conflict(self):
  a=rec(shadow_order_id="collision",market_regime="RANGE")
  b=rec(shadow_order_id="collision",market_regime="HIGH_VOL")
  o=m.evaluate([a,b]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"CONFLICTING_DUPLICATE")
 def test_fill_price_difference_is_a_conflict(self):
  a=rec(shadow_order_id="collision",predicted_fill_price=1500.0,observed_fill_price=1501.0)
  b=rec(shadow_order_id="collision",predicted_fill_price=1490.0,observed_fill_price=1510.0)
  o=m.evaluate([a,b]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"CONFLICTING_DUPLICATE")
 def test_prediction_timestamp_difference_is_a_conflict(self):
  a=rec(shadow_order_id="collision");b=rec(shadow_order_id="collision",predicted_at=a["submitted_at"]+timedelta(microseconds=1))
  o=m.evaluate([a,b]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"CONFLICTING_DUPLICATE")
 def test_invalid_duplicate_classification_is_permutation_invariant(self):
  good=rec(shadow_order_id="same");bad=rec(shadow_order_id="same",observed_fill_qty=101)
  a=m.evaluate([good,bad]);b=m.evaluate([bad,good]);self.assertEqual(a,b);self.assertEqual(a["invalid_record_n"],1);self.assertEqual(a["sample_size"],1);self.assertEqual(a["evidence_integrity_status"],"INVALID_RECORDS")

class CalibrationPermutationDeterminismTest(unittest.TestCase):
 def test_unique_record_order_does_not_change_float_diagnostics(self):
  rows=[rec(shadow_order_id="c",predicted_fill_price=10_000_000_000_000_000.0,observed_fill_price=1.0),rec(shadow_order_id="a",predicted_fill_price=2.0,observed_fill_price=1.0),rec(shadow_order_id="b",predicted_fill_price=2.0,observed_fill_price=1.0)]
  self.assertEqual(m.evaluate(rows),m.evaluate(list(reversed(rows))))

class CalibrationIntegrityGateTest(unittest.TestCase):
 def test_conflict_blocks_review_even_when_sample_threshold_met(self):
  rows=[rec(shadow_order_id=f"ok-{i}") for i in range(m.MIN_SAMPLE)]
  rows.append(rec(shadow_order_id="ok-0",observed_fill_qty=99))
  o=m.evaluate(rows);self.assertEqual(o["sample_size"],m.MIN_SAMPLE-1);self.assertEqual(o["status"],"EVIDENCE_CONFLICT");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT");self.assertFalse(o["parameter_update_allowed"]);self.assertFalse(o["real_submit_allowed"])
 def test_invalid_record_blocks_review_even_when_valid_threshold_met(self):
  rows=[rec(shadow_order_id=f"ok-{i}") for i in range(m.MIN_SAMPLE)]+[rec(shadow_order_id="bad",observed_fill_qty=101)]
  o=m.evaluate(rows);self.assertEqual(o["sample_size"],m.MIN_SAMPLE);self.assertEqual(o["invalid_record_n"],1);self.assertEqual(o["status"],"EVIDENCE_CONFLICT");self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS");self.assertIn("INVALID_RECORDS",o["evidence_integrity_issues"])

class CalibrationPointInTimeGuardTest(unittest.TestCase):
 def test_observation_must_be_after_submission(self):
  when=datetime(2026,9,21,tzinfo=timezone.utc);o=m.evaluate([rec(submitted_at=when,observed_at=when)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)
 def test_future_evidence_relative_to_now_is_invalid(self):
  now=datetime(2026,9,21,1,tzinfo=timezone.utc);o=m.evaluate([rec(observed_at=now+timedelta(seconds=1))],now=now);self.assertEqual(o["sample_size"],0)
 def test_naive_now_is_rejected(self):
  with self.assertRaises(ValueError): m.evaluate([],now=datetime(2026,9,21))
 def test_review_threshold_requires_explicit_as_of(self):
  o=m.evaluate([rec(shadow_order_id=f"unbound-{i}") for i in range(m.MIN_SAMPLE)]);self.assertEqual(o["status"],"AS_OF_REQUIRED");self.assertEqual(o["point_in_time_status"],"AS_OF_REQUIRED");self.assertIsNone(o["evaluation_as_of"]);self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT")
 def test_equivalent_as_of_offsets_have_identical_output(self):
  utc=datetime(2026,9,21,1,tzinfo=timezone.utc);jst=datetime(2026,9,21,10,tzinfo=timezone(timedelta(hours=9)))
  self.assertEqual(m.evaluate([rec()],now=utc),m.evaluate([rec()],now=jst))

class CalibrationPredictionChronologyTest(unittest.TestCase):
 def test_missing_prediction_timestamp_is_invalid(self):
  r=rec();del r["predicted_at"];o=m.evaluate([r]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS")
 def test_prediction_cannot_be_after_outcome_observation(self):
  observed=datetime(2026,9,21,tzinfo=timezone.utc);o=m.evaluate([rec(predicted_at=observed+timedelta(microseconds=1),observed_at=observed)]);self.assertEqual(o["sample_size"],0)
 def test_prediction_cannot_equal_outcome_observation(self):
  observed=datetime(2026,9,21,tzinfo=timezone.utc);o=m.evaluate([rec(predicted_at=observed,observed_at=observed)]);self.assertEqual(o["sample_size"],0)
 def test_prediction_cannot_precede_submission(self):
  submitted=datetime(2026,9,21,tzinfo=timezone.utc);o=m.evaluate([rec(submitted_at=submitted,predicted_at=submitted-timedelta(microseconds=1),observed_at=submitted+timedelta(seconds=1))]);self.assertEqual(o["sample_size"],0)
 def test_prediction_at_submission_is_allowed(self):
  submitted=datetime(2026,9,21,tzinfo=timezone.utc);o=m.evaluate([rec(submitted_at=submitted,predicted_at=submitted,observed_at=submitted+timedelta(seconds=1))]);self.assertEqual(o["sample_size"],1);self.assertEqual(o["prediction_time_basis"],"EXPLICIT_PREDICTED_AT")

class CalibrationContextProvenanceTest(unittest.TestCase):
 def context_record(self): return rec(spread_yen=1.0,tick_size=1.0,visible_qty=100,visible_qty_side="ASK",market_regime="RANGE")
 def test_context_requires_observation_timestamp(self):
  r=self.context_record();del r["context_observed_at"];o=m.evaluate([r]);self.assertEqual(o["sample_size"],0)
 def test_context_requires_freshness(self):
  r=self.context_record();del r["context_freshness"];o=m.evaluate([r]);self.assertEqual(o["sample_size"],0)
 def test_non_ok_context_freshness_is_invalid(self):
  for freshness in ("STALE","MISSING","FUTURE","UNKNOWN"):
   with self.subTest(freshness=freshness): self.assertEqual(m.evaluate([rec(spread_yen=1.0,tick_size=1.0,context_freshness=freshness)])["sample_size"],0)
 def test_context_after_prediction_is_lookahead_and_invalid(self):
  r=self.context_record();r["context_observed_at"]=r["predicted_at"]+timedelta(microseconds=1);self.assertEqual(m.evaluate([r])["sample_size"],0)
 def test_context_before_submission_is_invalid(self):
  r=self.context_record();r["context_observed_at"]=r["submitted_at"]-timedelta(microseconds=1);self.assertEqual(m.evaluate([r])["sample_size"],0)
 def test_valid_context_provenance_is_reported(self):
  o=m.evaluate([self.context_record()]);self.assertEqual(o["context_evidence_n"],1);self.assertEqual(o["context_provenance_status"],"CONTEXT_PROVENANCE_AVAILABLE")
 def test_orphan_context_provenance_is_invalid(self):
  r=rec(context_observed_at=datetime(2026,9,20,23,59,59,tzinfo=timezone.utc),context_freshness="OK");self.assertEqual(m.evaluate([r])["sample_size"],0)

class CalibrationChronologyTest(unittest.TestCase):
 def test_observation_at_submission_is_invalid(self):
  ts=datetime(2026,9,21,tzinfo=timezone.utc);o=m.evaluate([rec(submitted_at=ts,observed_at=ts)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)
 def test_observation_before_submission_is_invalid(self):
  submit=datetime(2026,9,21,0,0,2,tzinfo=timezone.utc);obs=datetime(2026,9,21,0,0,1,tzinfo=timezone.utc);o=m.evaluate([rec(submitted_at=submit,observed_at=obs)]);self.assertEqual(o["sample_size"],0)
 def test_naive_submission_is_invalid(self):
  o=m.evaluate([rec(submitted_at=datetime(2026,9,21))]);self.assertEqual(o["sample_size"],0)

class CalibrationFutureGuardTest(unittest.TestCase):
 def test_future_observation_is_invalid(self):
  now=datetime(2026,9,20,23,59,59,500000,tzinfo=timezone.utc);o=m.evaluate([rec()],now=now);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1)
 def test_future_submission_is_invalid(self):
  now=datetime(2026,9,20,tzinfo=timezone.utc);o=m.evaluate([rec()],now=now);self.assertEqual(o["sample_size"],0)
 def test_naive_now_rejected(self):
  with self.assertRaises(ValueError): m.evaluate([],now=datetime(2026,9,21))

class CalibrationOptimismDiagnosticsTest(unittest.TestCase):
 def test_signed_qty_bias_exposes_overfill_optimism(self):
  o=m.evaluate([rec(shadow_order_id="a",predicted_fill_qty=100,observed_fill_qty=40),rec(shadow_order_id="b",predicted_fill_qty=50,observed_fill_qty=70)])
  self.assertEqual(o["fill_qty_bias"],20);self.assertEqual(o["fill_qty_mae"],40)
 def test_false_full_fill_rate_is_conditioned_on_predicted_full(self):
  rows=[rec(shadow_order_id="a",predicted_fill_qty=100,observed_fill_qty=40),rec(shadow_order_id="b",predicted_fill_qty=100,observed_fill_qty=100),rec(shadow_order_id="c",predicted_fill_qty=50,observed_fill_qty=10)]
  o=m.evaluate(rows);self.assertEqual(o["predicted_full_fill_n"],2);self.assertEqual(o["false_full_fill_n"],1);self.assertEqual(o["false_full_fill_rate"],0.5)
 def test_no_predicted_full_fill_has_no_false_full_rate(self):
  o=m.evaluate([rec(shadow_order_id="a",predicted_fill_qty=50,observed_fill_qty=40)]);self.assertIsNone(o["false_full_fill_rate"])

class CalibrationRelativePriceDiagnosticsTest(unittest.TestCase):
 def test_price_error_bps_normalizes_by_observed_price(self):
  o=m.evaluate([rec(shadow_order_id="a",predicted_fill_price=101.0,observed_fill_price=100.0),rec(shadow_order_id="b",predicted_fill_price=1001.0,observed_fill_price=1000.0)])
  self.assertAlmostEqual(o["fill_price_mae_yen"],1.0);self.assertAlmostEqual(o["fill_price_mae_bps"],55.0);self.assertAlmostEqual(o["fill_price_bias_bps"],55.0)
 def test_price_bias_bps_preserves_direction(self):
  o=m.evaluate([rec(shadow_order_id="a",predicted_fill_price=99.0,observed_fill_price=100.0)]);self.assertAlmostEqual(o["fill_price_bias_bps"],-100.0)

class CalibrationAdversePriceBiasTest(unittest.TestCase):
 def test_buy_worse_observed_price_is_positive_adverse_bias(self):
  o=m.evaluate([rec(shadow_order_id="buy",side="BUY",predicted_fill_price=100.0,observed_fill_price=101.0)]);self.assertGreater(o["adverse_price_bias_bps"],0)
 def test_sell_worse_observed_price_is_positive_adverse_bias(self):
  o=m.evaluate([rec(shadow_order_id="sell",side="SELL",predicted_fill_price=101.0,observed_fill_price=100.0)]);self.assertGreater(o["adverse_price_bias_bps"],0)
 def test_buy_better_observed_price_is_negative_adverse_bias(self):
  o=m.evaluate([rec(shadow_order_id="buy",side="BUY",predicted_fill_price=101.0,observed_fill_price=100.0)]);self.assertLess(o["adverse_price_bias_bps"],0)

class CalibrationModelVersionIsolationTest(unittest.TestCase):
 def test_mixed_model_versions_block_review(self):
  rows=[rec(shadow_order_id=f"v1-{i}") for i in range(m.MIN_SAMPLE)]
  rows += [rec(shadow_order_id=f"v2-{i}",model_version="shadow-fill-model-0.2") for i in range(m.MIN_SAMPLE)]
  o=m.evaluate(rows);self.assertEqual(o["model_version_status"],"MIXED_MODEL_VERSIONS");self.assertEqual(o["status"],"EVIDENCE_CONFLICT");self.assertEqual(o["coverage_status"],"COVERAGE_INSUFFICIENT");self.assertFalse(o["parameter_update_allowed"])
 def test_single_model_version_remains_normal(self):
  o=m.evaluate([rec(shadow_order_id="v1")]);self.assertEqual(o["model_versions"],["shadow-fill-model-0.1"]);self.assertEqual(o["model_version_status"],"SINGLE_MODEL_VERSION")
 def test_invalid_model_version_is_rejected_without_crashing(self):
  for value in (None,1,""," v1","v1 ","v1|LIMIT"):
   with self.subTest(value=value):
    o=m.evaluate([rec(shadow_order_id=f"bad-{value!r}",model_version=value)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS")

class CalibrationClosedSchemaTest(unittest.TestCase):
 def test_unknown_field_is_rejected_fail_closed(self):
  o=m.evaluate([rec(shadow_order_id="unknown-field",unexpected_evidence="x")],now=AS_OF);self.assertEqual(o["sample_size"],0);self.assertEqual(o["invalid_record_n"],1);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS");self.assertEqual(o["status"],"EVIDENCE_CONFLICT")
 def test_unknown_field_cannot_be_silently_deduplicated(self):
  good=rec(shadow_order_id="same");extra=rec(shadow_order_id="same",untracked_context=123)
  a=m.evaluate([good,extra],now=AS_OF);b=m.evaluate([extra,good],now=AS_OF);self.assertEqual(a,b);self.assertEqual(a["sample_size"],1);self.assertEqual(a["invalid_record_n"],1);self.assertEqual(a["evidence_integrity_status"],"INVALID_RECORDS")

class CalibrationIdentityIntegrityTest(unittest.TestCase):
 def test_surrounding_order_id_whitespace_is_not_silently_normalized(self):
  o=m.evaluate([rec(shadow_order_id=" order-1 ")]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS")

class CalibrationNumericIntegrityTest(unittest.TestCase):
 def test_huge_integer_is_rejected_without_exception(self):
  huge=10**1000;o=m.evaluate([rec(requested_qty=huge,predicted_fill_qty=huge,observed_fill_qty=huge)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS")
 def test_quantity_above_json_safe_integer_is_invalid(self):
  unsafe=m.MAX_SAFE_INTEGER+1;o=m.evaluate([rec(requested_qty=unsafe,predicted_fill_qty=unsafe,observed_fill_qty=unsafe)]);self.assertEqual(o["sample_size"],0)
 def test_nonfinite_derived_price_error_is_invalid(self):
  o=m.evaluate([rec(predicted_fill_price=1e308,observed_fill_price=1e-308)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["price_pair_n"],0);json.dumps(o,allow_nan=False)
 def test_nonfinite_spread_tick_ratio_is_invalid(self):
  o=m.evaluate([rec(spread_yen=1e308,tick_size=5e-324)]);self.assertEqual(o["sample_size"],0);json.dumps(o,allow_nan=False)

class CalibrationVisibleLiquiditySideTest(unittest.TestCase):
 def test_buy_visible_qty_requires_ask_side(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="a",visible_qty=100,visible_qty_side="BID")])["sample_size"],0)
 def test_sell_visible_qty_requires_bid_side(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="b",side="SELL",visible_qty=100,visible_qty_side="ASK")])["sample_size"],0)
 def test_correct_executable_side_is_accepted(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="a",side="BUY",visible_qty=100,visible_qty_side="ASK")])["sample_size"],1)
  self.assertEqual(m.evaluate([rec(shadow_order_id="b",side="SELL",visible_qty=100,visible_qty_side="BID")])["sample_size"],1)
 def test_visible_side_without_quantity_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="a",visible_qty_side="ASK")])["sample_size"],0)
 def test_non_integral_visible_quantity_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="a",visible_qty=100.5,visible_qty_side="ASK")])["sample_size"],0)

class CalibrationSpreadTickIntegrityTest(unittest.TestCase):
 def test_spread_without_tick_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="a",spread_yen=1.0)])["sample_size"],0)
 def test_tick_without_spread_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="b",tick_size=1.0)])["sample_size"],0)
 def test_zero_tick_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="c",spread_yen=1.0,tick_size=0.0)])["sample_size"],0)
 def test_spread_tick_pair_is_accepted(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="d",spread_yen=2.0,tick_size=1.0)])["sample_size"],1)


class CalibrationTickGridIntegrityTest(unittest.TestCase):
 def test_fractional_tick_spread_is_invalid(self):
  o=m.evaluate([rec(shadow_order_id="fractional-tick",spread_yen=1.5,tick_size=1.0)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS")
 def test_float_roundoff_exact_tick_multiple_is_accepted_and_stable(self):
  o=m.evaluate([rec(shadow_order_id="roundoff",spread_yen=0.3,tick_size=0.1)]);self.assertEqual(o["sample_size"],1);self.assertTrue(any("|SPREAD_2_3T|" in k for k in o["context_strata"]))

class CalibrationTimezoneNormalizationIntegrityTest(unittest.TestCase):
 def test_aware_timestamp_that_overflows_jst_is_invalid_not_exception(self):
  submitted=datetime(9999,12,31,16,0,tzinfo=timezone.utc);predicted=datetime(9999,12,31,17,0,tzinfo=timezone.utc);observed=datetime(9999,12,31,18,0,tzinfo=timezone.utc)
  o=m.evaluate([rec(shadow_order_id="overflow-time",submitted_at=submitted,predicted_at=predicted,observed_at=observed)]);self.assertEqual(o["sample_size"],0);self.assertEqual(o["evidence_integrity_status"],"INVALID_RECORDS")
 def test_now_that_cannot_normalize_to_jst_is_rejected(self):
  with self.assertRaises(ValueError): m.evaluate([],now=datetime(9999,12,31,16,0,tzinfo=timezone.utc))

class CalibrationPricePairIntegrityTest(unittest.TestCase):
 def test_predicted_price_without_observed_is_invalid(self):
  r=rec(shadow_order_id="a");del r["observed_fill_price"];self.assertEqual(m.evaluate([r])["sample_size"],0)
 def test_observed_price_without_predicted_is_invalid(self):
  r=rec(shadow_order_id="b");del r["predicted_fill_price"];self.assertEqual(m.evaluate([r])["sample_size"],0)
 def test_nonpositive_price_pair_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="c",predicted_fill_price=0.0,observed_fill_price=100.0)])["sample_size"],0)
 def test_both_prices_absent_is_allowed(self):
  r=rec(shadow_order_id="d");del r["predicted_fill_price"];del r["observed_fill_price"];o=m.evaluate([r]);self.assertEqual(o["sample_size"],1);self.assertEqual(o["price_pair_n"],0)
 def test_price_pair_without_both_positive_fill_quantities_is_invalid(self):
  self.assertEqual(m.evaluate([rec(shadow_order_id="e",predicted_fill_qty=100,observed_fill_qty=0)])["sample_size"],0)
  self.assertEqual(m.evaluate([rec(shadow_order_id="f",predicted_fill_qty=0,observed_fill_qty=40)])["sample_size"],0)
 def test_no_fill_without_price_pair_is_allowed(self):
  r=rec(shadow_order_id="g",predicted_fill_qty=0,observed_fill_qty=0);del r["predicted_fill_price"];del r["observed_fill_price"];self.assertEqual(m.evaluate([r])["sample_size"],1)

class CalibrationPriceEvidenceCoverageTest(unittest.TestCase):
 def test_partial_price_evidence_reports_coverage(self):
  a=rec(shadow_order_id="a");b=rec(shadow_order_id="b");del b["predicted_fill_price"];del b["observed_fill_price"]
  o=m.evaluate([a,b]);self.assertEqual(o["price_pair_n"],1);self.assertEqual(o["price_evidence_coverage"],0.5);self.assertEqual(o["price_evidence_status"],"PRICE_EVIDENCE_AVAILABLE")
 def test_no_price_evidence_is_explicit(self):
  r=rec(shadow_order_id="a");del r["predicted_fill_price"];del r["observed_fill_price"];o=m.evaluate([r]);self.assertEqual(o["price_pair_n"],0);self.assertEqual(o["price_evidence_coverage"],0.0);self.assertEqual(o["price_evidence_status"],"PRICE_EVIDENCE_UNAVAILABLE")

class CalibrationJstNormalizationTest(unittest.TestCase):
 def test_same_instant_utc_and_jst_have_same_open_bucket_and_session_day(self):
  a=rec(shadow_order_id="utc",submitted_at=datetime(2026,9,21,0,0,tzinfo=timezone.utc),observed_at=datetime(2026,9,21,0,10,tzinfo=timezone.utc))
  b=rec(shadow_order_id="jst",submitted_at=datetime(2026,9,21,9,0,tzinfo=timezone(timedelta(hours=9))),observed_at=datetime(2026,9,21,9,10,tzinfo=timezone(timedelta(hours=9))))
  oa=m.evaluate([a]);ob=m.evaluate([b]);self.assertEqual(oa["session_days"],ob["session_days"]);self.assertEqual(list(oa["context_strata"])[0].split("|")[-2], "OPEN_0900_0930");self.assertEqual(list(oa["context_strata"])[0].split("|")[-2],list(ob["context_strata"])[0].split("|")[-2])
 def test_utc_0540_maps_to_jst_close_bucket(self):
  r=rec(shadow_order_id="close",submitted_at=datetime(2026,9,21,5,30,tzinfo=timezone.utc),observed_at=datetime(2026,9,21,5,40,tzinfo=timezone.utc));o=m.evaluate([r]);self.assertEqual(list(o["context_strata"])[0].split("|")[-2],"CLOSE_1430_1530")
 def test_time_bucket_uses_submission_not_later_observation(self):
  r=rec(shadow_order_id="boundary",submitted_at=datetime(2026,9,21,5,29,tzinfo=timezone.utc),observed_at=datetime(2026,9,21,5,31,tzinfo=timezone.utc));o=m.evaluate([r]);self.assertEqual(list(o["context_strata"])[0].split("|")[-2],"MID_SESSION");self.assertEqual(o["time_bucket_basis"],"SUBMITTED_AT_JST")
 def test_session_day_uses_submission_not_delayed_observation(self):
  r=rec(shadow_order_id="delayed",submitted_at=datetime(2026,9,21,5,0,tzinfo=timezone.utc),observed_at=datetime(2026,9,21,15,0,tzinfo=timezone.utc));o=m.evaluate([r]);self.assertEqual(o["session_days"],["2026-09-21"]);self.assertEqual(o["session_day_basis"],"SUBMITTED_AT_JST")
