import importlib.util
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[1] / 'scripts/conflict_resolver.py'
spec = importlib.util.spec_from_file_location('cr', SCRIPT_PATH)
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

POLICY = {
    "policy_version": "conflict-policy-0.1",
    "account_lane": "execution_test_300k_v1",
    "max_open_positions": 1,
    "execution_priority": ["day_ifo_long", "day_rank_long", "day_short_mvp"],
}


def signal(code="285A.T", side="LONG", strategy_id="day_ifo_long", ts="2026-09-17T09:18:00+09:00",
           quality="ok", entry=1500.0, stop=1450.0, target=1600.0, snapshot_id=None, horizon="day", **extra):
    return {
        "code": code, "side": side, "strategy_id": strategy_id, "decision_asof": ts,
        "source_quality": quality, "entry": entry, "stop": stop, "target": target,
        "snapshot_id": snapshot_id or f"{strategy_id}-{ts}", "horizon": horizon,
        **extra,
    }


class SingleSignalTests(unittest.TestCase):
    def test_single_long_signal_produces_one_candidate_ready_scenario(self):
        """Golden #1: P0-1 LONGだけ -> 1 scenario。"""
        out = cr.resolve_conflicts([signal()], [], POLICY)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["resolved_status"], "CANDIDATE_READY")
        self.assertEqual(out[0]["side"], "BUY")
        self.assertEqual(out[0]["execution_owner_strategy_id"], "day_ifo_long")
        self.assertEqual(out[0]["confirming_strategy_ids"], [])


class SameSideMergeTests(unittest.TestCase):
    def test_second_same_side_signal_becomes_confirmation_not_new_scenario(self):
        """Golden #2: P0-1 LONG後にP0-4 LONG -> qty増えずconfirmation追加。"""
        s1 = signal(strategy_id="day_ifo_long", ts="2026-09-17T09:18:00+09:00")
        s2 = signal(strategy_id="day_rank_long", ts="2026-09-17T09:19:00+09:00", entry=1510.0, stop=1460.0)
        out = cr.resolve_conflicts([s1, s2], [], POLICY)
        self.assertEqual(len(out), 1)
        scenario = out[0]
        self.assertEqual(scenario["resolved_status"], "CANDIDATE_READY")
        self.assertEqual(scenario["execution_owner_strategy_id"], "day_ifo_long")
        self.assertEqual(scenario["confirming_strategy_ids"], ["day_rank_long"])

    def test_confirming_signal_does_not_rewrite_entry_stop_target(self):
        """Golden #10: confirming strategy追加でentry/stop/targetを書き換えない。"""
        owner = signal(strategy_id="day_ifo_long", ts="2026-09-17T09:18:00+09:00",
                        entry=1500.0, stop=1450.0, target=1600.0)
        confirmer = signal(strategy_id="day_rank_long", ts="2026-09-17T09:19:00+09:00",
                            entry=9999.0, stop=8888.0, target=7777.0)
        out = cr.resolve_conflicts([owner, confirmer], [], POLICY)
        scenario = out[0]
        self.assertEqual(scenario["entry"], 1500.0)
        self.assertEqual(scenario["stop"], 1450.0)
        self.assertEqual(scenario["target"], 1600.0)

    def test_cross_horizon_same_side_merges_into_one_scenario(self):
        """Golden #9: DAYTRADEとSWINGが同symbol -> 1つの候補にmerge（confirmationとして
        added、別の物理scenarioは作らない）。"""
        daytrade = signal(strategy_id="day_ifo_long", horizon="day", ts="2026-09-17T09:18:00+09:00")
        swing = signal(strategy_id="day_rank_long", horizon="swing", ts="2026-09-17T09:19:00+09:00")
        out = cr.resolve_conflicts([daytrade, swing], [], POLICY)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["confirming_strategy_ids"], ["day_rank_long"])

    def test_simultaneous_timestamp_tie_broken_by_execution_priority(self):
        """Golden #3: P0-1とP0-4同時刻 -> config priorityでowner固定。"""
        same_ts = "2026-09-17T09:18:00+09:00"
        lower_priority_first = signal(strategy_id="day_rank_long", ts=same_ts)
        higher_priority_second = signal(strategy_id="day_ifo_long", ts=same_ts)
        out = cr.resolve_conflicts([lower_priority_first, higher_priority_second], [], POLICY)
        # day_ifo_long は execution_priority で day_rank_long より先（index 0 < 1）
        self.assertEqual(out[0]["execution_owner_strategy_id"], "day_ifo_long")

    def test_existing_open_position_absorbs_new_signal_as_confirmation(self):
        open_positions = [{
            "symbol": "285A.T", "side": "BUY", "execution_owner_strategy_id": "day_ifo_long",
            "entry": 1500.0, "stop": 1450.0, "target": 1600.0,
        }]
        new_signal = signal(strategy_id="day_rank_long", entry=9999.0, stop=9999.0, target=9999.0)
        out = cr.resolve_conflicts([new_signal], open_positions, POLICY)
        scenario = out[0]
        self.assertEqual(scenario["resolved_status"], "MERGED_CONFIRMATION")
        self.assertEqual(scenario["execution_owner_strategy_id"], "day_ifo_long")
        self.assertEqual(scenario["entry"], 1500.0)  # from the open position, not the new signal
        self.assertEqual(scenario["confirming_strategy_ids"], ["day_rank_long"])


