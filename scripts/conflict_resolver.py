"""scripts/conflict_resolver.py

Conflict Resolver / Position Merge（GitHub Issue #18 Execution Stack Phase 2、
comment 5702288572の基本設計 + C-048-GPT comment 5702907356の上書き解釈）。

同一symbolで複数戦略が同時・近接発火した場合に、①各戦略の研究上の成績を
壊さず、②現実の口座では1つのphysical positionだけを安全に管理する、という
2つの要求を両立させるための純粋関数レイヤー。scripts/signal_contract.pyの
Signalを受け取り、scripts/execution_contract.pyのExecution Intentを作る前段
として使う（signal_contract → conflict_resolver → execution_contract → Shadow/
Risk Gate、という接続。後段のPhase 3 Risk Gate・Phase 4 Permission Gateは
このコミットでは一切実装しない）。

このファイルも発注・broker/RSS呼び出し・Excel注文式・実ポジション変更は
一切行わない（scripts/execution_contract.pyと同じ境界）。

## C-048-GPTによる上書き解釈（重要）
- `intent_hash`という名前は scripts/execution_contract.py の11フィールド
  SHA256だけがcanonicalに使う。このファイルは同名のhashを絶対に作らない。
  Resolver固有の決定論的キーは`merge_hash`という別名にする。
- 許可フィールド名は`real_submit_allowed`のみ（旧設計案にあった
  `real_order_allowed`は使わない）。このResolverは常にFalseで出力し、
  入力信号に`real_submit_allowed=True`が紛れ込んでいても一切信用しない
  （そもそも読み取らない）。
- signal側の LONG/SHORT は研究語彙として保持してよいが、Execution境界の
  出力では明示的に LONG→BUY・SHORT→SELL へ正規化する。

## このPhase 2が決めないこと（正直な制約）
- 数量（qty）はこのファイルでは一切決めない。Position Sizing/Risk Gate
  （Phase 3、未実装）の責務であり、ここで100株等をダミーで埋めると実装
  されていないPhaseの判断を先取りして見せてしまうため、意図的に出力
  schemaへ含めていない。
- 「real lane」と「shadow lane」の区別自体は、口座残高・証拠金・実際の
  約定余力を知らないこのPhaseでは判定できない。ここで決めるのは
  「conflict抜きの候補として有効か」と「max_open_positions（銘柄横断の
  口座レベル上限）を超えていないか」までで、超えた分は`BLOCKED_MAX_
  OPEN_POSITIONS`として明示し、Shadowへ回すかどうかの実際の判断は
  呼び出し側（将来のOrchestrator）に委ねる。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "conflict-resolver-1.0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT / "config" / "conflict_policy_v0_1.json"

VALID_RESEARCH_SIDES = ("LONG", "SHORT", "WAIT")
_SIDE_NORMALIZE = {"LONG": "BUY", "SHORT": "SELL"}

RESOLVED_STATUSES = (
    "CANDIDATE_READY",
    "MERGED_CONFIRMATION",
    "CONFLICT_BLOCKED_OPPOSITE_SIDE",
    "BLOCKED_MAX_OPEN_POSITIONS",
    "BLOCKED_DUPLICATE_ORDER",
    "BLOCKED_DATA_QUALITY",
)


def now_jst() -> datetime:
    return datetime.now(JST)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict:
    """conflict_policy_v0_1.jsonを読む（I/Oはここだけに閉じ込める。
    resolve_conflicts()自体は純粋関数のまま、policyはdictで受け取る）。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_aware_timestamp(text: str) -> datetime:
    """Golden #17: naive timestampを時系列判定に使わない。offset無しはエラーにする
    （推測でJSTを補完しない——呼び出し側が明示的にoffset付きで渡す責務にする）。"""
    if not text or not isinstance(text, str):
        raise ValueError(f"decision_asof must be a non-empty ISO8601 string, got {text!r}")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"decision_asof is not a valid ISO8601 timestamp: {text!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"decision_asof must be timezone-aware (offset-included), got naive value {text!r}")
    return parsed


def _normalize_side(side: str) -> str:
    if side not in _SIDE_NORMALIZE:
        raise ValueError(f"side must be one of {tuple(_SIDE_NORMALIZE)}, got {side!r}")
    return _SIDE_NORMALIZE[side]


