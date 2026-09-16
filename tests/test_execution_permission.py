import importlib.util
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
ep = _load('ep', 'scripts/execution_permission.py')

NOW = datetime(2026, 9, 17, 9, 0, 0, tzinfo=JST)

POLICY = {
    "policy_version": "execution-safety-0.1.0",
    "max_ticket_age_sec": 15,
    "max_price_drift_bps": 50,
    "authorization_ttl_sec": 3600,
    "master_kill_ttl_sec": 3600,
    "daily_stop_yen": 3000,
    "max_open_positions": 1,
}


def iso(dt: datetime) -> str:
    return dt.isoformat()


def build_intent(**overrides):
    kwargs = dict(
        symbol="285A.T", side="BUY", quantity=100, order_type="LIMIT",
        limit_price=1500.0, planned_entry=1500.0, planned_stop=1450.0, planned_target=1600.0,
        strategy_id="day_ifo_long", strategy_version="1.0",
        decision_snapshot_id="snap-1", signal_known_at="2026-09-17T08:55:00+09:00",
        risk_policy_version="risk-gate-0.1.0", execution_policy_version="exec-v0.1",
        shadow_fill_model_version="shadow-v0.1",
    )
    kwargs.update(overrides)
    return ec.build_intent(**kwargs)


def risk_decision(**overrides):
    base = {
        "decision": "PASS", "merge_hash": "m" * 64, "allowed_qty": 100,
        "symbol": "285A.T", "side": "BUY", "horizon": "day",
        "policy_version": "risk-gate-0.1.0",
    }
    base.update(overrides)
    return base


def snapshot(**overrides):
    base = {
        "kill_switch": {"status": "ARMED", "armed_at": iso(NOW - timedelta(seconds=60)),
                         "expires_at": iso(NOW + timedelta(seconds=3600))},
        "human_session_authorized": True,
        "authorization_expires_at": iso(NOW + timedelta(seconds=3600)),
        "authorization_session_id": "sess-1",
        "data_freshness": "OK",
        "market_session_allowed": True,
        "symbol_tradeable": True,
        "broker_link_health": "OK",
        "expected_position_qty": 0,
        "broker_position_qty": 0,
        "buying_power_check": True,
        "short_availability_check": True,
        "realized_pnl_today_yen": 0.0,
        "open_positions_count": 0,
        "known_intents": [],
        "pending_orders": [],
        "price_tick_valid": True,
        "qty_lot_valid": True,
        "quote_price": 1500.0,
        "quote_asof": iso(NOW - timedelta(seconds=3)),
        "ticket_created_at": iso(NOW - timedelta(seconds=5)),
        "broker_snapshot_fingerprint": "broker-fp-1",
    }
    base.update(overrides)
    return base


def evaluate(intent=None, decision=None, snap=None, policy=None, now=NOW):
    return ep.evaluate_permission(
        intent if intent is not None else build_intent(),
        decision if decision is not None else risk_decision(),
        snap if snap is not None else snapshot(),
        policy or POLICY, now=now,
    )


class HappyPathTests(unittest.TestCase):
    def test_all_gates_pass_gives_order_ticket_ready(self):
        out = evaluate()
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")
        self.assertEqual(out["block_reasons"], [])
        self.assertIsNotNone(out["ticket_fingerprint"])


class CanonicalIntentHashTests(unittest.TestCase):
    """Golden: canonical intent_hashをPhase 4が再計算仕様変更しない。"""

    def test_evaluate_permission_does_not_alter_intent_hash_semantics(self):
        intent = build_intent()
        original_hash = intent["intent_hash"]
        self.assertEqual(original_hash, ec.compute_intent_hash(intent))
        evaluate(intent)
        # 呼び出し後もintentは変更されておらず、canonical hashも再計算可能なまま。
        self.assertEqual(intent["intent_hash"], original_hash)
        self.assertEqual(ec.compute_intent_hash(intent), original_hash)

    def test_tampered_intent_hash_is_blocked(self):
        """Golden: tampered Intentでintent_hash != compute_intent_hash(intent) → BLOCK。"""
        intent = build_intent()
        intent = {**intent, "intent_hash": "0" * 64}
        out = evaluate(intent)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_INTENT_HASH_TAMPERED", out["block_reasons"])

    def test_tampered_quantity_without_rehash_is_blocked(self):
        """qtyだけ書き換えてhashを再計算しなかった場合も、同じくtampered検知で拾われる。"""
        intent = build_intent()
        intent = {**intent, "quantity": 999}
        out = evaluate(intent)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_INTENT_HASH_TAMPERED", out["block_reasons"])


