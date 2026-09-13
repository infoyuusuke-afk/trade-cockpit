"""
short_candidates.py
SHORT側の紙トレード候補をMVPとして生成する。

背景:
  update.py の build_day_ifo_candidates() はLONGブレイクアウト専用で、
  テーマ株バケット分類など作り込まれた選定ロジックを持つ。
  一方 signal_scan.py の analyse_short() はSHORTセットアップを検知しているが、
  この結果は紙トレード実行パイプラインに接続されていなかった（診断済み）。

このスクリプトの位置づけ:
  LONG側と同水準の作り込み（テーマバケット等）はまだ行わず、
  まず「下落トレンド＋出来高を伴う戻り売り」という単純な条件で
  日次のSHORT候補を最大5件出す。LONGより単純なぶん精度は未検証。
  → 出力は day_ifo_candidates_short.json（data.jsonやday_ifo_candidatesとは
     別ファイルに分離し、既存の巨大な update.py には一切手を入れない）。

前提: data.json の stocks 辞書に close/ma5/ma20/rvol/atr_pct/from_ma20/turnover 等が
      揃っていること（build_day_ifo_candidatesと同じ入力を再利用）。
"""
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))


def price_tick(price: float) -> float:
    return 1.0 if price < 3000 else 5.0


def load_margin_caution() -> dict:
    """東証の日々公表銘柄リストを読み込む。存在しない/未取得なら空。"""
    p = Path("margin_caution.json")
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {d["code"]: d for d in data.get("designated", [])}


def build_short_candidates(stocks: dict, credit_supply: dict) -> list[dict]:
    margin_caution = load_margin_caution()
    eligible = []
    for name, row in stocks.items():
        if row.get("style") not in ("day", "both"):
            continue
        code = str(row.get("ticker", "")).split(".")[0]
        price = float(row.get("price") or 0)
        ma5 = float(row.get("ma5") or 0)
        ma20 = float(row.get("ma20") or 0)
        rvol = float(row.get("rvol") or 0)
        atr_pct = float(row.get("atr_pct") or 99)
        from_ma20 = float(row.get("from_ma20") or 0)
        turnover = float(row.get("turnover") or 0)
        change_pct = float(row.get("change_pct") or 0)

        if not (100 <= price <= 30000):
            continue
        if turnover < 1_000_000_000:  # LONG側より流動性条件はやや緩め（SHORTは母数が少ないため）
            continue
        down_order = 0 < price < ma5 < ma20
        falling = from_ma20 < -3
        high_vol_selloff = rvol >= 1.2 and change_pct < -1.5
        not_squeeze_prone = atr_pct <= 9.0
        if not (down_order and falling and high_vol_selloff and not_squeeze_prone):
            continue

        supply = credit_supply.get(code, {})
        supply_phase = supply.get("supply_phase")
        # 信用需給が「改善（＝戻り売り圧力低下）」の銘柄はSHORT候補として矛盾するため除外
        if supply_phase == "改善":
            continue

        caution = margin_caution.get(code)
        if caution and caution.get("regulated"):
            # 東証が新規信用取引等を規制中の銘柄はSHORT候補から除外
            continue

        tick = price_tick(price)
        low = float(row.get("low") or price)
        high = float(row.get("high") or price)
        trigger = math.floor((low - tick) / tick) * tick
        atr = max(float(row.get("atr14") or price * 0.02), price * 0.008)
        stop = math.ceil(max(high + atr * 0.30, ma5 + atr * 0.30) / tick) * tick
        risk = max(stop - trigger, tick)

        score = round(
            30
            + (15 if rvol >= 1.5 else 8)
            + (15 if turnover >= 3_000_000_000 else 8)
            + (15 if atr_pct <= 5 else 8)
            + (15 if supply_phase == "悪化" else 0)
        )
        score = min(100, score)
        if score < 60:
            continue

        eligible.append({
            "name": name,
            "code": code,
            "ticker": row.get("ticker", ""),
            "side": "SHORT",
            "score": score,
            "trigger": trigger,
            "stop": stop,
            "target1": round((trigger - risk * 1.5) / tick) * tick,
            "target2": round((trigger - risk * 2.5) / tick) * tick,
            "rvol": round(rvol, 2),
            "atr_pct": round(atr_pct, 2),
            "supply_phase": supply_phase,
            "margin_caution_flagged": caution is not None,
            "reason": (
                f"下降配列（終値<5日線<20日線）／20日線からの乖離{from_ma20:.1f}%／"
                f"出来高比{rvol:.2f}倍／信用需給{supply_phase or '不明'}"
            ),
            "caution": (
                "東証の日々公表銘柄に指定中。品貸料・在庫を必ず確認。"
                if caution else
                "貸借銘柄・在庫・逆日歩・空売り規制を楽天MS2で必ず確認。"
            ),
            "status": "試運転・検証中（LONG側と異なりまだ実績なし）",
        })

    eligible.sort(key=lambda x: x["score"], reverse=True)
    return eligible[:5]


def main():
    data = json.loads(Path("data.json").read_text(encoding="utf-8"))
    credit = json.loads(Path("credit_supply.json").read_text(encoding="utf-8")).get("stocks", {})
    stocks = data.get("stocks", {})

    candidates = build_short_candidates(stocks, credit)

    out = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "side": "SHORT",
        "status": "試運転・検証中",
        "count": len(candidates),
        "candidates": candidates,
    }
    Path("day_ifo_candidates_short.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"day_ifo_candidates_short.json written: {len(candidates)}件")


if __name__ == "__main__":
    main()
