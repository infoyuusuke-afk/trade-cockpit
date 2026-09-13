"""
watch_top5.py
「監視TOP5 → 当日発動候補」の2段階構成のうち、第1段階（監視TOP5の確定）。

設計方針:
  - 当日の寄り付き前（例: 前営業日の引け後）に実行し、その時点で"知り得た"
    data.json（決算・信用需給・材料イベント等を含む）だけを使ってTOP5を決める。
  - 決定した瞬間の情報だけを使ったことを証明するため、
    decision_asof（このリストを確定した時刻）を必ず記録する。
  - Jumping Point!! 株Tube（mentions.json）の内容は、ここでは一切スコアに使わない。
    使ってしまうと「紹介されたから上がる」という後追いバイアスになるため。
    その代わり、confirmed_tickers に載っている銘柄がこの監視リストに
    「たまたま」含まれていたかどうかだけを記録し、後段の的中率検証に使う。
  - 当日の実際のエントリー判断（OR5・VWAP・出来高・GU/GD）は別スクリプト
    （day_trigger.py, 未実装）が、このwatch_top5.jsonを入力として行う。
    つまり当日の値動きはここでは一切見ない。
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def score_candidate(row: dict) -> float:
    """day_score/swing_scoreなど既存の指標を単純合成した仮スコア。
    build_day_ifo_candidatesほど厳密ではないため、監視段階の粗い足切り用途に限定する。"""
    day_score = float(row.get("day_score") or 0)
    supply_bonus = 10 if row.get("market_supply_improved") else 0
    liquidity_bonus = 10 if float(row.get("turnover") or 0) >= 2_000_000_000 else 0
    return day_score + supply_bonus + liquidity_bonus


def main():
    data = load_json("data.json", {})
    mentions = load_json("mentions.json", {"videos": []})

    rows = []
    for name, row in (data.get("stocks") or {}).items() if isinstance(data.get("stocks"), dict) else []:
        rows.append((name, row))
    # data.jsonの実際の格納形式に合わせて調整が必要な場合あり（要確認）
    if not rows:
        print("警告: data.jsonからの銘柄一覧取得に失敗。スキーマを確認してください。")
        return

    scored = []
    for name, row in rows:
        if row.get("style") not in ("day", "both"):
            continue
        s = score_candidate(row)
        scored.append({
            "code": str(row.get("ticker", "")).split(".")[0],
            "name": name,
            "ticker": row.get("ticker"),
            "watch_score": round(s, 1),
            "day_score": row.get("day_score"),
            "market_supply_improved": row.get("market_supply_improved"),
            "turnover": row.get("turnover"),
        })

    scored.sort(key=lambda x: x["watch_score"], reverse=True)
    top5 = scored[:5]

    # confirmed_tickers（手動確認済みの株Tube紹介銘柄）との突合。スコアには一切影響させない。
    confirmed_codes = set()
    for v in mentions.get("videos", []):
        for t in v.get("confirmed_tickers", []):
            confirmed_codes.add(t.get("code"))
    for item in top5:
        item["also_in_confirmed_mentions"] = item["code"] in confirmed_codes

    out = {
        "decision_asof": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "note": "この時点の情報のみで確定。株Tube紹介の有無はスコアに含めていない（観測用の参考情報のみ）。",
        "top5": top5,
    }

    Path("watch_top5.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"watch_top5.json written: {len(top5)}件")


if __name__ == "__main__":
    main()