class OppositeSideConflictTests(unittest.TestCase):
    def test_simultaneous_long_and_short_blocks_both(self):
        """Golden #4: LONG + SHORT同時 -> real lane blocked。"""
        long_sig = signal(strategy_id="day_ifo_long", side="LONG")
        short_sig = signal(strategy_id="day_short_mvp", side="SHORT")
        out = cr.resolve_conflicts([long_sig, short_sig], [], POLICY)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["resolved_status"], "CONFLICT_BLOCKED_OPPOSITE_SIDE")
        self.assertEqual(out[0]["real_submit_allowed"], False)

    def test_new_opposite_signal_does_not_auto_reverse_open_position(self):
        """Golden #5: LONG position OPEN中にSHORT -> auto reverseしない。"""
        open_positions = [{
            "symbol": "285A.T", "side": "BUY", "execution_owner_strategy_id": "day_ifo_long",
            "entry": 1500.0, "stop": 1450.0, "target": 1600.0,
        }]
        short_sig = signal(strategy_id="day_short_mvp", side="SHORT")
        out = cr.resolve_conflicts([short_sig], open_positions, POLICY)
        self.assertEqual(out[0]["resolved_status"], "CONFLICT_BLOCKED_OPPOSITE_SIDE")

    def test_research_signal_ids_preserved_even_when_blocked(self):
        """Golden #11: research ledgerはmerge前のstrategy数を保持（blockedでも消えない）。"""
        long_sig = signal(strategy_id="day_ifo_long", side="LONG", snapshot_id="s1")
        short_sig = signal(strategy_id="day_short_mvp", side="SHORT", snapshot_id="s2")
        out = cr.resolve_conflicts([long_sig, short_sig], [], POLICY)
        self.assertEqual(set(out[0]["research_signal_ids"]), {"s1", "s2"})


