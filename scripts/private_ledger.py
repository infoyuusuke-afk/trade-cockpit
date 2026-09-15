"""scripts/private_ledger.py

非公開売買ログ（docs/C-031-GPT_STRATEGY_ROADMAP.md 第5節「非公開ledger」・P1「非公開売買ログ・反省会」への対応）。

このモジュールが扱うのは本人の**実約定**（証券会社での実際の売買）であり、
paper_trade_history.json の紙トレード（仮想約定）とは完全に別台帳にする
（第1節「実現損益は…紙トレード・予測・含み損益とは別台帳にする」）。

## 公開境界（重要・CLAUDE.md準拠）
このリポジトリ（trade-cockpit）はGitHub Pagesで公開される公開repoである。
ロードマップ第5節は「非公開ledgerを公開repoへ置かない」ことを明示要件にしており、
CLAUDE.mdも「個人の保有・注文情報を公開repoへ出さない」ことを禁止事項として定めている。
そのためこのモジュールが読み書きするファイルは data/private/ 配下に置き、
.gitignore で追跡除外している。GitHub Actions（クラウド）側のワークフローには
一切組み込まない・呼び出さない。実行はユーザー本人のPC上でのみ想定する。

## ワンタップ発注は未実装
発注実装は未着手（現状はサイン生成＋人のワンタップ確定が既定の発注範囲）。
そのため実約定の記録は、本人が証券会社の約定明細を見ながら手入力する運用を前提にする。
"""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "data" / "private"
LEDGER_PATH = LEDGER_DIR / "trade_ledger.jsonl"

# 第5節: 非公開ledgerのフィールド定義
REQUIRED_FIELDS = (
    "trade_id", "ticker", "name", "side", "executed_at",
    "price", "quantity", "fee", "horizon", "strategy_version", "source",
)
OPTIONAL_FIELDS = (
    "order_id", "execution_id", "position_id",
    "decision_snapshot_id", "regime", "entry_reason", "exit_reason",
    "rule_violation", "reconciliation_status",
)
VALID_SIDES = ("BUY", "SELL")
RECONCILIATION_STATUSES = ("未照合", "照合済み", "実績未取得")


def now_jst() -> datetime:
    return datetime.now(JST)


def new_trade_id(executed_at: Optional[datetime] = None) -> str:
    stamp = (executed_at or now_jst()).strftime("%Y%m%dT%H%M%S")
    return f"T-{stamp}-{uuid.uuid4().hex[:6]}"


def validate_entry(entry: dict) -> list[str]:
    """必須フィールドの欠落・型の明白な誤りを検出する（純粋関数、テスト対象）。
    戻り値は問題点のリスト（空なら妥当）。ここでは例外を投げない。
    """
    problems = []
    for field in REQUIRED_FIELDS:
        if entry.get(field) in (None, ""):
            problems.append(f"missing_{field}")
    side = entry.get("side")
    if side is not None and side not in VALID_SIDES:
        problems.append(f"invalid_side:{side}")
    for numeric_field in ("price", "quantity", "fee"):
        value = entry.get(numeric_field)
        if value is not None:
            try:
                float(value)
            except (TypeError, ValueError):
                problems.append(f"non_numeric_{numeric_field}")
    return problems


def normalize_entry(entry: dict) -> dict:
    """デフォルト値を補い、フィールド順を固定した辞書を返す（純粋関数）。
    trade_idが無ければ発番する。reconciliation_statusの未指定は「未照合」。
    """
    entry = dict(entry)
    entry.setdefault("trade_id", new_trade_id())
    for field in OPTIONAL_FIELDS:
        entry.setdefault(field, None)
    if entry.get("reconciliation_status") is None:
        entry["reconciliation_status"] = "未照合"
    if entry.get("rule_violation") is None:
        entry["rule_violation"] = []
    ordered = {}
    for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        ordered[field] = entry.get(field)
    ordered["recorded_at"] = entry.get("recorded_at") or now_jst().isoformat()
    return ordered


def append_entry(entry: dict, path: Path = LEDGER_PATH) -> dict:
    """1件の実約定を非公開台帳に追記する。妥当性チェックに失敗したらValueError。
    追記のみで既存行は書き換えない（signal_contract.record_snapshotと同じ方針）。
    """
    problems = validate_entry(entry)
    if problems:
        raise ValueError(f"invalid ledger entry: {problems}")
    record = normalize_entry(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def load_entries(path: Path = LEDGER_PATH, day: Optional[str] = None) -> list[dict]:
    """台帳を読み出す。day="YYYY-MM-DD"を渡すとexecuted_atがその日のものだけに絞る。
    ファイルが無い（＝実績未取得）場合は空リストを返す（例外にしない）。
    """
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if day is not None:
            executed_at = record.get("executed_at") or ""
            if not executed_at.startswith(day):
                continue
        records.append(record)
    return records


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="非公開の実約定を1件、ローカル台帳(data/private/trade_ledger.jsonl)に追記する。"
                     "このファイルはgit追跡されない。"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="実約定を1件追加")
    add.add_argument("--ticker", required=True)
    add.add_argument("--name", required=True)
    add.add_argument("--side", required=True, choices=VALID_SIDES)
    add.add_argument("--price", required=True, type=float)
    add.add_argument("--quantity", required=True, type=float)
    add.add_argument("--fee", required=True, type=float)
    add.add_argument("--executed-at", required=True, help='例: "2026-09-15 09:05:00"')
    add.add_argument("--horizon", required=True, choices=("day", "swing", "long"))
    add.add_argument("--strategy-version", required=True)
    add.add_argument("--source", required=True, help="例: 楽天証券手入力")
    add.add_argument("--position-id", default=None, help="同一ポジションの複数約定をまとめるID")
    add.add_argument("--order-id", default=None)
    add.add_argument("--execution-id", default=None)
    add.add_argument("--decision-snapshot-id", default=None)
    add.add_argument("--regime", default=None)
    add.add_argument("--entry-reason", default=None)
    add.add_argument("--exit-reason", default=None)
    add.add_argument("--rule-violation", default=None, action="append",
                      help="ルール逸脱の記述。複数回指定可")

    show = sub.add_parser("show", help="台帳の内容を表示（デバッグ用）")
    show.add_argument("--day", default=None, help="YYYY-MM-DDで絞り込み")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_arg_parser().parse_args(argv)
    if args.command == "add":
        entry = {
            "ticker": args.ticker,
            "name": args.name,
            "side": args.side,
            "price": args.price,
            "quantity": args.quantity,
            "fee": args.fee,
            "executed_at": args.executed_at,
            "horizon": args.horizon,
            "strategy_version": args.strategy_version,
            "source": args.source,
            "position_id": args.position_id,
            "order_id": args.order_id,
            "execution_id": args.execution_id,
            "decision_snapshot_id": args.decision_snapshot_id,
            "regime": args.regime,
            "entry_reason": args.entry_reason,
            "exit_reason": args.exit_reason,
            "rule_violation": args.rule_violation or [],
        }
        record = append_entry(entry)
        print(f"記録しました: {record['trade_id']} ({LEDGER_PATH})")
    elif args.command == "show":
        records = load_entries(day=args.day)
        if not records:
            print("実績未取得（該当する約定なし）")
        for r in records:
            print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
