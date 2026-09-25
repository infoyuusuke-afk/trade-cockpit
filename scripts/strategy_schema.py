"""scripts/strategy_schema.py

統一検証スキーマ（GitHub Issue #18「C-045-GPT: 現行サイトレビューと次フェーズ提案」の
優先順位1「新統計スキーマ＋strategy_id/version」への対応）。

これまでpaper_trade_history.jsonは、どの選定ロジック（build_day_ifo_candidates由来か
day_rankフォールバックか、LONGかSHORTか）が生んだ候補なのかを区別せずに1本の配列へ
記録していた（reliability_report.pyはside別にしか集計できない）。ここでは各レコードへ
strategy_id/strategy_version/horizon/symbol_class/liquidity_bucket/regime等を追記する
純粋関数を提供し、strategy_id別・銘柄プロファイル別・地合い別の集計を将来可能にする。

## 設計方針
- 既存フィールドは一切変更・削除しない（追記のみ）。旧データへの遡及的な推定補完は
  行わない（呼び出し側がまだこのモジュールを使っていない過去レコードにはこれらの
  キー自体が存在しない状態のままにする）。
- 地合い（regime）は独自に判定し直さず、既存のscripts/regime_policy.pyが書き出す
  market_regime.jsonのconfirmed_regime（UP/DOWN/RANGE/UNKNOWN/EVENT_LOCK）を
  そのまま読む（Issueが要求するUP/DOWN/RANGE語彙と完全一致する既存実装の再利用）。

## 正直な制約
- symbol_classはIssueが要求する6分類（HIGH_VOL_HIGH_TURNOVER/LARGE_VALUE/
  LARGE_GROWTH_SEMI/SMALL_GROWTH/SPECULATIVE_THEME/TOB_EVENT）のうち、現在の
  パイプラインで確認可能なatr_pct・turnoverだけから判定できるHIGH_VOL_HIGH_TURNOVER
  のみ実装している。残り5分類は時価総額・グロース/バリュー区分・材料情報が必要で、
  investor_regime.pyのstock_feature_schemaが既に「未接続」と明記している項目と同じ
  制約を持つため、推測せずUNCLASSIFIEDとする。
- fees/slippageはまだ手数料モデルを持たないため0固定（既存のpnl計算も暗黙に
  手数料ゼロを前提にしている——この関数は新しい前提を作らず、既存の前提を
  スキーマ上に明示しているだけ）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
MARKET_REGIME_PATH = ROOT / "market_regime.json"

SCHEMA_VERSION = "signal-schema-1.0"

# 既存の候補生成元ごとに安定したstrategy_id/versionを割り当てる。
# ここに無いstrategy_idを渡すとversion/horizonは"unknown"になる（サイレントに
# 別の戦略として扱わない）。
STRATEGY_REGISTRY = {
    "day_ifo_long": {
        "version": "1.0", "horizon": "day", "side_hint": "LONG",
        "description": "build_day_ifo_candidates()のテーマ配分IFO選定（scripts/update.py）",
        "cockpit_tab": "ms2-live",
    },
    "day_rank_long": {
        "version": "1.0", "horizon": "day", "side_hint": "LONG",
        "description": "day_rank（material_lifecycle由来のday_score順位）フォールバック選定（scripts/update.py）",
        "cockpit_tab": "ms2-live",
    },
    "day_short_mvp": {
        "version": "1.0", "horizon": "day", "side_hint": "SHORT",
        "description": "scripts/short_candidates.pyのSHORT MVP選定",
        "cockpit_tab": "ms2-live",
    },
}


def classify_liquidity_bucket(turnover: Optional[float]) -> str:
    """売買代金（円）から流動性バケットを判定する純粋関数。
    しきい値はscripts/update.pyの既存スコアリングが使っている水準（10億/30億/5億円）を踏襲。
    """
    if turnover is None:
        return "UNKNOWN"
    turnover = float(turnover)
    if turnover >= 10_000_000_000:
        return "ULTRA_LIQUID"
    if turnover >= 3_000_000_000:
        return "HIGH_LIQUID"
    if turnover >= 500_000_000:
        return "MID_LIQUID"
    return "LOW_LIQUID"


def classify_symbol_class(*, turnover: Optional[float] = None, atr_pct: Optional[float] = None) -> str:
    """銘柄プロファイルの暫定分類（純粋関数）。モジュールdocstringの「正直な制約」参照。"""
    if turnover is not None and atr_pct is not None and turnover >= 3_000_000_000 and atr_pct >= 3.0:
        return "HIGH_VOL_HIGH_TURNOVER"
    return "UNCLASSIFIED"


def current_regime(path: Path = MARKET_REGIME_PATH) -> dict:
    """market_regime.json（regime_policy.py出力）からregime関連フィールドを読む。
    ファイルが無い/壊れている場合は全てNoneで返す（推測しない）。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"regime": None, "regime_updated_at": None, "high_vol": None,
                "rate_shock": None, "policy_event": None}
    flags = data.get("flags") or {}
    return {
        "regime": data.get("confirmed_regime"),
        "regime_updated_at": data.get("confirmed_at"),
        "high_vol": flags.get("high_vol"),
        "rate_shock": flags.get("rate_shock"),
        "policy_event": flags.get("policy_event"),
    }


def exit_reason_code(result: str) -> str:
    """既存のresult文字列（日本語の表示用テキスト）から、集計しやすい正規化コードへ写す
    純粋関数。resultは削除せず併記する。"""
    return {
        "未発動（見送り）": "NOT_TRIGGERED",
        "順序不明（成績除外）": "AMBIGUOUS_EXCLUDED",
        "IFO損切り": "STOP",
        "IFO利確1": "TARGET1",
        "時点評価・未決済": "OPEN_MARK",
    }.get(result, "UNKNOWN")


def tag_record(record: dict, *, strategy_id: str, signal_time: str,
                turnover: Optional[float] = None, atr_pct: Optional[float] = None,
                regime_snapshot: Optional[dict] = None, source: str = "") -> dict:
    """既存のtrade/signalレコードへ新スキーマのフィールドを追記した新しいdictを返す
    （既存フィールドは一切変更・削除しない、純粋関数）。"""
    meta = STRATEGY_REGISTRY.get(strategy_id, {})
    regime_snapshot = regime_snapshot if regime_snapshot is not None else current_regime()
    return {
        **record,
        "schema_version": SCHEMA_VERSION,
        "strategy_id": strategy_id,
        "strategy_version": meta.get("version", "unknown"),
        "horizon": meta.get("horizon", "unknown"),
        "cockpit_tab": meta.get("cockpit_tab"),
        "liquidity_bucket": classify_liquidity_bucket(turnover),
        "symbol_class": classify_symbol_class(turnover=turnover, atr_pct=atr_pct),
        "regime": regime_snapshot.get("regime"),
        "regime_updated_at": regime_snapshot.get("regime_updated_at"),
        "high_vol": regime_snapshot.get("high_vol"),
        "signal_time": signal_time,
        "source": source or strategy_id,
    }