class DataQualityTests(unittest.TestCase):
    def test_stale_only_signal_blocked_as_data_quality(self):
        """Golden #8: stale/futureのみ -> physical intentへ昇格しない。"""
        stale = signal(quality="stale")
        out = cr.resolve_conflicts([stale], [], POLICY)
        self.assertEqual(out[0]["resolved_status"], "BLOCKED_DATA_QUALITY")

    def test_stale_signal_ignored_when_ok_signal_also_present(self):
        ok_sig = signal(strategy_id="day_ifo_long", quality="ok")
        stale_sig = signal(strategy_id="day_rank_long", quality="stale")
        out = cr.resolve_conflicts([ok_sig, stale_sig], [], POLICY)
        self.assertEqual(out[0]["resolved_status"], "CANDIDATE_READY")
        self.assertEqual(out[0]["execution_owner_strategy_id"], "day_ifo_long")
        self.assertEqual(out[0]["confirming_strategy_ids"], [])  # stale signal not counted

    def test_wait_side_signal_never_becomes_a_candidate(self):
        wait_sig = signal(side="WAIT", quality="ok")
        out = cr.resolve_conflicts([wait_sig], [], POLICY)
        self.assertEqual(out[0]["resolved_status"], "BLOCKED_DATA_QUALITY")


def _strip_generated_at(scenarios):
    """generated_atは呼び出しごとの実時刻で正当に変わりうるフィールドなので、
    順序非依存性の比較対象からは除く（比較したいのはowner/confirmations/
    merge_hash等の実質的な解決結果であり、壁時計時刻ではない）。"""
    return [{k: v for k, v in s.items() if k != "generated_at"} for s in scenarios]


class OrderIndependenceTests(unittest.TestCase):
    def test_input_order_does_not_affect_result(self):
        """Golden #7/#16: input順序を変えても同じresolve結果。"""
        s1 = signal(strategy_id="day_ifo_long", ts="2026-09-17T09:18:00+09:00")
        s2 = signal(strategy_id="day_rank_long", ts="2026-09-17T09:19:00+09:00")
        out_a = cr.resolve_conflicts([s1, s2], [], POLICY)
        out_b = cr.resolve_conflicts([s2, s1], [], POLICY)
        self.assertEqual(_strip_generated_at(out_a), _strip_generated_at(out_b))

    def test_multi_symbol_order_does_not_affect_result(self):
        a = signal(code="285A.T", strategy_id="day_ifo_long")
        b = signal(code="8035.T", strategy_id="day_rank_long", target=None)
        out_a = cr.resolve_conflicts([a, b], [], {**POLICY, "max_open_positions": 5})
        out_b = cr.resolve_conflicts([b, a], [], {**POLICY, "max_open_positions": 5})
        self.assertEqual(_strip_generated_at(out_a), _strip_generated_at(out_b))


class MergeHashTests(unittest.TestCase):
    def test_merge_hash_key_name_is_never_intent_hash(self):
        """Golden #13: Resolver固有hashは intent_hash という名前を使わない。"""
        out = cr.resolve_conflicts([signal()], [], POLICY)
        for scenario in out:
            self.assertNotIn("intent_hash", scenario)
        self.assertIn("merge_hash", out[0])

    def test_resubmitting_same_signal_gives_same_merge_hash(self):
        """Golden #6 (前半): 同じSignalを2回投入 -> merge_hash一致。"""
        out_a = cr.resolve_conflicts([signal()], [], POLICY)
        out_b = cr.resolve_conflicts([signal()], [], POLICY)
        self.assertEqual(out_a[0]["merge_hash"], out_b[0]["merge_hash"])

    def test_known_merge_hash_blocks_as_duplicate(self):
        """Golden #6 (後半): 2回目はduplicate blocked。"""
        first = cr.resolve_conflicts([signal()], [], POLICY)
        known = {first[0]["merge_hash"]}
        second = cr.resolve_conflicts([signal()], [], POLICY, known_merge_hashes=known)
        self.assertEqual(second[0]["resolved_status"], "BLOCKED_DUPLICATE_ORDER")

    def test_intent_hash_passthrough_is_never_mutated(self):
        """Golden #14: canonical intent_hashを受け取った場合、Resolver通過後も値を
        変更しない——resolve_conflicts()は入力signal dictの intent_hash キーを
        一切読み書きしないことを、元のdictが変化しないことで証明する。"""
        sig = signal()
        sig["intent_hash"] = "deadbeef" * 8
        cr.resolve_conflicts([sig], [], POLICY)
        self.assertEqual(sig["intent_hash"], "deadbeef" * 8)


