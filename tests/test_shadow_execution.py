import importlib.util
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
JST = timezone(timedelta(hours=9))


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ec = _load('ec', 'scripts/execution_contract.py')
se = _load('se', 'scripts/shadow_execution.py')

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)
SUBMITTED_AT = NOW - timedelta(seconds=10)


def build_intent(**overrides):
    kwargs = dict(
        symbol="285A.T", side="BUY", quantity=100, order_type="LIMIT",
        limit_price=1500.0, planned_entry=1500.0, planned_stop=1450.0, planned_target=1600.0,
        strategy_id="day_ifo_long", strategy_version="1.0",
        decision_snapshot_id="snap-1", signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-gate-0.1.0", execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-fill-model-0.1", merge_hash="m" * 64,
    )
    kwargs.update(overrides)
    return ec.build_intent(**kwargs)


def risk_decision(**overrides):
    base = {
        "decision": "PASS", "merge_hash": "m" * 64, "allowed_qty": 100,
        "symbol": "285A.T", "side": "BUY", "policy_version": "risk-gate-0.1.0",
    }
    base.update(overrides)
    return base


def ticket(intent, **overrides):
    base = {
        "permission_status": "ORDER_TICKET_READY",
        "intent_hash": intent["intent_hash"],
        "merge_hash": intent["merge_hash"],
        "ticket_fingerprint": "fp-" + "a" * 60,
    }
    base.update(overrides)
    return base


def observation(**overrides):
    base = {
        "observed_at": NOW,
        "bid": 1499.0, "ask": 1500.0,
        "bid_qty": 500, "ask_qty": 500,
        "last_trade_price": 1500.0, "last_trade_qty": 100,
        "tick_size": 1.0,
        "data_freshness": "OK",
    }
    base.update(overrides)
    return base


def submit(intent, decision, tkt, *, known_orders=None, submitted_at=SUBMITTED_AT, now=NOW):
    """Phase 5.0.2 hardening（C-060-GPT comment 5708285624）: submit_shadow_
    order()がsubmitted_at/nowを必須keyword-only引数として要求するように
    なったため、ほとんどのテストで共通利用するデフォルト値を持つ薄い
    wrapper。submitted_at/now自体の検証をテストするケースはse.submit_
    shadow_order()を直接呼ぶ。"""
    return se.submit_shadow_order(intent, decision, tkt, known_orders=[] if known_orders is None else known_orders,
                                   submitted_at=submitted_at, now=now)


class ShadowOrderIdTests(unittest.TestCase):
    def test_golden_1_same_intent_and_model_gives_same_id(self):
        a = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        b = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        self.assertEqual(a, b)

    def test_different_model_version_gives_different_id(self):
        a = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        b = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.2")
        self.assertNotEqual(a, b)

    def test_different_intent_hash_gives_different_id(self):
        a = se.compute_shadow_order_id("h" * 64, "shadow-fill-model-0.1")
        b = se.compute_shadow_order_id("z" * 64, "shadow-fill-model-0.1")
        self.assertNotEqual(a, b)