class RealSubmitAllowedTests(unittest.TestCase):
    """Golden: real_submit_allowedをTrueへ変更する経路がない。"""

    def test_output_never_contains_real_submit_allowed(self):
        out = evaluate()
        self.assertNotIn("real_submit_allowed", out)

    def test_input_intent_real_submit_allowed_stays_false_after_call(self):
        intent = build_intent()
        self.assertIs(intent["real_submit_allowed"], False)
        evaluate(intent)
        self.assertIs(intent["real_submit_allowed"], False)

    def test_tampered_real_submit_allowed_true_is_blocked(self):
        intent = build_intent()
        tampered = {**intent, "real_submit_allowed": True}
        out = evaluate(tampered)
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_REAL_SUBMIT_ALLOWED_TAMPERED", out["block_reasons"])

    def test_build_intent_does_not_accept_real_submit_allowed_argument(self):
        with self.assertRaises(TypeError):
            build_intent(real_submit_allowed=True)


class RiskGateGateTests(unittest.TestCase):
    def test_risk_gate_not_pass_blocks(self):
        for bad_decision in ("SHADOW_ONLY", "BLOCK"):
            out = evaluate(decision=risk_decision(decision=bad_decision))
            self.assertEqual(out["permission_status"], "BLOCKED", msg=bad_decision)
            self.assertIn("BLOCK_RISK_GATE_NOT_PASS", out["block_reasons"])


class MasterKillTests(unittest.TestCase):
    def test_default_kill_switch_state_is_disarmed(self):
        """Golden: master kill default DISARMED / restartで再ARMしない。"""
        state = ep.default_kill_switch_state()
        self.assertEqual(state["status"], "DISARMED")

    def test_disarmed_kill_switch_blocks(self):
        out = evaluate(snap=snapshot(kill_switch=ep.default_kill_switch_state()))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_DISARMED", out["block_reasons"])

    def test_missing_kill_switch_blocks(self):
        out = evaluate(snap=snapshot(kill_switch={}))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_DISARMED", out["block_reasons"])

    def test_expired_kill_switch_blocks(self):
        expired = {"status": "ARMED", "armed_at": iso(NOW - timedelta(hours=2)),
                   "expires_at": iso(NOW - timedelta(seconds=1))}
        out = evaluate(snap=snapshot(kill_switch=expired))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_EXPIRED", out["block_reasons"])

    def test_naive_expiry_timestamp_blocks(self):
        naive = {"status": "ARMED", "armed_at": iso(NOW), "expires_at": "2026-09-17T10:00:00"}
        out = evaluate(snap=snapshot(kill_switch=naive))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MASTER_KILL_EXPIRY_INVALID", out["block_reasons"])


