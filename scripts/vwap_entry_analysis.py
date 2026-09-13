"""
vwap_entry_analysis.py
「勝ったREBOUNDと負けたREBOUNDで何が違うか」を、既存のpaper_trade_history.jsonの
記録（entry, vwap, morning_price）だけを使って統計的に検証する。

正直な制約:
  - paper_trade_history.jsonには時系列の値動き（押し目を作ったかどうかの経路）は
    記録されていない。ここでの「vwap」は当日引け（または時点評価）時点の値であり、
    エントリー"時点"のVWAPそのものではない。そのため「押し目を作ってから再度
    VWAP上に戻った」という値動きの"形"そのものは検証できていない。
  - 代わりに、次の2つの代理指標で近似する:
      entry_vwap_gap_pct : エントリー価格が、その日のVWAP（引け時点）から見て
                            高い位置だったか低い位置だったかの割合
      entry_extension_pct: エントリー価格が、朝8時時点の基準値からどれだけ
                            既に動いていたか
    これは「エントリーが日中平均より割安だったか割高だったか」の代理であり、
    本来の「途中で一度押し目を作ったか」とは厳密には別物。今後、5分足の
    経路データ（multi_ticker_5m_calendar.py）が貯まれば、より正確な検証に
    置き換えられる。
  - サンプル数（n=21, n=22）はどちらもユーザー指定のn<30ゲート未満のため、
    このレポートの結果も「試運転・検証中」として扱う。

出力: vwap_entry_analysis.json
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
MIN_N_RELIABLE = 30


def entry_vwap_gap(r: dict):
    if not r.get("vwap") or not r.get("entry"):
        return None
    return (r["entry"] - r["vwap"]) / r["vwap"] * 100


def entry_extension(r: dict):
    if not r.get("morning_price") or not r.get("entry"):
        return None
    return (r["entry"] - r["morning_price"]) / r["morning_price"] * 100


def summarize(rows: list) -> dict:
    n = len(rows)
    wins = [r for r in rows if r["r"] > 0]
    losses = [r for r in rows if r["r"] <= 0]
    gross_win = sum(r["r"] for r in wins)
    gross_loss = -sum(r["r"] for r in losses)
    return {
        "n": n,
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else None,
        "avg_r": round(sum(r["r"] for r in rows) / n, 3) if n else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "status": "参考値（要検証）" if n >= MIN_N_RELIABLE else "試運転・検証中（サンプル不足）",
    }


def main():
    history = json.loads(Path("paper_trade_history.json").read_text(encoding="utf-8"))
    triggered = [
        r for r in history
        if r.get("triggered") and isinstance(r.get("r"), (int, float))
        and r.get("vwap") and r.get("entry")
    ]

    below_vwap = [r for r in triggered if entry_vwap_gap(r) < 0]
    above_vwap = [r for r in triggered if entry_vwap_gap(r) >= 0]

    out = {
        "generated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "note": (
            "entryがVWAP(引け時点)未満だったか以上だったかで成績を分けた分析。"
            "経路（押し目の有無）そのものではなく代理指標であることに注意。"
            "n<30のため『試運転・検証中』のまま扱うこと。"
        ),
        "below_vwap_entry": summarize(below_vwap),
        "above_vwap_entry": summarize(above_vwap),
        "avg_entry_extension_pct": {
            "wins": round(sum(entry_extension(r) for r in triggered if r["r"] > 0) / max(1, sum(1 for r in triggered if r["r"] > 0)), 3),
            "losses": round(sum(entry_extension(r) for r in triggered if r["r"] <= 0) / max(1, sum(1 for r in triggered if r["r"] <= 0)), 3),
        },
    }
    Path("vwap_entry_analysis.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