class SubmitShadowOrderHappyPathTests(unittest.TestCase):
    def test_valid_lineage_gives_new_status(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertEqual(out["status"], "NEW")
        self.assertEqual(out["real_submit_allowed"], False)
        expected_id = se.compute_shadow_order_id(intent["intent_hash"], intent["shadow_fill_model_version"])
        self.assertEqual(out["shadow_order_id"], expected_id)
        self.assertEqual(out["merge_hash"], "m" * 64)
        self.assertEqual(out["requested_qty"], 100)
        self.assertEqual(out["remaining_qty"], 100)

    def test_canonical_status_field_name_only(self):
        """Phase 5.0.1 small schema correction（C-057R-GPT）: canonical field
        名は`status`のみに統一する。`fill_status`という二重フィールドは
        作らない。"""
        intent = build_intent()
        out = submit(intent, risk_decision(), ticket(intent))
        self.assertIn("status", out)
        self.assertNotIn("fill_status", out)
        filled = se.evaluate_shadow_fill({**out, "order_type": "MARKET"}, observation(), now=NOW)
        self.assertIn("status", filled)
        self.assertNotIn("fill_status", filled)


class DuplicateGuardTests(unittest.TestCase):
    def test_golden_2_duplicate_intent_gives_duplicate_ignored_no_double_order(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        first = submit(intent, decision, tkt)
        second = submit(intent, decision, tkt, known_orders=[first])
        self.assertEqual(second["status"], "DUPLICATE_IGNORED")
        self.assertEqual(second["shadow_order_id"], first["shadow_order_id"])

    def test_unrelated_known_order_does_not_block(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        unrelated = {"shadow_order_id": "z" * 64}
        out = submit(intent, decision, tkt, known_orders=[unrelated])
        self.assertEqual(out["status"], "NEW")


class LineageRejectionTests(unittest.TestCase):
    """Golden #3-#7: lineageが不正ならREJECTED。"""

    def test_golden_3_mismatched_intent_hash_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent, intent_hash="0" * 64)
        out = submit(intent, decision, tkt)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_INTENT_HASH_MISMATCH", out["reject_reasons"])
        self.assertIsNone(out["shadow_order_id"])

    def test_golden_4_risk_decision_merge_hash_mismatch_rejected(self):
        intent = build_intent()
        decision = risk_decision(merge_hash="z" * 64)
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_MERGE_HASH_MISMATCH", out["reject_reasons"])

    def test_golden_4_ticket_merge_hash_mismatch_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent, merge_hash="z" * 64)
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_MERGE_HASH_MISMATCH", out["reject_reasons"])

    def test_golden_5_risk_decision_not_pass_rejected(self):
        intent = build_intent()
        decision = risk_decision(decision="BLOCK")
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_RISK_DECISION_NOT_PASS", out["reject_reasons"])

    def test_golden_6_permission_status_not_ready_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent, permission_status="BLOCKED")
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_TICKET_NOT_READY", out["reject_reasons"])

    def test_golden_7_real_submit_allowed_true_rejected(self):
        intent = {**build_intent(), "real_submit_allowed": True}
        decision = risk_decision()
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_REAL_SUBMIT_ALLOWED_NOT_FALSE", out["reject_reasons"])

    def test_quantity_mismatch_rejected(self):
        intent = build_intent(quantity=100)
        decision = risk_decision(allowed_qty=200)
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_QUANTITY_MISMATCH", out["reject_reasons"])

    def test_risk_policy_version_mismatch_rejected(self):
        intent = build_intent(risk_policy_version="risk-gate-0.1.0")
        decision = risk_decision(policy_version="risk-gate-9.9.9")
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_RISK_POLICY_VERSION_MISMATCH", out["reject_reasons"])

    def test_intent_hash_tampered_rejected(self):
        """intent_hashフィールド自体はticketと一致していても、中身
        （quantity）だけ書き換えられ再計算hashと食い違う場合を検出する。"""
        intent = {**build_intent(), "quantity": 999}
        decision = risk_decision(allowed_qty=999)
        tkt = ticket(intent)
        out = submit(intent, decision, tkt)
        self.assertIn("REJECTED_INTENT_HASH_TAMPERED", out["reject_reasons"])

    def test_non_list_known_orders_rejected(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        out = se.submit_shadow_order(intent, decision, tkt, known_orders=None,
                                      submitted_at=SUBMITTED_AT, now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_KNOWN_ORDERS_INVALID", out["reject_reasons"])


class ShadowFillModelVersionBindingTests(unittest.TestCase):
    """Phase 5.0.1 hardening Blocker 2（C-057R-GPT comment 5707963859）:
    宣言されたshadow_fill_model_versionが、実際に呼ぶscripts/shadow_
    fill_model.pyのFILL_MODEL_VERSIONと完全一致することを必須にする。"""

    def test_hardening_golden_5_exact_version_match_gives_new(self):
        intent = build_intent(shadow_fill_model_version=se.sfm.FILL_MODEL_VERSION)
        out = submit(intent, risk_decision(), ticket(intent))
        self.assertEqual(out["status"], "NEW")

    def test_hardening_golden_6_unknown_or_newer_or_older_version_rejected(self):
        # build_intent()自体はshadow_fill_model_versionに非空stringしか要求しない
        # （versionの中身までは検証しない）ため、まず正常にbuildしてからintent側だけ
        # 改ざんして再現する（tamperしてもintent_hashは影響を受けない——hash対象外）。
        for bad_version in ("shadow-fill-model-9.9", "shadow-fill-model-0.0", "", None, 123):
            intent = build_intent()
            tampered = {**intent, "shadow_fill_model_version": bad_version}
            out = submit(tampered, risk_decision(), ticket(tampered))
            self.assertEqual(out["status"], "REJECTED", msg=f"version={bad_version!r}")
            self.assertIn("REJECTED_SHADOW_FILL_MODEL_VERSION_MISMATCH", out["reject_reasons"],
                           msg=f"version={bad_version!r}")

    def test_hardening_golden_7_recorded_version_matches_version_actually_used(self):
        intent = build_intent(shadow_fill_model_version=se.sfm.FILL_MODEL_VERSION)
        out = submit(intent, risk_decision(), ticket(intent))
        self.assertEqual(out["shadow_fill_model_version"], se.sfm.FILL_MODEL_VERSION)
        expected_id = se.compute_shadow_order_id(intent["intent_hash"], se.sfm.FILL_MODEL_VERSION)
        self.assertEqual(out["shadow_order_id"], expected_id)


class SubmittedAtBindingTests(unittest.TestCase):
    """Phase 5.0.2 hardening Blocker 1（C-060-GPT comment 5708285624）:
    submitted_atはshadow orderへimmutable/bound contextとして保存され、
    evaluate_shadow_fill()は外部からsubmitted_atを受け取らない。"""

    def test_hardening_golden_1_market_observation_before_submitted_at_no_fill(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        order = submit(intent, risk_decision(), ticket(intent), submitted_at=NOW)
        early = observation(observed_at=NOW - timedelta(seconds=1))
        out = se.evaluate_shadow_fill(order, early, now=NOW)
        self.assertEqual(out["filled_qty"], 0)

    def test_hardening_golden_2_limit_observation_before_submitted_at_no_fill(self):
        intent = build_intent(order_type="LIMIT", limit_price=1500.0)
        order = submit(intent, risk_decision(), ticket(intent), submitted_at=NOW)
        early = observation(observed_at=NOW - timedelta(seconds=1), last_trade_price=1490.0)
        out = se.evaluate_shadow_fill(order, early, now=NOW)
        self.assertEqual(out["filled_qty"], 0)

    def test_hardening_golden_3_evaluate_shadow_fill_does_not_accept_submitted_at(self):
        """呼び出し側が別のsubmitted_atを注入して過去tradeを有効化する
        経路が構造的に存在しないことを確認する。"""
        params = inspect.signature(se.evaluate_shadow_fill).parameters
        self.assertNotIn("submitted_at", params)

    def test_submit_shadow_order_requires_aware_submitted_at(self):
        intent = build_intent()
        out = se.submit_shadow_order(intent, risk_decision(), ticket(intent), known_orders=[],
                                      submitted_at=datetime(2026, 9, 17, 8, 59, 0), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_SUBMITTED_AT_NOT_TIMEZONE_AWARE", out["reject_reasons"])

    def test_submit_shadow_order_rejects_future_submitted_at(self):
        intent = build_intent()
        out = se.submit_shadow_order(intent, risk_decision(), ticket(intent), known_orders=[],
                                      submitted_at=NOW + timedelta(seconds=1), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_SUBMITTED_AT_FUTURE", out["reject_reasons"])

    def test_submit_shadow_order_requires_aware_now(self):
        intent = build_intent()
        out = se.submit_shadow_order(intent, risk_decision(), ticket(intent), known_orders=[],
                                      submitted_at=SUBMITTED_AT, now=datetime(2026, 9, 17, 9, 0, 0))
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_NOW_NOT_TIMEZONE_AWARE", out["reject_reasons"])

    def test_order_stores_bound_submitted_at(self):
        intent = build_intent()
        out = submit(intent, risk_decision(), ticket(intent))
        self.assertEqual(out["submitted_at"], SUBMITTED_AT)


class EvaluateShadowFillTests(unittest.TestCase):
    def _new_order(self, order_type="MARKET", **intent_overrides):
        overrides = dict(order_type=order_type)
        if order_type == "MARKET":
            overrides["limit_price"] = None
        overrides.update(intent_overrides)
        intent = build_intent(**overrides)
        decision = risk_decision()
        tkt = ticket(intent)
        return submit(intent, decision, tkt)

    def test_market_fill_transitions_to_filled(self):
        order = self._new_order("MARKET")
        out = se.evaluate_shadow_fill(order, observation(), now=NOW)
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["filled_qty"], 100)
        self.assertEqual(out["remaining_qty"], 0)
        self.assertEqual(out["fill_at"], NOW)
        self.assertEqual(out["first_observation_at"], NOW)
        self.assertEqual(out["real_submit_allowed"], False)

    def test_market_partial_fill_status(self):
        order = self._new_order("MARKET")
        out = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(out["status"], "PARTIAL_FILLED")
        self.assertEqual(out["filled_qty"], 40)
        self.assertEqual(out["remaining_qty"], 60)
        self.assertIn("PARTIAL_FILL", out["ambiguity_flags"])

    def test_limit_touch_only_stays_working_with_ambiguity_flag(self):
        order = self._new_order("LIMIT", limit_price=1500.0)
        out = se.evaluate_shadow_fill(order, observation(last_trade_price=1500.0), now=NOW)
        self.assertEqual(out["status"], "WORKING")
        self.assertIn("TOUCH_ONLY", out["ambiguity_flags"])
        self.assertEqual(out["filled_qty"], 0)

    def test_limit_trade_through_fills(self):
        order = self._new_order("LIMIT", limit_price=1500.0)
        out = se.evaluate_shadow_fill(order, observation(last_trade_price=1490.0), now=NOW)
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["filled_qty"], 100)

    def test_unobservable_data_gives_unobservable_status(self):
        order = self._new_order("MARKET")
        out = se.evaluate_shadow_fill(order, observation(data_freshness="STALE"), now=NOW)
        self.assertEqual(out["status"], "UNOBSERVABLE")
        self.assertEqual(out["filled_qty"], 0)

    def test_golden_17_terminal_filled_state_not_reevaluated(self):
        """FILLED状態のshadow_orderへ、全く異なるobservationを渡しても
        一切変化しない（自動retryしない）。"""
        order = self._new_order("MARKET")
        filled = se.evaluate_shadow_fill(order, observation(), now=NOW)
        self.assertEqual(filled["status"], "FILLED")
        later = NOW + timedelta(seconds=30)
        reevaluated = se.evaluate_shadow_fill(filled, observation(observed_at=later, ask=9999.0), now=later)
        self.assertEqual(reevaluated, filled)

    def test_golden_17_rejected_state_not_reevaluated(self):
        intent = build_intent()
        decision = risk_decision(decision="BLOCK")
        tkt = ticket(intent)
        rejected = submit(intent, decision, tkt)
        self.assertEqual(rejected["status"], "REJECTED")
        out = se.evaluate_shadow_fill(rejected, observation(), now=NOW)
        self.assertEqual(out, rejected)

    def test_golden_17_duplicate_ignored_state_not_reevaluated(self):
        intent = build_intent()
        decision = risk_decision()
        tkt = ticket(intent)
        first = submit(intent, decision, tkt)
        duplicate = submit(intent, decision, tkt, known_orders=[first])
        self.assertEqual(duplicate["status"], "DUPLICATE_IGNORED")
        out = se.evaluate_shadow_fill(duplicate, observation(), now=NOW)
        self.assertEqual(out, duplicate)


class PartialFillAccumulationTests(unittest.TestCase):
    """Phase 5.0.1 hardening Blocker 1（C-057R-GPT comment 5707963859）:
    複数回のobservationにまたがるpartial fillを累積し、既存fillを
    上書き/巻き戻ししない。avg_fill_priceは数量加重平均にする。"""

    def _new_market_order(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        return submit(intent, risk_decision(), ticket(intent))

    def test_hardening_golden_1_second_round_completes_to_filled(self):
        order = self._new_market_order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(round1["status"], "PARTIAL_FILLED")
        self.assertEqual(round1["filled_qty"], 40)
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask_qty=60), now=later)
        self.assertEqual(round2["status"], "FILLED")
        self.assertEqual(round2["filled_qty"], 100)
        self.assertEqual(round2["remaining_qty"], 0)

    def test_hardening_golden_2_second_round_stays_partial_with_correct_total(self):
        order = self._new_market_order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(round1["filled_qty"], 40)
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask_qty=20), now=later)
        self.assertEqual(round2["status"], "PARTIAL_FILLED")
        self.assertEqual(round2["filled_qty"], 60)
        self.assertEqual(round2["remaining_qty"], 40)

    def test_hardening_golden_3_unusable_second_observation_does_not_roll_back_existing_fill(self):
        order = self._new_market_order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(round1["filled_qty"], 40)
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, data_freshness="STALE"), now=later)
        self.assertEqual(round2["filled_qty"], 40)
        self.assertEqual(round2["status"], "PARTIAL_FILLED")

    def test_hardening_golden_4_quantity_weighted_average_fill_price(self):
        order = self._new_market_order()
        round1 = se.evaluate_shadow_fill(order, observation(ask=1500.0, ask_qty=40), now=NOW)
        self.assertEqual(round1["avg_fill_price"], 1500.0)
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask=1510.0, ask_qty=60), now=later)
        self.assertEqual(round2["filled_qty"], 100)
        # (1500*40 + 1510*60) / 100 = 1506.0
        self.assertAlmostEqual(round2["avg_fill_price"], 1506.0)

    def test_new_total_filled_never_exceeds_requested_qty(self):
        order = self._new_market_order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=90), now=NOW)
        self.assertEqual(round1["filled_qty"], 90)
        later = NOW + timedelta(seconds=5)
        # 2回目のobservationがvisible qty=500（requested全量超）でも、
        # 残数量(10)を超えてfillしない。
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask_qty=500), now=later)
        self.assertEqual(round2["filled_qty"], 100)
        self.assertEqual(round2["remaining_qty"], 0)
        self.assertEqual(round2["status"], "FILLED")

    def test_hardening_golden_10_none_slippage_not_implicitly_converted_to_zero(self):
        """Golden #10: downstream（evaluate_shadow_fillのmerge処理）が
        Noneを0へ暗黙変換しない契約テスト。"""
        order = self._new_market_order()
        out = se.evaluate_shadow_fill(order, observation(), now=NOW)
        self.assertIsNone(out["slippage_yen"])
        self.assertIsNone(out["slippage_bps"])
        self.assertNotEqual(out["slippage_yen"], 0)
        self.assertEqual(out["slippage_model_status"], "NOT_MODELED_V0_1")