class RealSubmitAllowedTests(unittest.TestCase):
    def test_always_false_regardless_of_status(self):
        """Golden #12: real_submit_allowed は常にfalseのまま。"""
        long_sig = signal(side="LONG", strategy_id="day_ifo_long")
        short_sig = signal(side="SHORT", strategy_id="day_short_mvp")
        for scenario in cr.resolve_conflicts([long_sig, short_sig], [], POLICY):
            self.assertIs(scenario["real_submit_allowed"], False)

    def test_tampered_input_real_submit_allowed_is_ignored(self):
        """Golden #15: 入力dictが real_submit_allowed=True に改ざんされていても
        Realとして解釈しない。"""
        sig = signal()
        sig["real_submit_allowed"] = True
        out = cr.resolve_conflicts([sig], [], POLICY)
        self.assertIs(out[0]["real_submit_allowed"], False)


class NaiveTimestampTests(unittest.TestCase):
    def test_naive_decision_asof_is_rejected(self):
        """Golden #17: naive timestampを時系列判定に使わない。"""
        sig = signal(ts="2026-09-17T09:18:00")  # no offset
        with self.assertRaises(ValueError):
            cr.resolve_conflicts([sig], [], POLICY)

    def test_offset_aware_timestamp_is_accepted(self):
        sig = signal(ts="2026-09-17T09:18:00+09:00")
        out = cr.resolve_conflicts([sig], [], POLICY)
        self.assertEqual(out[0]["resolved_status"], "CANDIDATE_READY")


class MaxOpenPositionsTests(unittest.TestCase):
    def test_second_symbol_blocked_when_capacity_is_one(self):
        earlier = signal(code="285A.T", strategy_id="day_ifo_long", ts="2026-09-17T09:18:00+09:00")
        later = signal(code="8035.T", strategy_id="day_rank_long", ts="2026-09-17T09:20:00+09:00")
        out = cr.resolve_conflicts([earlier, later], [], POLICY)  # max_open_positions=1
        statuses = {s["symbol"]: s["resolved_status"] for s in out}
        self.assertEqual(statuses["285A.T"], "CANDIDATE_READY")
        self.assertEqual(statuses["8035.T"], "BLOCKED_MAX_OPEN_POSITIONS")

    def test_existing_open_position_counts_against_capacity(self):
        open_positions = [{
            "symbol": "285A.T", "side": "BUY", "execution_owner_strategy_id": "day_ifo_long",
            "entry": 1500.0, "stop": 1450.0, "target": 1600.0,
        }]
        new_symbol_signal = signal(code="8035.T", strategy_id="day_rank_long")
        out = cr.resolve_conflicts([new_symbol_signal], open_positions, POLICY)
        self.assertEqual(out[0]["resolved_status"], "BLOCKED_MAX_OPEN_POSITIONS")


class IsDuplicateScenarioTests(unittest.TestCase):
    def test_matches_by_merge_hash_only(self):
        out = cr.resolve_conflicts([signal()], [], POLICY)
        self.assertTrue(cr.is_duplicate_scenario(out[0], out))

    def test_scenario_without_merge_hash_is_never_duplicate(self):
        blocked = cr.resolve_conflicts([signal(side="WAIT")], [], POLICY)[0]
        self.assertFalse(cr.is_duplicate_scenario(blocked, [blocked]))


class LoadPolicyTests(unittest.TestCase):
    def test_default_policy_file_loads_and_has_required_keys(self):
        policy = cr.load_policy()
        for key in ("policy_version", "account_lane", "max_open_positions", "execution_priority"):
            self.assertIn(key, policy)


class NoBrokerReferenceTests(unittest.TestCase):
    def test_source_has_no_broker_rss_or_network_references(self):
        import ast
        tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
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


if __name__ == "__main__":
    unittest.main()
