"""
swing_signal.py
「スイング（1週間）」レイヤーのMVPシグナル生成。

入力:
  - credit_supply.json  : 銘柄別・信用取引残高の週次変化（supply_phase / trade_bias）
  - investor_regime.json: 市場全体の投資部門別売買動向（外国人・個人等の週次フロー転換）

出力: signals_swing.json
  各銘柄について 0-100 のスコアと方向性（LONG/SHORT/WATCH）、根拠を出す。
  デイレイヤー(signals_day.json)と違い、エントリー価格やstop/targetは出さない
  （スイングは値ではなく「地合いの向き」を判定する層のため）。

注意: これは初期版（MVP）。実際の勝率検証は paper_trade_history 等に
      horizon="swing" のタグを付けて記録し、weekly_review的な集計で行うこと。
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signal_contract as sc

JST = timezone(timedelta(hours=9))

# 週次更新データのため秒単位TTLは適用しない（C-031-GPT第3節）。
# 更新が完全に止まっていないかを確認する大まかな健全性チェックとして10日を使う。
WEEKLY_TTL_SECONDS = 10 * 24 * 3600


def foreign_flow_bias(investor_regime: dict) -> tuple[int, list[str]]:
    """市場全体の外国人・個人フローから、地合いスコア(-20〜+20)と理由を返す。"""
    score = 0
    reasons = []
    for subj in investor_regime.get("subjects", []):
        if subj.get("subject") == "foreign":
            reversal = subj.get("reversal")
            streak = subj.get("streak_weeks") or 0
            if reversal == "売→買":
                score += 15
                reasons.append(f"海外投資家が売→買に転換（{streak}週目）")
            elif reversal == "買→売":
                score -= 15
                reasons.append(f"海外投資家が買→売に転換（{streak}週目）")
    regime = investor_regime.get("regime", {})
    if regime.get("name") and regime.get("name") != "MIXED":
        reasons.append(f"市場レジーム: {regime.get('name')}（確信度{regime.get('confidence')}）")
    return score, reasons


def credit_bias(entry: dict) -> tuple[int, list[str]]:
    """個別銘柄の信用需給からスコア(-30〜+30)と理由を返す。"""
    score = 0
    reasons = []
    phase = entry.get("supply_phase")
    if phase == "改善":
        score += 20
        reasons.append(f"信用需給フェーズ: 改善（{entry.get('trade_bias', '')}）")
    elif phase == "悪化":
        score -= 20
        reasons.append(f"信用需給フェーズ: 悪化（{entry.get('trade_bias', '')}）")

    chg1w = entry.get("margin_buy_change_1w_pct")
    if isinstance(chg1w, (int, float)):
        if chg1w <= -10:
            score += 10
            reasons.append(f"信用買い残が週次{chg1w:.1f}%減少（戻り売り圧力の低下）")
        elif chg1w >= 10:
            score -= 10
            reasons.append(f"信用買い残が週次{chg1w:.1f}%増加（将来の戻り売り圧力増）")
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
    with open("investor_regime.json", encoding="utf-8") as f:
        regime = json.load(f)

    # RSS鮮度・欠測ゲート（C-031-GPT P0）。信用需給・投資部門別データが更新停止していたら、
    # 古い週次データのままスコアリングせず全銘柄WAITとする（EV・スコアをゼロ補完しない）。
    credit_point = sc.DataPoint(credit, fetched_at=sc.parse_jst_timestamp(credit.get("updated_at")))
    regime_point = sc.DataPoint(regime, fetched_at=sc.parse_jst_timestamp(
        regime.get("generated_at") or regime.get("decision_at")))
    credit_quality = sc.check_freshness(credit_point, WEEKLY_TTL_SECONDS, now)
    regime_quality = sc.check_freshness(regime_point, WEEKLY_TTL_SECONDS, now)
    trade_allowed, block_reasons = sc.gate_no_trade(credit_quality, regime_quality)

    market_score, market_reasons = foreign_flow_bias(regime) if trade_allowed else (0, [])

    signals = []
    for code, entry in credit.get("stocks", {}).items():
        if not trade_allowed:
            signals.append({
                "code": code,
                "name": entry.get("name"),
                "score": None,
                "direction": "WAIT",
                "reasons": [f"データ鮮度不足のため判定保留（{', '.join(block_reasons)}）"],
                "horizon": "swing",
            })
            continue
        c_score, c_reasons = credit_bias(entry)
        total = c_score + market_score
        signals.append({
            "code": code,
            "name": entry.get("name"),
            "score": total,
            "direction": classify(total),
            "supply_phase": entry.get("supply_phase"),
            "trade_bias": entry.get("trade_bias"),
            "margin_buy_change_1w_pct": entry.get("margin_buy_change_1w_pct"),
            "credit_ratio": entry.get("credit_ratio"),
            "reasons": c_reasons + market_reasons,
            "horizon": "swing",
        })

    out = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "horizon": "swing",
        "data_quality": {
            "credit_supply": credit_quality,
            "investor_regime": regime_quality,
            "trade_allowed": trade_allowed,
            "block_reasons": block_reasons,
        },
        "universe_count": len(signals),
        "market_score": market_score,
        "market_reasons": market_reasons,
        "signals": signals,
    }

    with open("signals_swing.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"signals_swing.json written: {len(signals)} tickers scored")


if __name__ == "__main__":
    main()