def _canonical_json(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def compute_merge_hash(*, account_lane: str, session_date: str, symbol: str, side: str,
                        execution_owner_strategy_id: str, entry: float, stop: float,
                        target: Optional[float]) -> str:
    """Resolver固有の決定論的キー。C-047/C-048の`intent_hash`とは別名・別定義
    （このファイルでは絶対に`intent_hash`という名前を使わない）。
    scenario_idやUUIDのような非決定値は対象に含めない。同じ状況（同じ口座
    レーン・同じ意思決定日・同じ銘柄/方向・同じowner戦略・同じ発動条件）なら
    何度計算しても同じ値になる。
    """
    payload = {
        "account_lane": account_lane,
        "session_date": session_date,
        "symbol": symbol,
        "side": side,
        "execution_owner_strategy_id": execution_owner_strategy_id,
        "entry": float(entry),
        "stop": float(stop),
        "target": None if target is None else float(target),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _owner_sort_key(signal: dict, execution_priority: list[str]):
    ts = _parse_aware_timestamp(signal["decision_asof"])
    strategy_id = signal["strategy_id"]
    try:
        priority_rank = execution_priority.index(strategy_id)
    except ValueError:
        # config/conflict_policy_v0_1.jsonにまだ載っていない戦略は最低優先度
        # 扱いにする（無登録を「最優先」に誤って解釈させない）。
        priority_rank = len(execution_priority)
    return (ts, priority_rank, strategy_id)


def resolve_conflicts(signals: list[dict], open_positions: list[dict], policy: dict,
                       known_merge_hashes: Optional[set] = None) -> list[dict]:
    """Conflict Resolverの中核となる純粋関数。symbolごとに1件のResolvedScenarioを
    返す。同一入力（順序違いを含む）からは常に同一の結果になる。

    signals: scripts/signal_contract.build_signal()が出力する形の辞書のリスト。
        少なくとも code/side/strategy_id/decision_asof/source_quality/entry/
        stop/target/snapshot_id を持つことを期待する。
    open_positions: 現在OPEN中のphysical position（symbol/side[BUY|SELL]/
        execution_owner_strategy_id/entry/stop/targetを持つ辞書のリスト）。
        まだExecution Ledgerが無いため呼び出し側が別途管理する前提で、
        このPhaseでは単純な入力として受け取るだけ。
    policy: load_policy()が返す辞書（policy_version/account_lane/
        max_open_positions/execution_priority）。
    known_merge_hashes: 既知のmerge_hash集合（渡された場合のみ重複判定に使う）。
    """
    known_merge_hashes = known_merge_hashes or set()
    generated_at = now_jst().isoformat()
    execution_priority = list(policy.get("execution_priority") or [])
    account_lane = policy["account_lane"]

    by_symbol: dict[str, list[dict]] = {}
    for signal in signals:
        by_symbol.setdefault(signal["code"], []).append(signal)

    open_by_symbol: dict[str, dict[str, dict]] = {}
    for pos in open_positions:
        open_by_symbol.setdefault(pos["symbol"], {})[pos["side"]] = pos

    scenarios = []
    owner_ts_by_symbol: dict[str, datetime] = {}
    # 銘柄名でソートしてから処理することで、入力signalsの並び順に関わらず
    # 出力リストの並び順自体も決定論的にする（Golden #7/#16）。
    for symbol in sorted(by_symbol):
        symbol_signals = by_symbol[symbol]
        research_signal_ids = [s["snapshot_id"] for s in symbol_signals]

        eligible = [s for s in symbol_signals if s.get("side") in ("LONG", "SHORT")
                    and s.get("source_quality") == "ok"]
        long_eligible = [s for s in eligible if s["side"] == "LONG"]
        short_eligible = [s for s in eligible if s["side"] == "SHORT"]
        open_sides = set(open_by_symbol.get(symbol, {}))

        base = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": policy["policy_version"],
            "generated_at": generated_at,
            "symbol": symbol,
            "side": None,
            "resolved_status": None,
            "execution_owner_strategy_id": None,
            "confirming_strategy_ids": [],
            "research_signal_ids": research_signal_ids,
            "entry": None,
            "stop": None,
            "target": None,
            "block_reasons": [],
            "merge_hash": None,
            # Golden #12/#15: 入力signalが real_submit_allowed=True を運んで
            # いても一切読み取らず、常にFalseで出力する。
            "real_submit_allowed": False,
        }

        opposite_conflict = (
            (bool(long_eligible) and bool(short_eligible))
            or (bool(long_eligible) and "SELL" in open_sides)
            or (bool(short_eligible) and "BUY" in open_sides)
        )
        if opposite_conflict:
            scenarios.append({
                **base,
                "resolved_status": "CONFLICT_BLOCKED_OPPOSITE_SIDE",
                "block_reasons": ["CONFLICT_BLOCKED_OPPOSITE_SIDE"],
            })
            continue

        if not long_eligible and not short_eligible:
            scenarios.append({
                **base,
                "resolved_status": "BLOCKED_DATA_QUALITY",
                "block_reasons": ["NO_ELIGIBLE_OK_QUALITY_SIGNAL"],
            })
            continue

        side_signals = long_eligible or short_eligible
        side = _normalize_side(side_signals[0]["side"])
        existing_open = open_by_symbol.get(symbol, {}).get(side)

        if existing_open is not None:
            owner_strategy_id = (existing_open.get("execution_owner_strategy_id")
                                  or existing_open.get("strategy_id"))
            entry, stop, target = existing_open["entry"], existing_open["stop"], existing_open.get("target")
            confirming = sorted({s["strategy_id"] for s in side_signals} - {owner_strategy_id})
            status = "MERGED_CONFIRMATION"
        else:
            owner = min(side_signals, key=lambda s: _owner_sort_key(s, execution_priority))
            owner_strategy_id = owner["strategy_id"]
            entry, stop, target = owner["entry"], owner["stop"], owner.get("target")
            confirming = sorted({s["strategy_id"] for s in side_signals} - {owner_strategy_id})
            status = "CANDIDATE_READY"
            owner_ts_by_symbol[symbol] = _parse_aware_timestamp(owner["decision_asof"])

        session_date = _parse_aware_timestamp(side_signals[0]["decision_asof"]).astimezone(JST).strftime("%Y-%m-%d")
        merge_hash = compute_merge_hash(
            account_lane=account_lane, session_date=session_date, symbol=symbol, side=side,
            execution_owner_strategy_id=owner_strategy_id, entry=entry, stop=stop, target=target,
        )
        if status == "CANDIDATE_READY" and merge_hash in known_merge_hashes:
            status = "BLOCKED_DUPLICATE_ORDER"

        scenarios.append({
            **base,
            "side": side,
            "resolved_status": status,
            "execution_owner_strategy_id": owner_strategy_id,
            "confirming_strategy_ids": confirming,
            "entry": entry,
            "stop": stop,
            "target": target,
            "merge_hash": merge_hash,
            "block_reasons": [] if status != "BLOCKED_DUPLICATE_ORDER" else ["BLOCKED_DUPLICATE_ORDER"],
        })

    _apply_max_open_positions(scenarios, open_positions, policy, execution_priority, owner_ts_by_symbol)
    return scenarios


def _apply_max_open_positions(scenarios: list[dict], open_positions: list[dict], policy: dict,
                               execution_priority: list[str], owner_ts_by_symbol: dict[str, datetime]) -> None:
    """口座レベルのmax_open_positions上限を、symbol横断でCANDIDATE_READYの
    候補に対して適用する（in-place）。上限を超えた分はBLOCKED_MAX_OPEN_
    POSITIONSへ差し替える。優先順位はowner決定と同じ規則（owner signalの
    decision_asofが早い→execution_priority→symbol名）で決定論的に並べる
    （generated_atはこの呼び出し内で全scenario共通のため、ランキングには
    使わない——タイになって非決定的にならないようowner側の実時刻を使う）。
    """
    max_open = policy.get("max_open_positions")
    if max_open is None:
        return
    remaining = max_open - len(open_positions)
    ready = [s for s in scenarios if s["resolved_status"] == "CANDIDATE_READY"]
    if remaining >= len(ready):
        return
    remaining = max(remaining, 0)

    def rank(scenario: dict):
        try:
            priority_rank = execution_priority.index(scenario["execution_owner_strategy_id"])
        except ValueError:
            priority_rank = len(execution_priority)
        return (owner_ts_by_symbol[scenario["symbol"]], priority_rank, scenario["symbol"])

    ready_sorted = sorted(ready, key=rank)
    keep = set(id(s) for s in ready_sorted[:remaining])
    for scenario in ready:
        if id(scenario) not in keep:
            scenario["resolved_status"] = "BLOCKED_MAX_OPEN_POSITIONS"
            scenario["block_reasons"] = ["BLOCKED_MAX_OPEN_POSITIONS"]


def is_duplicate_scenario(candidate: dict, known: list[dict]) -> bool:
    """merge_hashの完全一致だけで重複判定する純粋関数（execution_contract.
    is_duplicate_intent()と同じ設計だが、対象はmerge_hashでintent_hashではない）。"""
    candidate_hash = candidate.get("merge_hash")
    if candidate_hash is None:
        return False
    return any(k.get("merge_hash") == candidate_hash for k in known)
