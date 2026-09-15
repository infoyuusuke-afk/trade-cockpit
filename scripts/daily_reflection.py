"""scripts/daily_reflection.py

日次反省会（docs/C-031-GPT_STRATEGY_ROADMAP.md 第6節 R1「非公開日記」・
P1「非公開売買ログ・反省会」への対応）。

scripts/private_ledger.py が記録した**実約定**だけを対象にする。紙トレード
（paper_trade_history.json）は対象にしない（別台帳の方針、第1節）。

## 公開境界
このモジュールが読み書きするのも data/private/ 配下のみで、公開repoには含めない
（scripts/private_ledger.py と同じ理由。詳細はそちらのdocstring参照）。

## 正直な制約（今回の実装範囲）
- 「見送り理由」の自動突合は行わない。signal_contract.record_snapshotによる
  時点固定ログが実運用でまだどのスクリプトからも呼ばれておらず、実データが
  存在しないため。見送り情報が必要な場合は、reflectionのskipped_notesに
  明示した上で「未接続」と表示する（捏造しない）。
- 「翌日の改善点」はGPT的な所感生成ではなく、本人がledgerに記録した
  rule_violation・entry_reason/exit_reasonの記入有無から機械的に導出する
  純粋関数（build_reflection）にしている。投資助言ではなく記録の完全性・
  規律の可視化が目的。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import private_ledger as pl

JST = timezone(timedelta(hours=9))
REFLECTIONS_DIR = pl.LEDGER_DIR / "reflections"


def pair_positions(entries: list[dict]) -> list[dict]:
    """position_idでBUY/SELLをまとめ、数量が相殺された（=決済済み）ポジションの
    実現損益を計算する純粋関数。position_id未記入の行は単独で"unmatched"にする。
    """
    by_position: dict[str, list[dict]] = {}
    unmatched: list[dict] = []
    for e in entries:
        pid = e.get("position_id")
        if not pid:
            unmatched.append(e)
            continue
        by_position.setdefault(pid, []).append(e)

    positions = []
    for pid, legs in by_position.items():
        legs = sorted(legs, key=lambda x: x.get("executed_at") or "")
        net_qty = 0.0
        cash_flow = 0.0
        for leg in legs:
            qty = float(leg["quantity"])
            price = float(leg["price"])
            fee = float(leg["fee"])
            if leg["side"] == "BUY":
                net_qty += qty
                cash_flow -= price * qty + fee
            else:
                net_qty -= qty
                cash_flow += price * qty - fee
        closed = abs(net_qty) < 1e-9
        positions.append({
            "position_id": pid,
            "ticker": legs[0].get("ticker"),
            "name": legs[0].get("name"),
            "legs": legs,
            "status": "決済済み" if closed else "保有中",
            "realized_pnl_yen": round(cash_flow) if closed else None,
            "opened_at": legs[0].get("executed_at"),
            "closed_at": legs[-1].get("executed_at") if closed else None,
        })
    for e in unmatched:
        positions.append({
            "position_id": None,
            "ticker": e.get("ticker"),
            "name": e.get("name"),
            "legs": [e],
            "status": "ペア不可（position_id未記入）",
            "realized_pnl_yen": None,
            "opened_at": e.get("executed_at"),
            "closed_at": None,
        })
    return positions


def _missing_reason(entry: dict) -> bool:
    if entry.get("side") == "BUY":
        return not entry.get("entry_reason")
    return not entry.get("exit_reason")


def build_reflection(date: str, entries_for_day: list[dict], all_entries: list[dict]) -> dict:
    """1日分の反省会データを組み立てる純粋関数（同一入力なら同じ出力、
    ロードマップP1完了条件「同一入力で同じ判定」に対応）。
    """
    if not entries_for_day:
        return {
            "date": date,
            "status": "実績未取得",
            "message": f"{date}の実約定記録なし。台帳未記入か、取引が無かった日。",
            "positions": [],
            "pnl_total_yen": None,
            "discipline_notes": [],
            "missing_reason_count": 0,
            "skipped_candidates_note": "実績未取得のため対象外",
            "improvement_point": None,
        }

    all_positions = pair_positions(all_entries)
    closed_today = [
        p for p in all_positions
        if p["status"] == "決済済み" and (p["closed_at"] or "").startswith(date)
    ]
    open_or_unmatched_today = [
        p for p in all_positions
        if p["status"] != "決済済み" and (p["opened_at"] or "").startswith(date)
    ]
    positions_today = closed_today + open_or_unmatched_today

    pnl_values = [p["realized_pnl_yen"] for p in closed_today if p["realized_pnl_yen"] is not None]
    pnl_total = sum(pnl_values) if pnl_values else None

    discipline_notes = [
        {"trade_id": e["trade_id"], "ticker": e.get("ticker"), "violations": e["rule_violation"]}
        for e in entries_for_day if e.get("rule_violation")
    ]
    missing_reason_entries = [e for e in entries_for_day if _missing_reason(e)]

    if discipline_notes:
        first = discipline_notes[0]
        improvement_point = (
            f"本日記録されたルール逸脱: {'、'.join(first['violations'])}"
            f"（{first['ticker']}・trade_id={first['trade_id']}）。"
            "同じ逸脱を繰り返していないか、次回の売買記録で確認する。"
        )
    elif missing_reason_entries:
        improvement_point = (
            f"本日{len(missing_reason_entries)}/{len(entries_for_day)}件で"
            "entry_reason/exit_reasonが未記入。次回は理由の記入を優先する。"
        )
    else:
        improvement_point = "本日はルール逸脱の記録・記入漏れなし。"

    return {
        "date": date,
        "status": "記録あり",
        "message": f"{date}の実約定{len(entries_for_day)}件を集計。",
        "positions": positions_today,
        "pnl_total_yen": pnl_total,
        "discipline_notes": discipline_notes,
        "missing_reason_count": len(missing_reason_entries),
        "skipped_candidates_note": (
            "見送り理由の自動突合は未接続（signal_contract.record_snapshotの"
            "実運用ログ蓄積待ち）。捏造せず「未接続」と表示している。"
        ),
        "improvement_point": improvement_point,
    }


def render_text(reflection: dict) -> str:
    lines = [
        f"# 反省会 {reflection['date']}",
        "",
        f"状態: {reflection['status']}",
        reflection["message"],
        "",
    ]
    if reflection["status"] == "実績未取得":
        return "\n".join(lines)

    pnl = reflection["pnl_total_yen"]
    pnl_text = "—（本日決済済みポジションなし）" if pnl is None else f"{pnl:+,}円"
    lines += [f"## 損益（実約定・決済済みのみ）", pnl_text, ""]

    lines.append("## ポジション")
    if not reflection["positions"]:
        lines.append("該当なし")
    for p in reflection["positions"]:
        pnl_p = "—" if p["realized_pnl_yen"] is None else f"{p['realized_pnl_yen']:+,}円"
        lines.append(f"- {p.get('name')}（{p.get('ticker')}）: {p['status']} / {pnl_p}")
    lines.append("")

    lines.append("## 規律（rule_violation記録）")
    if not reflection["discipline_notes"]:
        lines.append("記録なし")
    for n in reflection["discipline_notes"]:
        lines.append(f"- {n['ticker']}（{n['trade_id']}）: {'、'.join(n['violations'])}")
    lines.append("")

    lines.append(f"## 記入漏れ（entry_reason/exit_reason未記入）: {reflection['missing_reason_count']}件")
    lines.append("")
    lines.append("## 見送り候補")
    lines.append(reflection["skipped_candidates_note"])
    lines.append("")
    lines.append("## 翌日への改善点1つ")
    lines.append(reflection["improvement_point"])
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="非公開の実約定台帳(data/private/trade_ledger.jsonl)から日次反省会を生成する。"
                     "出力もdata/private/reflections/配下のみ（git追跡されない）。"
    )
    parser.add_argument("--date", default=None, help="YYYY-MM-DD（省略時は本日・JST）")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_arg_parser().parse_args(argv)
    date = args.date or pl.now_jst().strftime("%Y-%m-%d")
    entries_for_day = pl.load_entries(day=date)
    all_entries = pl.load_entries()
    reflection = build_reflection(date, entries_for_day, all_entries)
    text = render_text(reflection)
    print(text)
    REFLECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REFLECTIONS_DIR / f"{date}.md"
    out_path.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