class ObservationChronologyTests(unittest.TestCase):
    """Phase 5.0.2 hardening Blocker 2（C-060-GPT comment 5708285624）:
    同一/古いMarketObservationの再適用でfillを二重計上できない。"""

    def _partial_order(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        order = submit(intent, risk_decision(), ticket(intent))
        return se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)

    def test_hardening_golden_4_replaying_same_observation_does_not_increase_fill(self):
        round1 = self._partial_order()
        self.assertEqual(round1["filled_qty"], 40)
        replay = se.evaluate_shadow_fill(round1, observation(ask_qty=40), now=NOW)
        self.assertEqual(replay["filled_qty"], 40)
        self.assertEqual(replay["fill_reason"], "DUPLICATE_OBSERVATION")

    def test_hardening_golden_5_older_observation_does_not_increase_fill(self):
        round1 = self._partial_order()
        self.assertEqual(round1["filled_qty"], 40)
        older = observation(observed_at=NOW - timedelta(seconds=1), ask_qty=40)
        out = se.evaluate_shadow_fill(round1, older, now=NOW)
        self.assertEqual(out["filled_qty"], 40)
        self.assertEqual(out["fill_reason"], "OUT_OF_ORDER_OBSERVATION")

    def test_hardening_golden_6_strictly_newer_observation_accumulates_normally(self):
        round1 = self._partial_order()
        self.assertEqual(round1["filled_qty"], 40)
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask_qty=60), now=later)
        self.assertEqual(round2["filled_qty"], 100)
        self.assertEqual(round2["status"], "FILLED")

    def test_last_applied_observation_at_advances(self):
        round1 = self._partial_order()
        self.assertEqual(round1["last_applied_observation_at"], NOW)


