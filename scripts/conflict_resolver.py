"""scripts/conflict_resolver.py

Conflict Resolver / Position Merge（GitHub Issue #18 Execution Stack Phase 2、
comment 5702288572の基本設計 + C-048-GPT comment 5702907356の上書き解釈 +
C-048R-GPT comment 5703181981のPhase 2.1 hardening＝3 blocker修正）。

同一symbolで複数戦略が同時・近接発火した場合に、①各戦略の研究上の成績を
壊さず、②現実の口座では1つのphysical positionだけを安全に管理する、という
2つの要求を両立させるための純粋関数レイヤー。scripts/signal_contract.pyの
Signalを受け取り、scripts/execution_contract.pyのExecution Intentを作る前段
として使う（signal_contract → conflict_resolver → execution_contract → Shadow/
Risk Gate、という接続。後段のPhase 3 Risk Gate・Phase 4 Permission Gateは
このコミットでは一切実装しない）。

このファイルも発注・broker/RSS呼び出し・Excel注文式・実ポジション変更は
一切行わない（scripts/execution_contract.pyと同じ境界）。

## C-048-GPTによる上書き解釈
- `intent_hash`という名前は scripts/execution_contract.py の11フィールド
  SHA256だけがcanonicalに使う。このファイルは同名のhashを絶対に作らない。
  Resolver固有の決定論的キーは`merge_hash`という別名にする。
- 許可フィールド名は`real_submit_allowed`のみ（旧設計案にあった
  `real_order_allowed`は使わない）。このResolverは常にFalseで出力し、
  入力信号に`real_submit_allowed=True`が紛れ込んでいても一切信用しない
  （そもそも読み取らない）。
- signal側の LONG/SHORT は研究語彙として保持してよいが、Execution境界の
  出力では明示的に LONG→BUY・SHORT→SELL へ正規化する。

## C-048R-GPTによるPhase 2.1 hardening（3 blocker）
1. `merge_hash`へ`owner_decision_asof`を必須で含める。同一signalの再読込
   （decision_asof同一）は同じmerge_hashのまま、EXIT後の次completed bar
   での正当な再Entry（同じgeometry/strategyでもdecision_asofが違う）は
   別のmerge_hashになるようにする——decision_asofを含めなければ、正当な
   再Entryが過去のmerge_hashと衝突しBLOCKED_DUPLICATE_ORDERへ誤判定
   されてしまう。
2. `session_date`は必ずowner側のdecision_asof（新規はowner signal、
   confirmationは既存positionのowner_decision_asof）から算出する。また
   同一resolve対象のsignal群に複数のJST session_dateが混在していたら
   黙ってmergeせず`BLOCKED_SESSION_MISMATCH`にする。
3. same-side mergeの対象を`symbol + side + horizon`に限定する。DAYTRADE
   とSWINGのように保有期間・exit条件が異なるhorizonの信号は、同じ方向
   でも別々のscenarioとして扱い、confirming_strategy_idsへ混ぜない。
   Researchは両方独立して残るが、real physical候補はmax_open_positions
   の口座レベル上限で横断的に絞り込む（1銘柄内の複数horizonが同時に
   real候補になっても、その上限適用でどちらか一方だけがCANDIDATE_READY
   に残り、他はBLOCKED_MAX_OPEN_POSITIONSになる）。

## このPhase 2.1が決めないこと（正直な制約）
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
SCHEMA_VERSION = "conflict-resolver-1.1"
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
    "BLOCKED_SESSION_MISMATCH",
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
                        execution_owner_strategy_id: str, owner_decision_asof: str,
                        entry: float, stop: float, target: Optional[float]) -> str:
    """Resolver固有の決定論的キー。C-047/C-048の`intent_hash`とは別名・別定義
    （このファイルでは絶対に`intent_hash`という名前を使わない）。
    scenario_idやUUIDのような非決定値は対象に含めない。

    C-048R-GPT Blocker 1: owner_decision_asofを必須で含める。同一signalの
    再読込（decision_asof同一）は同じhashのまま、EXIT後の次completed bar
    での正当な再Entry（decision_asofが違う）は別hashになる——これが無いと
    同じgeometry/strategyの正当な再Entryが過去のhashと衝突し、duplicate
    として誤ってblockされてしまう。
    """
    payload = {
        "account_lane": account_lane,
        "session_date": session_date,
        "symbol": symbol,
        "side": side,
        "execution_owner_strategy_id": execution_owner_strategy_id,
        "owner_decision_asof": owner_decision_asof,
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


def _session_date_of(dt: datetime) -> str:
    return dt.astimezone(JST).strftime("%Y-%m-%d")


def _blocked_scenario(base: dict, status: str, reason: str) -> dict:
    return {**base, "resolved_status": status, "block_reasons": [reason]}


def resolve_conflicts(signals: list[dict], open_positions: list[dict], policy: dict,
                       known_merge_hashes: Optional[set] = None) -> list[dict]:
    """Conflict Resolverの中核となる純粋関数。symbol×horizonごとに1件の
    ResolvedScenarioを返す（同一symbolでも異なるhorizonは別scenario。
    C-048R-GPT Blocker 3）。同一入力（順序違いを含む）からは常に同一の
    結果になる。

    signals: scripts/signal_contract.build_signal()が出力する形の辞書のリスト。
        少なくとも code/side/strategy_id/decision_asof/source_quality/entry/
        stop/target/snapshot_id/horizon を持つことを期待する。
    open_positions: 現在OPEN中のphysical position（symbol/side[BUY|SELL]/
        horizon/execution_owner_strategy_id/owner_decision_asof/entry/stop/
        targetを持つ辞書のリスト）。まだExecution Ledgerが無いため呼び出し
        側が別途管理する前提で、このPhaseでは単純な入力として受け取るだけ。
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

    open_by_key: dict[tuple, dict] = {}
    open_sides_by_symbol: dict[str, set] = {}
    for pos in open_positions:
        open_by_key[(pos["symbol"], pos["side"], pos["horizon"])] = pos
        open_sides_by_symbol.setdefault(pos["symbol"], set()).add(pos["side"])

    scenarios = []
    owner_ts_by_key: dict[tuple, datetime] = {}  # key = (symbol, horizon)

    # 銘柄名でソートしてから処理することで、入力signalsの並び順に関わらず
    # 出力リストの並び順自体も決定論的にする（Golden #7/#16/#21）。
    for symbol in sorted(by_symbol):
        symbol_signals = by_symbol[symbol]
        symbol_research_ids = sorted(s["snapshot_id"] for s in symbol_signals)

        symbol_base = {
            "schema_version": SCHEMA_VERSION,
            "policy_version": policy["policy_version"],
            "generated_at": generated_at,
            "symbol": symbol,
            "side": None,
            "horizon": None,
            "resolved_status": None,
            "execution_owner_strategy_id": None,
            "confirming_strategy_ids": [],
            "research_signal_ids": symbol_research_ids,
            "entry": None,
            "stop": None,
            "target": None,
            "block_reasons": [],
            "merge_hash": None,
            # Golden #12/#15: 入力signalが real_submit_allowed=True を運んで
            # いても一切読み取らず、常にFalseで出力する。
            "real_submit_allowed": False,
        }

        eligible = [s for s in symbol_signals if s.get("side") in ("LONG", "SHORT")
                    and s.get("source_quality") == "ok"]
        long_eligible = [s for s in eligible if s["side"] == "LONG"]
        short_eligible = [s for s in eligible if s["side"] == "SHORT"]
        open_sides = open_sides_by_symbol.get(symbol, set())

        # opposite-side競合はhorizonをまたいでsymbol単位で見る（実口座の
        # physical positionはhorizonを問わず銘柄単位で1つしか持てないため）。
        opposite_conflict = (
            (bool(long_eligible) and bool(short_eligible))
            or (bool(long_eligible) and "SELL" in open_sides)
            or (bool(short_eligible) and "BUY" in open_sides)
        )
        if opposite_conflict:
            scenarios.append(_blocked_scenario(symbol_base, "CONFLICT_BLOCKED_OPPOSITE_SIDE",
                                                "CONFLICT_BLOCKED_OPPOSITE_SIDE"))
            continue

        if not long_eligible and not short_eligible:
            scenarios.append(_blocked_scenario(symbol_base, "BLOCKED_DATA_QUALITY",
                                                "NO_ELIGIBLE_OK_QUALITY_SIGNAL"))
            continue

        side_signals_all = long_eligible or short_eligible
        side = _normalize_side(side_signals_all[0]["side"])

        # C-048R-GPT Blocker 3: same-side mergeはsymbol+side+horizonに限定する。
        by_horizon: dict[str, list[dict]] = {}
        for s in side_signals_all:
            by_horizon.setdefault(s.get("horizon"), []).append(s)

        for horizon in sorted(by_horizon, key=lambda h: (h is None, h or "")):
            horizon_signals = by_horizon[horizon]
            base = {
                **symbol_base,
                "side": side,
                "horizon": horizon,
                "research_signal_ids": sorted(s["snapshot_id"] for s in horizon_signals),
            }

            # C-048R-GPT Blocker 2: 混在session_dateを黙ってmergeしない。
            session_dates = {_session_date_of(_parse_aware_timestamp(s["decision_asof"]))
                              for s in horizon_signals}
            if len(session_dates) > 1:
                scenarios.append(_blocked_scenario(base, "BLOCKED_SESSION_MISMATCH",
                                                    "SESSION_DATE_MISMATCH"))
                continue

            existing_open = open_by_key.get((symbol, side, horizon))
            if existing_open is not None:
                owner_strategy_id = (existing_open.get("execution_owner_strategy_id")
                                      or existing_open.get("strategy_id"))
                entry, stop, target = existing_open["entry"], existing_open["stop"], existing_open.get("target")
                owner_decision_asof_text = existing_open["owner_decision_asof"]
                confirming = sorted({s["strategy_id"] for s in horizon_signals} - {owner_strategy_id})
                status = "MERGED_CONFIRMATION"
            else:
                owner = min(horizon_signals, key=lambda s: _owner_sort_key(s, execution_priority))
                owner_strategy_id = owner["strategy_id"]
                entry, stop, target = owner["entry"], owner["stop"], owner.get("target")
                owner_decision_asof_text = owner["decision_asof"]
                confirming = sorted({s["strategy_id"] for s in horizon_signals} - {owner_strategy_id})
                status = "CANDIDATE_READY"

            owner_decision_asof = _parse_aware_timestamp(owner_decision_asof_text)
            if status == "CANDIDATE_READY":
                owner_ts_by_key[(symbol, horizon)] = owner_decision_asof
            session_date = _session_date_of(owner_decision_asof)

            merge_hash = compute_merge_hash(
                account_lane=account_lane, session_date=session_date, symbol=symbol, side=side,
                execution_owner_strategy_id=owner_strategy_id,
                owner_decision_asof=owner_decision_asof.isoformat(),
                entry=entry, stop=stop, target=target,
            )
            if status == "CANDIDATE_READY" and merge_hash in known_merge_hashes:
                status = "BLOCKED_DUPLICATE_ORDER"

            scenarios.append({
                **base,
                "resolved_status": status,
                "execution_owner_strategy_id": owner_strategy_id,
                "confirming_strategy_ids": confirming,
                "entry": entry,
                "stop": stop,
                "target": target,
                "merge_hash": merge_hash,
                "block_reasons": [] if status != "BLOCKED_DUPLICATE_ORDER" else ["BLOCKED_DUPLICATE_ORDER"],
            })

    _apply_max_open_positions(scenarios, open_positions, policy, execution_priority, owner_ts_by_key)
    return scenarios


def _apply_max_open_positions(scenarios: list[dict], open_positions: list[dict], policy: dict,
                               execution_priority: list[str],
                               owner_ts_by_key: dict[tuple, datetime]) -> None:
    """口座レベルのmax_open_positions上限を、symbol×horizon横断でCANDIDATE_READY
    の候補に対して適用する（in-place）。上限を超えた分はBLOCKED_MAX_OPEN_
    POSITIONSへ差し替える（C-048R-GPT Blocker 3: 同一銘柄の複数horizonが
    同時にCANDIDATE_READYになった場合も、この上限適用で最終的に1件だけが
    real候補として残る）。優先順位はowner決定と同じ規則（owner signalの
    decision_asofが早い→execution_priority→symbol名→horizon名）で決定論的
    に並べる（generated_atはこの呼び出し内で全scenario共通のため、
    ランキングには使わない）。
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
        key = (scenario["symbol"], scenario["horizon"])
        return (owner_ts_by_key[key], priority_rank, scenario["symbol"], scenario["horizon"] or "")

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
