"""scripts/signal_contract.py

共通シグナル契約（docs/C-031-GPT_STRATEGY_ROADMAP.md のP0「共通期待値契約」への対応）。

今後実装する地合い判定・決算判定・期待値計算などのシグナル生成スクリプトが共通で使う
「出力の型」「データ鮮度によるNO TRADEゲート」「意思決定の時点固定ログ」を提供する。
個別の戦略ロジック（地合い判定式・決算判定式・期待値の統計処理そのもの）はここに含めない。

設計はC-031-GPT_STRATEGY_ROADMAP.mdの第3節（入力契約）・第7節（共通出力スキーマ・受入基準）に
準拠する。受入基準#1（古いデータはWAIT・ゼロ補完しない）・#2（未来情報漏洩の検知）・
#8（同一入力なら同じ判定）を満たすことを目標にする。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "signal-contract-1.0"

VALID_SIDES = ("LONG", "SHORT", "WAIT")
VALID_QUALITY = ("ok", "stale", "missing", "future")


def now_jst() -> datetime:
    return datetime.now(JST)


@dataclass
class DataPoint:
    """1件の観測値。value/source_url/published_at/fetched_at/available_at/qualityを持つ。
    C-031-GPT第3節: available_at = max(published_at, fetched_at) <= decision_asof の
    観測だけを意思決定に使ってよい。"""
    value: Any
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None

    def __post_init__(self):
        if self.fetched_at is None:
            self.fetched_at = now_jst()

    @property
    def available_at(self) -> Optional[datetime]:
        candidates = [t for t in (self.published_at, self.fetched_at) if t is not None]
        return max(candidates) if candidates else None


def check_freshness(point: Optional[DataPoint], ttl_seconds: float, decision_asof: datetime) -> str:
    """observed値がdecision_asof時点で利用可能・鮮度内かを判定する。
    戻り値: "ok" | "stale" | "missing" | "future"（future=未来情報漏洩の疑い、受入基準#2）。
    """
    if point is None or point.value is None:
        return "missing"
    available_at = point.available_at
    if available_at is None:
        return "missing"
    if available_at > decision_asof:
        return "future"
    age = (decision_asof - available_at).total_seconds()
    if age > ttl_seconds:
        return "stale"
    return "ok"


def gate_no_trade(*freshness_results: str) -> tuple[bool, list[str]]:
    """いずれかの入力がok以外ならNO TRADE（WAIT）とする。
    受入基準#1: 古い価格・欠落OR・イベント取得失敗はWAITとし、EV・勝率をゼロ補完しない
    （呼び出し側は、この関数がFalseを返したらev_net_r等をnullのまま出力し、0で埋めないこと）。
    戻り値: (取引可否, ブロック理由のリスト)。
    """
    reasons = []
    for i, r in enumerate(freshness_results):
        if r not in VALID_QUALITY:
            raise ValueError(f"unknown freshness result: {r!r}")
        if r != "ok":
            reasons.append(f"input_{i}_{r}")
    return (len(reasons) == 0), reasons


def new_snapshot_id(decision_asof: Optional[datetime] = None) -> str:
    stamp = (decision_asof or now_jst()).strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def build_signal(
    *,
    horizon: str,
    code: str,
    side: str,
    strategy_id: str,
    decision_asof: datetime,
    source_quality: str,
    regime: Optional[str] = None,
    flags: Optional[list[str]] = None,
    ev_net_r: Optional[float] = None,
    ev_ci95: Optional[tuple[float, float]] = None,
    resolved_n: int = 0,
    eligibility: str = "insufficient_n",
    block_reasons: Optional[list[str]] = None,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    target: Optional[float] = None,
    expiry: Optional[str] = None,
    policy_version: str = "v1",
    snapshot_id: Optional[str] = None,
) -> dict:
    """C-031-GPT第7節の共通出力スキーマに沿ったシグナル辞書を組み立てる。
    trading_enabledはここでは受け付けない引数にしており、常にFalse固定で出力する
    （呼び出し側が誤ってTrueを渡しても反映されない。CLAUDE.mdの自動発注禁止方針に対応）。
    """
    if side not in VALID_SIDES:
        raise ValueError(f"side must be one of {VALID_SIDES}, got {side!r}")
    if side != "WAIT" and (entry is None or stop is None):
        raise ValueError("LONG/SHORT signals must include entry and stop")
    return {
        "schema_version": SCHEMA_VERSION,
        "policy_version": policy_version,
        "decision_asof": decision_asof.isoformat(),
        "snapshot_id": snapshot_id or new_snapshot_id(decision_asof),
        "source_quality": source_quality,
        "horizon": horizon,
        "code": code,
        "side": side,
        "strategy_id": strategy_id,
        "regime": regime,
        "flags": list(flags) if flags else [],
        "ev_net_r": ev_net_r,
        "ev_ci95": list(ev_ci95) if ev_ci95 else None,
        "resolved_n": resolved_n,
        "eligibility": eligibility,
        "block_reasons": list(block_reasons) if block_reasons else [],
        "entry": entry,
        "stop": stop,
        "target": target,
        "expiry": expiry,
        "trading_enabled": False,
    }


def record_snapshot(out_dir: Path, decision_asof: datetime, inputs: dict, signal: dict,
                     snapshot_id: Optional[str] = None) -> Path:
    """意思決定の時点固定ログ（P0「時点固定ログ」）。
    その意思決定が『その時点で本当に入手可能だったデータだけ』から作られたことを
    後から検証できるよう、1行1レコードのJSON Linesとして追記保存する
    （受入基準#2＝未来情報漏洩の検知、#8＝同一入力なら同じ判定、の検証に使う）。
    1日1ファイルにまとめ、ファイル自体は追記のみで過去行を書き換えない。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    day = decision_asof.astimezone(JST).strftime("%Y-%m-%d")
    path = out_dir / f"{day}.jsonl"
    record = {
        "snapshot_id": snapshot_id or signal.get("snapshot_id") or new_snapshot_id(decision_asof),
        "decision_asof": decision_asof.isoformat(),
        "inputs": inputs,
        "signal": signal,
        "recorded_at": now_jst().isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def read_snapshots(out_dir: Path, day: str) -> list[dict]:
    """record_snapshotで保存した1日分のログを読み出す（day="YYYY-MM-DD"）。"""
    path = out_dir / f"{day}.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records