class ShadowOrderStateIntegrityTests(unittest.TestCase):
    """Phase 5.0.2 hardening Blocker 3（C-060-GPT comment 5708285624）:
    壊れた既存shadow stateを推測補正せずfail-closedにする。"""

    def _order(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        return submit(intent, risk_decision(), ticket(intent))

    def test_hardening_golden_7_negative_filled_qty_fails_closed(self):
        corrupted = {**self._order(), "filled_qty": -5}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILLED_QTY_INVALID", out["reject_reasons"])

    def test_hardening_golden_7_nan_filled_qty_fails_closed(self):
        corrupted = {**self._order(), "filled_qty": float("nan")}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILLED_QTY_INVALID", out["reject_reasons"])

    def test_hardening_golden_7_fractional_filled_qty_fails_closed(self):
        corrupted = {**self._order(), "filled_qty": 40.5, "remaining_qty": 59.5}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILLED_QTY_INVALID", out["reject_reasons"])

    def test_hardening_golden_8_remaining_qty_inconsistent_fails_closed(self):
        corrupted = {**self._order(), "filled_qty": 40, "remaining_qty": 999}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_REMAINING_QTY_INCONSISTENT", out["reject_reasons"])

    def test_hardening_golden_9_filled_qty_positive_but_avg_fill_price_missing_fails_closed(self):
        corrupted = {**self._order(), "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": None}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_AVG_FILL_PRICE_INVALID", out["reject_reasons"])

    def test_hardening_golden_9_avg_fill_price_non_positive_fails_closed(self):
        corrupted = {**self._order(), "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 0.0}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_AVG_FILL_PRICE_INVALID", out["reject_reasons"])

    def test_requested_qty_invalid_fails_closed(self):
        corrupted = {**self._order(), "requested_qty": 0}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_REQUESTED_QTY_INVALID", out["reject_reasons"])

    def test_fill_model_version_mismatch_fails_closed(self):
        corrupted = {**self._order(), "shadow_fill_model_version": "shadow-fill-model-9.9"}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILL_MODEL_VERSION_MISMATCH", out["reject_reasons"])

    def test_real_submit_allowed_true_fails_closed(self):
        corrupted = {**self._order(), "real_submit_allowed": True}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_REAL_SUBMIT_ALLOWED_NOT_FALSE", out["reject_reasons"])

    def test_healthy_new_order_passes_state_validation(self):
        order = self._order()
        out = se.evaluate_shadow_fill(order, observation(), now=NOW)
        self.assertNotEqual(out["status"], "REJECTED")

    def test_corrupted_filled_state_does_not_get_silently_reset_to_zero(self):
        """壊れたfilled_qtyが0へ黙って補正され処理が継続してしまわない
        ことを確認する——REJECTEDへfail closedし、filled_qtyの値自体は
        書き換えない（推測補正しない）。"""
        corrupted = {**self._order(), "filled_qty": -5}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["filled_qty"], -5)
        self.assertEqual(out["status"], "REJECTED")

    def test_rejected_and_duplicate_ignored_records_skip_state_validation(self):
        """REJECTED/DUPLICATE_IGNOREDはrequested_qty等の完全なスキーマを
        持たない最小フィールドの辞書のため、state-integrity検証の対象
        から除外される（誤ってREJECTED_STATE_*で再REJECTされない）。"""
        intent = build_intent()
        rejected = submit(intent, risk_decision(decision="BLOCK"), ticket(intent))
        out = se.evaluate_shadow_fill(rejected, observation(), now=NOW)
        self.assertEqual(out, rejected)
        self.assertNotIn("REJECTED_STATE_REQUESTED_QTY_INVALID", out.get("reject_reasons", []))