class UnknownGateTests(unittest.TestCase):
    """Golden: UNKNOWN gate → BLOCK（missing/None/非Trueは全てPASSではない）。"""

    def test_missing_human_authorization_blocks(self):
        out = evaluate(snap=snapshot(human_session_authorized=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_HUMAN_AUTHORIZATION_MISSING", out["block_reasons"])

    def test_unknown_data_freshness_blocks(self):
        out = evaluate(snap=snapshot(data_freshness="UNKNOWN"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DATA_FRESHNESS_NOT_OK", out["block_reasons"])

    def test_unknown_broker_link_health_blocks(self):
        out = evaluate(snap=snapshot(broker_link_health="UNKNOWN"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_BROKER_LINK_UNHEALTHY", out["block_reasons"])

    def test_missing_buying_power_check_blocks(self):
        out = evaluate(snap=snapshot(buying_power_check=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_BUYING_POWER_NOT_CONFIRMED", out["block_reasons"])

    def test_missing_price_tick_or_lot_validity_blocks(self):
        out = evaluate(snap=snapshot(price_tick_valid=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        out2 = evaluate(snap=snapshot(qty_lot_valid=None))
        self.assertEqual(out2["permission_status"], "BLOCKED")


class AuthorizationExpiryTests(unittest.TestCase):
    def test_expired_authorization_blocks(self):
        out = evaluate(snap=snapshot(authorization_expires_at=iso(NOW - timedelta(seconds=1))))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRED", out["block_reasons"])

    def test_naive_authorization_expiry_blocks(self):
        """Golden: naive timestamp → BLOCK。"""
        out = evaluate(snap=snapshot(authorization_expires_at="2026-09-17T10:00:00"))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_AUTHORIZATION_EXPIRY_INVALID", out["block_reasons"])


class PositionReconciliationTests(unittest.TestCase):
    def test_position_mismatch_blocks(self):
        """Golden: position mismatch → BLOCK。"""
        out = evaluate(snap=snapshot(expected_position_qty=0, broker_position_qty=100))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_POSITION_RECONCILIATION", out["block_reasons"])

    def test_short_without_shortable_confirmation_blocks(self):
        sell_intent = build_intent(side="SELL", limit_price=1500.0, planned_entry=1500.0,
                                    planned_stop=1550.0)
        out = evaluate(sell_intent, decision=risk_decision(side="SELL"),
                        snap=snapshot(short_availability_check=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_SHORT_AVAILABILITY_NOT_CONFIRMED", out["block_reasons"])


class DailyStopAndMaxPositionsDefenseInDepthTests(unittest.TestCase):
    """Golden: daily stop / max position → defense-in-depthでBLOCK
    （Risk Gateが既にPASSしていても、Permission Gate側でも独立に再確認する）。"""

    def test_daily_stop_reached_blocks(self):
        out = evaluate(snap=snapshot(realized_pnl_today_yen=-3000.0))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DAILY_STOP_REACHED", out["block_reasons"])

    def test_max_open_positions_reached_blocks(self):
        out = evaluate(snap=snapshot(open_positions_count=1))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_MAX_OPEN_POSITIONS_REACHED", out["block_reasons"])

    def test_unknown_realized_pnl_blocks(self):
        out = evaluate(snap=snapshot(realized_pnl_today_yen=None))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_REALIZED_PNL_UNKNOWN", out["block_reasons"])


class DuplicateGuardTests(unittest.TestCase):
    def test_duplicate_exact_intent_hash_blocks(self):
        """Golden: duplicate exact intent_hash → BLOCK。"""
        intent = build_intent()
        known = [{"intent_hash": intent["intent_hash"], "status": "TICKET_READY"}]
        out = evaluate(intent, snap=snapshot(known_intents=known))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_INTENT_HASH", out["block_reasons"])

    def test_pending_unknown_intent_blocks_no_auto_retry(self):
        """Golden: pending/UNKNOWN intent → BLOCK、auto retryなし。"""
        intent = build_intent()
        known = [{"intent_hash": intent["intent_hash"], "status": "UNKNOWN"}]
        out = evaluate(intent, snap=snapshot(known_intents=known))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_PENDING_UNKNOWN", out["block_reasons"])

    def test_pending_order_same_symbol_side_blocks(self):
        pending = [{"symbol": "285A.T", "side": "BUY", "qty": 100}]
        out = evaluate(snap=snapshot(pending_orders=pending))
        self.assertEqual(out["permission_status"], "BLOCKED")
        self.assertIn("BLOCK_DUPLICATE_PENDING", out["block_reasons"])


class PriceDriftTests(unittest.TestCase):
    def test_stale_quote_requires_requote(self):
        """Golden: stale quote → BLOCK（ここではEXPIRED_REQUOTE_REQUIRED、既存Intentを
        書き換えず新しいIntentを作り直す前提の専用ステータス）。"""
        out = evaluate(snap=snapshot(quote_asof=iso(NOW - timedelta(seconds=60))))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("EXPIRED_QUOTE_STALE", out["block_reasons"])

    def test_stale_ticket_requires_requote(self):
        out = evaluate(snap=snapshot(ticket_created_at=iso(NOW - timedelta(seconds=60))))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("EXPIRED_TICKET_AGE", out["block_reasons"])

    def test_price_drift_beyond_threshold_requires_requote(self):
        """Golden: ticket ready直前のprice drift → requote required。"""
        drifted_quote = 1500.0 * 1.01  # 100bps drift > 50bps threshold
        out = evaluate(snap=snapshot(quote_price=drifted_quote))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("EXPIRED_PRICE_DRIFT", out["block_reasons"])

    def test_small_drift_within_threshold_still_passes(self):
        tiny_drift_quote = 1500.0 * 1.001  # 10bps < 50bps threshold
        out = evaluate(snap=snapshot(quote_price=tiny_drift_quote))
        self.assertEqual(out["permission_status"], "ORDER_TICKET_READY")

    def test_naive_quote_asof_blocks(self):
        out = evaluate(snap=snapshot(quote_asof="2026-09-17T08:59:57"))
        self.assertEqual(out["permission_status"], "EXPIRED_REQUOTE_REQUIRED")
        self.assertIn("BLOCK_TIMESTAMP_NOT_TIMEZONE_AWARE", out["block_reasons"])


class ReconfirmationTests(unittest.TestCase):
    """人の確認直前のチェックポイント②（C-053第7節・第9節）。"""

    def _fresh_snapshot(self, **overrides):
        # デフォルトはevaluate()が使うsnapshot()と完全に同じ観測（同じquote_asof/
        # ticket_created_at）にして「本当に何も変わっていない」ケースを表す。
        # quote_asofが変わる（＝新しい気配を取り直した）こと自体がfingerprintの
        # 構成要素なので、意図的にstaleでない新しいtimestampへ変えるテストは
        # 別途test_new_quote_observation_requires_reconfirmで確認する。
        base = {
            "quote_price": 1500.0, "quote_asof": iso(NOW - timedelta(seconds=3)),
            "ticket_created_at": iso(NOW - timedelta(seconds=5)),
            "planned_entry": 1500.0, "merge_hash": "m" * 64,
            "risk_policy_version": "risk-gate-0.1.0", "allowed_qty": 100,
            "authorization_session_id": "sess-1",
            "authorization_expires_at": iso(NOW + timedelta(seconds=3600)),
            "broker_snapshot_fingerprint": "broker-fp-1",
        }
        base.update(overrides)
        return base

    def test_unchanged_snapshot_gives_confirm_ready(self):
        ticket = evaluate()
        out = ep.evaluate_reconfirmation(ticket, self._fresh_snapshot(), POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "CONFIRM_READY")

    def test_price_drift_before_confirm_requires_requote(self):
        """Golden: human confirm直前のprice drift → requote required。"""
        ticket = evaluate()
        drifted = self._fresh_snapshot(quote_price=1500.0 * 1.01)
        out = ep.evaluate_reconfirmation(ticket, drifted, POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "EXPIRED_REQUOTE_REQUIRED")

    def test_fingerprint_change_requires_reconfirm(self):
        """Golden: permission/ticket fingerprint変更 → reconfirm required。"""
        ticket = evaluate()
        changed = self._fresh_snapshot(broker_snapshot_fingerprint="broker-fp-DIFFERENT")
        out = ep.evaluate_reconfirmation(ticket, changed, POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "RECONFIRM_REQUIRED")
        self.assertIn("TICKET_FINGERPRINT_CHANGED", out["block_reasons"])

    def test_new_quote_observation_requires_reconfirm(self):
        """quote/asofもfingerprintの構成要素（C-053第9節）なので、価格が同じでも
        新しい気配を取り直した（quote_asofが変わった）だけでreconfirmが必要になる
        ——古い確認画面を黙って使い回さないための設計。"""
        ticket = evaluate()
        refetched = self._fresh_snapshot(quote_asof=iso(NOW - timedelta(seconds=1)))
        out = ep.evaluate_reconfirmation(ticket, refetched, POLICY, now=NOW + timedelta(seconds=2))
        self.assertEqual(out["reconfirm_status"], "RECONFIRM_REQUIRED")

    def test_ticket_not_ready_blocks_reconfirmation(self):
        blocked_ticket = evaluate(snap=snapshot(human_session_authorized=None))
        out = ep.evaluate_reconfirmation(blocked_ticket, self._fresh_snapshot(), POLICY, now=NOW)
        self.assertEqual(out["reconfirm_status"], "BLOCKED")
        self.assertIn("BLOCK_TICKET_NOT_READY", out["block_reasons"])


class DeterminismTests(unittest.TestCase):
    def test_same_input_gives_same_decision_ignoring_wall_clock_metadata(self):
        """同一入力（同一nowを明示的に渡す）からは常に同一の判定。判定関数自体は
        datetime.now()を内部で呼ばない。"""
        out_a = evaluate()
        out_b = evaluate()
        strip = lambda d: {k: v for k, v in d.items() if k != "generated_at"}
        self.assertEqual(strip(out_a), strip(out_b))


class NoBrokerReferenceTests(unittest.TestCase):
    def test_execution_permission_has_no_broker_rss_or_network_references(self):
        self._assert_clean(ROOT / "scripts/execution_permission.py")

    def _assert_clean(self, path):
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_names = {"RssOrder", "win32com", "pywin32", "xlwings", "openpyxl"}
        forbidden_modules = {"win32com", "requests", "urllib", "socket", "http", "xlwings", "openpyxl"}
        found = set()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(found, set())
        self.assertEqual(imported & forbidden_modules, set())

    def test_collector_still_has_no_order_submit_path(self):
        """Golden: collectorへorder pathを追加していない（既存の安全境界を
        Phase 4実装が壊していないことのregression guard）。"""
        collector = ROOT / "ms2_live" / "MS2_RSS_100_Collector.ps1"
        source = collector.read_text(encoding="utf-8")
        self.assertNotIn("RssOrder", source)
        self.assertIn("$AutoOrderEnabled = $false", source)


if __name__ == "__main__":
    unittest.main()
