"""
long_signal.py
「長期（1か月）」レイヤーのMVPシグナル生成。

入力:
  - credit_supply.json  : margin_buy_change_4w_pct（信用買い残の4週トレンド＝構造的な需給）
  - buybacks.json        : 自社株買いプログラム（発表があれば強い長期材料として加点）
  - correlations.json    : 同業種ピアとの相関・方向一致（セクター全体の地合い確認に利用）

出力: signals_long.json
  スイング層より重い時間軸のため、日々の細かい変動ではなく
  「構造的な需給トレンド」と「セクター全体の追い風/向かい風」だけで判定する。

注意: buybacks.json が空（プログラムなし）の場合、自社株買い加点は発生しない。
      これはKioxiaが自社株買いを発表した際に自動で効いてくる設計。
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signal_contract as sc

JST = timezone(timedelta(hours=9))

# 週次〜不定期更新データのため秒単位TTLは適用しない（C-031-GPT第3節）。
# 更新が完全に止まっていないかを確認する大まかな健全性チェックとして10日を使う。
WEEKLY_TTL_SECONDS = 10 * 24 * 3600


def credit_4w_bias(entry: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    chg4w = entry.get("margin_buy_change_4w_pct")
    if isinstance(chg4w, (int, float)):
        if chg4w <= -10:
            score += 15
            reasons.append(f"信用買い残が4週で{chg4w:.1f}%減少（構造的な需給改善）")
        elif chg4w >= 10:
            score -= 15
            reasons.append(f"信用買い残が4週で{chg4w:.1f}%増加（構造的な需給悪化）")
    return score, reasons


def buyback_bias(code: str, buybacks: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []
    for program in buybacks.get("programs", []):
        if program.get("code") == code or program.get("ticker", "").startswith(code):
            score += 25
            reasons.append(f"自社株買いプログラム: {program.get('summary', program)}")
    return score, reasons


def sector_alignment_bias(code: str, correlations: dict) -> tuple[int, list[str]]:
    """相関の高いピア銘柄が同方向に強く動いているかを長期の地合い確認として使う。"""
    score = 0
    reasons = []
    strong_same_direction = 0
    checked = 0
    for rel in correlations.get("relationships", []):
        if code not in (rel.get("anchor_ticker", ""), rel.get("anchor", "")):
            continue
        checked += 1
        if (rel.get("corr60") or 0) >= 0.6 and rel.get("state") == "確認":
            strong_same_direction += 1
    if checked:
        ratio = strong_same_direction / checked
        if ratio >= 0.6:
            score += 10
            reasons.append(f"高相関ピア{checked}銘柄中{strong_same_direction}銘柄でセクター追い風を確認")
    return score, reasons


def classify(score: int) -> str:
    if score >= 20:
        return "LONG"
    if score <= -20:
        return "SHORT"
    return "WATCH"


def main():
    now = sc.now_jst()
    with open("credit_supply.json", encoding="utf-8") as f:
        credit = json.load(f)
    with open("buybacks.json", encoding="utf-8") as f:
        buybacks = json.load(f)
    with open("correlations.json", encoding="utf-8") as f:
        correlations = json.load(f)

    # RSS鮮度・欠測ゲート（C-031-GPT P0）。buybacks.jsonは現状「未取得」の空プレースホルダー
    # （programs=[]なら加点なしという既存設計）のため鮮度ゲートの対象に含めない。
    # 実データを継続的に更新しているcredit_supply.json・correlations.jsonだけを対象にする。
    credit_point = sc.DataPoint(credit, fetched_at=sc.parse_jst_timestamp(credit.get("updated_at")))
    corr_point = sc.DataPoint(correlations, fetched_at=sc.parse_jst_timestamp(correlations.get("updated_at")))
    credit_quality = sc.check_freshness(credit_point, WEEKLY_TTL_SECONDS, now)
    corr_quality = sc.check_freshness(corr_point, WEEKLY_TTL_SECONDS, now)
    trade_allowed, block_reasons = sc.gate_no_trade(credit_quality, corr_quality)

    signals = []
    for code, entry in credit.get("stocks", {}).items():
        if not trade_allowed:
            signals.append({
                "code": code,
                "name": entry.get("name"),
                "score": None,
                "direction": "WAIT",
                "reasons": [f"データ鮮度不足のため判定保留（{', '.join(block_reasons)}）"],
                "horizon": "long",
            })
            continue
        c_score, c_reasons = credit_4w_bias(entry)
        b_score, b_reasons = buyback_bias(code, buybacks)
        s_score, s_reasons = sector_alignment_bias(f"{code}.T", correlations)
        total = c_score + b_score + s_score
        signals.append({
            "code": code,
            "name": entry.get("name"),
            "score": total,
            "direction": classify(total),
            "margin_buy_change_4w_pct": entry.get("margin_buy_change_4w_pct"),
            "reasons": c_reasons + b_reasons + s_reasons,
            "horizon": "long",
        })

    out = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "horizon": "long",
        "data_quality": {
            "credit_supply": credit_quality,
            "correlations": corr_quality,
            "trade_allowed": trade_allowed,
            "block_reasons": block_reasons,
        },
        "universe_count": len(signals),
        "signals": signals,
    }

    with open("signals_long.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"signals_long.json written: {len(signals)} tickers scored")


if __name__ == "__main__":
    main()