class StateMachineIntegrityTests(unittest.TestCase):
    """Phase 5.0.3 hardening（C-060R-GPT comment 5708645191）: statusと
    数量の整合性、chronology各フィールドのfail-closed検証、
    submission_context_fingerprintによるsubmitted_atのdeterministic
    binding。"""

    def _order(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        return submit(intent, risk_decision(), ticket(intent))

    def test_golden_1_filled_with_partial_quantities_rejected(self):
        corrupted = {**self._order(), "status": "FILLED", "filled_qty": 40, "remaining_qty": 60,
                     "avg_fill_price": 1500.0}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_STATUS_QUANTITY_MISMATCH", out["reject_reasons"])

    def test_golden_2_filled_with_zero_fill_rejected(self):
        corrupted = {**self._order(), "status": "FILLED"}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_STATUS_QUANTITY_MISMATCH", out["reject_reasons"])

    def test_golden_3_partial_filled_with_filled_zero_rejected(self):
        corrupted = {**self._order(), "status": "PARTIAL_FILLED"}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_STATUS_QUANTITY_MISMATCH", out["reject_reasons"])

    def test_golden_3_partial_filled_with_filled_equals_requested_rejected(self):
        corrupted = {**self._order(), "status": "PARTIAL_FILLED", "filled_qty": 100,
                     "remaining_qty": 0, "avg_fill_price": 1500.0}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_STATUS_QUANTITY_MISMATCH", out["reject_reasons"])

    def test_golden_4_unknown_status_rejected(self):
        corrupted = {**self._order(), "status": "BOGUS_STATUS"}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_STATUS_INVALID", out["reject_reasons"])

    def test_golden_4_missing_status_rejected(self):
        order = self._order()
        corrupted = {k: v for k, v in order.items() if k != "status"}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_STATUS_INVALID", out["reject_reasons"])

    def test_golden_5_missing_submitted_at_rejected(self):
        corrupted = {**self._order(), "submitted_at": None}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_SUBMITTED_AT_INVALID", out["reject_reasons"])

    def test_golden_5_naive_submitted_at_rejected(self):
        corrupted = {**self._order(), "submitted_at": datetime(2026, 9, 17, 8, 59, 0)}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_SUBMITTED_AT_INVALID", out["reject_reasons"])

    def test_golden_5_future_submitted_at_rejected(self):
        corrupted = {**self._order(), "submitted_at": NOW + timedelta(seconds=1)}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_SUBMITTED_AT_INVALID", out["reject_reasons"])

    def test_golden_6_naive_last_applied_observation_at_rejected_no_exception(self):
        corrupted = {**self._order(), "last_applied_observation_at": datetime(2026, 9, 17, 8, 59, 0)}
        try:
            out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"evaluate_shadow_fill raised {exc!r} instead of failing closed")
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_LAST_APPLIED_OBSERVATION_AT_INVALID", out["reject_reasons"])

    def test_golden_7_last_applied_observation_at_before_submitted_at_rejected(self):
        corrupted = {**self._order(), "last_applied_observation_at": SUBMITTED_AT - timedelta(seconds=1)}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_LAST_APPLIED_OBSERVATION_AT_INVALID", out["reject_reasons"])

    def test_golden_7_last_applied_observation_at_future_rejected(self):
        corrupted = {**self._order(), "last_applied_observation_at": NOW + timedelta(seconds=1)}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_LAST_APPLIED_OBSERVATION_AT_INVALID", out["reject_reasons"])

    def test_golden_8_fill_at_present_while_unfilled_rejected(self):
        corrupted = {**self._order(), "fill_at": NOW}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILL_AT_INVALID", out["reject_reasons"])

    def test_golden_9_filled_positive_with_missing_fill_at_rejected(self):
        corrupted = {**self._order(), "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                     "status": "PARTIAL_FILLED", "fill_at": None}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILL_AT_INVALID", out["reject_reasons"])

    def test_golden_9_filled_positive_with_naive_fill_at_rejected(self):
        corrupted = {**self._order(), "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                     "status": "PARTIAL_FILLED", "fill_at": datetime(2026, 9, 17, 8, 59, 0)}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILL_AT_INVALID", out["reject_reasons"])

    def test_golden_9_filled_positive_with_pre_submit_fill_at_rejected(self):
        corrupted = {**self._order(), "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                     "status": "PARTIAL_FILLED", "fill_at": SUBMITTED_AT - timedelta(seconds=1)}
        out = se.evaluate_shadow_fill(corrupted, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FILL_AT_INVALID", out["reject_reasons"])

    def test_golden_10_pre_submit_observation_does_not_set_first_observation_at(self):
        order = self._order()
        self.assertIsNone(order["first_observation_at"])
        early = observation(observed_at=SUBMITTED_AT - timedelta(seconds=1))
        out = se.evaluate_shadow_fill(order, early, now=NOW)
        self.assertIsNone(out["first_observation_at"])

    def test_golden_11_mutated_submitted_at_with_stale_fingerprint_rejected(self):
        order = self._order()
        tampered = {**order, "submitted_at": order["submitted_at"] + timedelta(seconds=1)}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_SUBMISSION_CONTEXT_MISMATCH", out["reject_reasons"])

    def test_golden_12_healthy_new_partial_filled_chronology_passes(self):
        order = self._order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(round1["status"], "PARTIAL_FILLED")
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask_qty=60), now=later)
        self.assertEqual(round2["status"], "FILLED")

    def test_submission_context_fingerprint_stored_and_matches(self):
        order = self._order()
        expected = se.compute_submission_context_fingerprint(order["shadow_order_id"], order["submitted_at"])
        self.assertEqual(order["submission_context_fingerprint"], expected)


