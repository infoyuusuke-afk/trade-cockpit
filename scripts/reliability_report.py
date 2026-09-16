"""
reliability_report.py
paper_trade_history.json を LONG/SHORT別・horizon別に集計し、
サンプル数が閾値未満の場合は「試運転・検証中」ラベルを強制する。

目的: 母数が少ない段階で勝率やPFを「確立した手法」であるかのように
      表示してしまうのを防ぐ（今回の依頼で明示された要件）。

閾値は暫定でn=30。統計的に十分とは言えないが、デイトレのように
1日数件しか出ない戦略でこれ以上厳しくすると何か月も判定できなくなるため、
「参考値として出し始めてよい最低限」の実務的な線として置いている。
n=30到達後も、誤差の大きさを明示するために信頼区間の概算を添える。
"""
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
MIN_N = 30


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """勝率の95%信頼区間（Wilson score interval）。nが小さいときの誤差幅を明示するため。"""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z ** 2 / n
    centre = p + z ** 2 / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z ** 2 / (4 * n)) / n)
    lower = (centre - adj) / denom
    upper = (centre + adj) / denom
    return round(lower * 100, 1), round(upper * 100, 1)


def summarize(records: list[dict]) -> dict:
    resolved = [r for r in records if r.get("triggered") and isinstance(r.get("r"), (int, float))]
    total_recorded = len(records)
    n = len(resolved)
    wins = sum(1 for r in resolved if r["r"] > 0)
    gross_win = sum(r["r"] for r in resolved if r["r"] > 0)
    gross_loss = -sum(r["r"] for r in resolved if r["r"] <= 0)
    win_rate = round(wins / n * 100, 1) if n else None
    avg_r = round(sum(r["r"] for r in resolved) / n, 3) if n else None
    pf = round(gross_win / gross_loss, 2) if gross_loss else (None if not n else float("inf"))

    # 簡易最大DD（Rベースの累積曲線から算出）
    cum, peak, max_dd = 0.0, 0.0, 0.0
    for r in resolved:
        cum += r["r"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    ci = wilson_interval(wins, n) if n else None
    reliable = n >= MIN_N

    return {
        "total_recorded": total_recorded,   # 記録された全件数（未発動・見送り含む）
        "resolved_n": n,                     # 発動して勝敗が確定した件数（＝実際の検証母数）
        "win_rate_pct": win_rate,
        "win_rate_95ci": ci,
        "avg_r": avg_r,
        "profit_factor": pf,
        "max_drawdown_r": round(max_dd, 2) if resolved else None,
        "status": "参考値（要検証）" if reliable else "試運転・検証中（サンプル不足）",
        "min_n_threshold": MIN_N,
    }


def main():
    history = json.loads(Path("paper_trade_history.json").read_text(encoding="utf-8"))

    by_side = {}
    for side in ("LONG", "SHORT"):
        by_side[side] = summarize([r for r in history if r.get("side") == side])

    # Issue #18「C-045-GPT」優先順位1: strategy_id別の集計を追加。
    # strategy_schema.pyを経由していない過去レコードにはstrategy_idキー自体が無いため、
    # それらは推測でどれかの戦略に割り当てず"UNTAGGED_LEGACY"として明示的に分離する
    # （件数を消さず、旧スキーマ由来だと分かる形で残す）。
    strategy_ids = sorted({r.get("strategy_id") for r in history if r.get("strategy_id")})
    by_strategy = {sid: summarize([r for r in history if r.get("strategy_id") == sid]) for sid in strategy_ids}
    untagged = [r for r in history if not r.get("strategy_id")]
    if untagged:
        by_strategy["UNTAGGED_LEGACY"] = summarize(untagged)

    # regimeも同じ理由でregime未記録の過去レコードを別集計にする。
    regimes = sorted({r.get("regime") for r in history if r.get("regime")})
    by_regime = {reg: summarize([r for r in history if r.get("regime") == reg]) for reg in regimes}

    out = {
        "generated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "note": (
            f"resolved_n が{MIN_N}件未満の区分は、勝率・PFを『確立した手法』として"
            "扱わないこと。95%信頼区間の幅が広いほど、まだ結論を出せる段階ではない。"
            "by_strategy/by_regimeはstrategy_schema.py導入(2026-09-17)以降のレコードのみ"
            "区分でき、それ以前のレコードはUNTAGGED_LEGACYにまとめている。"
        ),
        "by_side": by_side,
        "by_strategy": by_strategy,
        "by_regime": by_regime,
    }
    Path("reliability_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