class OrderIdentityAndFillChronologyTests(unittest.TestCase):
    """Phase 5.0.4 hardening（C-062R-GPT comment 5708835773）: 発行時に
    保存した`order_context_fingerprint`によるIntent/RiskDecision/ticket
    由来フィールドのdeterministic binding（Blocker A）、完全なchronology
    不変条件（Blocker B）、`first_fill_at`/`last_fill_at`の新設
    （Blocker C）。"""

    def _order(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        return submit(intent, risk_decision(), ticket(intent))

    def test_order_context_fingerprint_stored_and_matches(self):
        order = self._order()
        expected = se.compute_order_context_fingerprint(
            shadow_order_id=order["shadow_order_id"], intent_hash=order["intent_hash"],
            merge_hash=order["merge_hash"], ticket_fingerprint=order["ticket_fingerprint"],
            symbol=order["symbol"], side=order["side"], order_type=order["order_type"],
            limit_price=order["limit_price"], requested_qty=order["requested_qty"],
            shadow_fill_model_version=order["shadow_fill_model_version"], submitted_at=order["submitted_at"],
        )
        self.assertEqual(order["order_context_fingerprint"], expected)

    # --- Blocker A: order identity binding ------------------------------------
    def test_golden_a1_partial_then_side_mutated_rejected_no_further_fill(self):
        order = self._order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(round1["filled_qty"], 40)
        tampered = {**round1, "side": "SELL"}
        later = NOW + timedelta(seconds=5)
        out = se.evaluate_shadow_fill(tampered, observation(observed_at=later, bid_qty=60), now=later)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_ORDER_CONTEXT_MISMATCH", out["reject_reasons"])
        self.assertEqual(out["filled_qty"], 40)

    def test_golden_a2_mutated_requested_qty_with_consistent_remaining_still_rejected(self):
        order = self._order()
        tampered = {**order, "requested_qty": 200, "remaining_qty": 200}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_ORDER_CONTEXT_MISMATCH", out["reject_reasons"])

    def test_golden_a3_mutating_any_identity_field_fails_closed(self):
        order = self._order()
        for field, value in [
            ("symbol", "9999.T"),
            ("order_type", "LIMIT"),
            ("limit_price", 1234.0),
            ("intent_hash", "0" * 64),
            ("merge_hash", "z" * 64),
            ("ticket_fingerprint", "different-fp"),
            ("shadow_fill_model_version", "shadow-fill-model-9.9"),
        ]:
            tampered = {**order, field: value}
            out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
            self.assertEqual(out["status"], "REJECTED", msg=field)
            self.assertIn("REJECTED_STATE_ORDER_CONTEXT_MISMATCH", out["reject_reasons"], msg=field)

    def test_golden_a4_mutated_shadow_order_id_rejected(self):
        order = self._order()
        tampered = {**order, "shadow_order_id": "0" * 64}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_SHADOW_ORDER_ID_MISMATCH", out["reject_reasons"])

    # --- Blocker B: complete chronology invariants -----------------------------
    def test_golden_b1_future_first_observation_at_without_watermark_rejected(self):
        order = self._order()
        tampered = {**order, "first_observation_at": NOW + timedelta(seconds=5)}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FIRST_OBSERVATION_AT_INVALID", out["reject_reasons"])

    def test_golden_b2_first_observation_at_without_last_applied_rejected(self):
        order = self._order()
        tampered = {**order, "first_observation_at": NOW}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_LAST_APPLIED_OBSERVATION_AT_INVALID", out["reject_reasons"])

    def test_golden_b3_filled_positive_without_observation_watermark_rejected(self):
        order = self._order()
        tampered = {**order, "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                    "status": "PARTIAL_FILLED", "first_fill_at": NOW, "last_fill_at": NOW, "fill_at": NOW}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW)
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FIRST_OBSERVATION_AT_INVALID", out["reject_reasons"])
        self.assertIn("REJECTED_STATE_LAST_APPLIED_OBSERVATION_AT_INVALID", out["reject_reasons"])

    def test_golden_b4_first_observation_after_first_fill_rejected(self):
        order = self._order()
        tampered = {**order, "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                    "status": "PARTIAL_FILLED",
                    "first_observation_at": NOW + timedelta(seconds=2),
                    "last_applied_observation_at": NOW + timedelta(seconds=2),
                    "first_fill_at": NOW, "last_fill_at": NOW, "fill_at": NOW}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW + timedelta(seconds=10))
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FIRST_FILL_AT_INVALID", out["reject_reasons"])

    def test_golden_b4_first_fill_after_last_fill_rejected(self):
        order = self._order()
        tampered = {**order, "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                    "status": "PARTIAL_FILLED",
                    "first_observation_at": NOW, "last_applied_observation_at": NOW + timedelta(seconds=5),
                    "first_fill_at": NOW + timedelta(seconds=3), "last_fill_at": NOW + timedelta(seconds=1),
                    "fill_at": NOW + timedelta(seconds=1)}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW + timedelta(seconds=10))
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_FIRST_FILL_AT_INVALID", out["reject_reasons"])

    def test_golden_b4_last_fill_after_watermark_rejected(self):
        order = self._order()
        tampered = {**order, "filled_qty": 40, "remaining_qty": 60, "avg_fill_price": 1500.0,
                    "status": "PARTIAL_FILLED",
                    "first_observation_at": NOW, "last_applied_observation_at": NOW + timedelta(seconds=2),
                    "first_fill_at": NOW, "last_fill_at": NOW + timedelta(seconds=5),
                    "fill_at": NOW + timedelta(seconds=5)}
        out = se.evaluate_shadow_fill(tampered, observation(), now=NOW + timedelta(seconds=10))
        self.assertEqual(out["status"], "REJECTED")
        self.assertIn("REJECTED_STATE_LAST_FILL_AT_INVALID", out["reject_reasons"])

    # --- Blocker C: first_fill_at / last_fill_at --------------------------------
    def test_golden_9_partial_then_completion_first_fill_at_preserved(self):
        order = self._order()
        round1 = se.evaluate_shadow_fill(order, observation(ask_qty=40), now=NOW)
        self.assertEqual(round1["first_fill_at"], NOW)
        self.assertEqual(round1["last_fill_at"], NOW)
        later = NOW + timedelta(seconds=5)
        round2 = se.evaluate_shadow_fill(round1, observation(observed_at=later, ask_qty=60), now=later)
        self.assertEqual(round2["first_fill_at"], NOW)
        self.assertEqual(round2["last_fill_at"], later)

    def test_golden_10_one_shot_full_fill_first_equals_last_fill_at(self):
        order = self._order()
        out = se.evaluate_shadow_fill(order, observation(), now=NOW)
        self.assertEqual(out["first_fill_at"], out["last_fill_at"])
        self.assertEqual(out["fill_at"], out["last_fill_at"])


class RealSubmitAllowedTests(unittest.TestCase):
    """Golden #19: real_submit_allowedは常にfalse。"""

    def test_new_order_real_submit_allowed_false(self):
        intent = build_intent()
        out = submit(intent, risk_decision(), ticket(intent))
        self.assertIs(out["real_submit_allowed"], False)

    def test_rejected_real_submit_allowed_false(self):
        intent = build_intent()
        out = submit(intent, risk_decision(decision="BLOCK"), ticket(intent))
        self.assertIs(out["real_submit_allowed"], False)

    def test_evaluated_fill_real_submit_allowed_false(self):
        intent = build_intent(order_type="MARKET", limit_price=None)
        order = submit(intent, risk_decision(), ticket(intent))
        out = se.evaluate_shadow_fill(order, observation(), now=NOW)
        self.assertIs(out["real_submit_allowed"], False)


class NoBrokerReferenceTests(unittest.TestCase):
    """Golden #18: RssOrder/broker/COM/network/Excel発注のside effectがゼロ。
    Golden #20: data/private/trade_ledger.jsonl（Real ledger）へ一切書かない。
    """

    def test_shadow_execution_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/shadow_execution.py")

    def test_shadow_fill_model_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/shadow_fill_model.py")

    def _assert_clean(self, path):
        """AST上の実行コードノードだけを検査する（docstringがtrade_ledger等の
        境界説明を含むこと自体は許容する——単純な文字列includeだと、その
        安全性の説明そのものが引っかかってしまうため）。"""
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_names = {"RssOrder", "win32com", "pywin32", "xlwings", "openpyxl"}
        forbidden_modules = {"win32com", "requests", "urllib", "socket", "http", "xlwings", "openpyxl"}
        forbidden_calls = {"open", "write_text", "write", "read_text", "read"}
        found = set()
        imported = set()
        io_calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            elif isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
                if name in forbidden_calls:
                    io_calls.add(name)
        self.assertEqual(found, set())
        self.assertEqual(imported & forbidden_modules, set())
        self.assertEqual(io_calls, set(), "shadow core must perform no file I/O at all")


if __name__ == "__main__":
    unittest.main()
