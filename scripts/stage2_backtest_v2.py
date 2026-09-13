"""
stage2_backtest_v2.py
Stage②の改良版。data/5m_calendars/<code>.json（真の高値・安値を保持した5分足）を使い、
OR5/OR15を使った3つのエントリー手法を比較する。

v1（stage2_backtest.py）との違い:
  - v1はkioxia_5m_calendar.jsonの終値だけの近似だったため、ザラ場中のヒゲを
    捕捉できず、損切りが実際より遅れる（成績が良く出過ぎる）方向のバイアスが
    あった。v2はmulti_ticker_5m_calendar.pyが集めた真のOHLCを使うため、
    このバイアスを解消できる。
  - 単一足の高値・安値の両方に損切り・利確ラインが含まれる場合（＝その足の中で
    どちらが先に来たか分からない場合）は、既存のpaper_trade_history.jsonの
    運用と同じルールで「順序不明」として成績から除外する。
  - キオクシア1銘柄だけでなく、data/5m_calendars/以下にある全銘柄（watch_top5経由で
    集まった銘柄）を対象にする。銘柄をまたいで合算する点はv1にはなかった変更。

3手法・共通ルールはv1と同じ（OR5早期参入 / OR5監視→OR15参加 / OR5参入・OR15利確）。

正直な制約:
  - data/5m_calendars/以下の銘柄は「その時点のwatch_top5に載っていた」銘柄の
    寄せ集めであり、常に同じ銘柄群ではない（日によって監視対象が変わるため）。
    銘柄選定バイアス（後から見て強かった銘柄だけが多く含まれる可能性）が
    ゼロとは言い切れない。
  - n<30ゲートは維持する。
"""
import json
from pathlib import Path

ENTRY_THRESHOLD = 0.0
STOP_DISTANCE = 1.0
TARGET_DISTANCE = 1.5
COST_PCT = 0.05
MIN_N_RELIABLE = 30

CALENDAR_DIR = Path("data/5m_calendars")


def load_all_calendars() -> list[dict]:
    days = []
    if not CALENDAR_DIR.exists():
        return days
    for f in sorted(CALENDAR_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for day in data.get("days", []):
            day["_code"] = data.get("code")
            days.append(day)
    return days


def or5_or15(bars: list[dict]):
    """真の高値・安値からOR5/OR15レンジを出す。"""
    if len(bars) < 4:
        return None
    or5 = {"h": bars[0]["h"], "l": bars[0]["l"], "entry_c": bars[0]["c"]}
    or15_bars = bars[:3]
    or15 = {
        "h": max(b["h"] for b in or15_bars),
        "l": min(b["l"] for b in or15_bars),
        "entry_c": bars[2]["c"],
    }
    return or5, or15


def simulate(bars: list[dict], entry_idx: int, forced_exit_idx: int = None):
    """entry_idxの足の終値でエントリーし、以降の足を高値・安値ベースで追跡する。
    同一足内で損切り・利確の両方に触れる場合は順序不明として None を返す
    （成績から除外）。forced_exit_idxを渡すと、それまでの間に損切りに
    触れなければforced_exit_idx足の終値で機械的に手仕舞う（Cの「OR15利確」用）。
    途中で損切りに触れた場合は、forced_exit_idxが指定されていても損切りを優先する
    （実際の注文なら損切り注文は生きたままのため）。"""
    if entry_idx >= len(bars):
        return None
    entry_ret = bars[entry_idx]["c"]
    stop_level = entry_ret - STOP_DISTANCE
    target_level = entry_ret + TARGET_DISTANCE

    end = forced_exit_idx if forced_exit_idx is not None else len(bars) - 1
    for i in range(entry_idx + 1, min(end, len(bars) - 1) + 1):
        b = bars[i]
        hit_stop = b["l"] <= stop_level
        hit_target = (forced_exit_idx is None) and b["h"] >= target_level
        if hit_stop and hit_target:
            return None  # 順序不明・除外
        if hit_stop:
            return (stop_level - entry_ret - COST_PCT) / STOP_DISTANCE
        if hit_target:
            return (target_level - entry_ret - COST_PCT) / STOP_DISTANCE
        if forced_exit_idx is not None and i == forced_exit_idx:
            return (b["c"] - entry_ret - COST_PCT) / STOP_DISTANCE
    return (bars[-1]["c"] - entry_ret - COST_PCT) / STOP_DISTANCE


def run_method(all_days: list[dict], method: str):
    rs = []
    excluded_ambiguous = 0
    candidate_days = 0
    for day in all_days:
        bars = day.get("bars", [])
        ranges = or5_or15(bars)
        if ranges is None:
            continue
        candidate_days += 1
        or5, or15 = ranges

        if method == "A_or5_early":
            if or5["entry_c"] >= ENTRY_THRESHOLD:
                r = simulate(bars, 0)
                (rs.append(r) if r is not None else None)
                if r is None:
                    excluded_ambiguous += 1
        elif method == "B_or5_watch_or15_enter":
            if or5["entry_c"] >= ENTRY_THRESHOLD and or15["entry_c"] >= ENTRY_THRESHOLD:
                r = simulate(bars, 2)
                (rs.append(r) if r is not None else None)
                if r is None:
                    excluded_ambiguous += 1
        elif method == "C_or5_enter_or15_exit":
            if or5["entry_c"] >= ENTRY_THRESHOLD:
                r = simulate(bars, 0, forced_exit_idx=2)
                (rs.append(r) if r is not None else None)
                if r is None:
                    excluded_ambiguous += 1
    return rs, candidate_days, excluded_ambiguous


def max_drawdown(rs):
    cum, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def summarize(rs, candidate_days, excluded):
    n = len(rs)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return {
        "candidate_days": candidate_days,
        "triggered_n": n,
        "excluded_ambiguous_order": excluded,
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else None,
        "avg_r": round(sum(rs) / n, 3) if n else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_r": round(max_drawdown(rs), 2) if rs else None,
        "status": "参考値（要検証、優位性確立を意味しない）" if n >= MIN_N_RELIABLE else "試運転・検証中（サンプル不足）",
    }


def main():
    all_days = load_all_calendars()
    tickers = sorted({d["_code"] for d in all_days})
    methods = ["A_or5_early", "B_or5_watch_or15_enter", "C_or5_enter_or15_exit"]

    results = {}
    for m in methods:
        rs, candidate_days, excluded = run_method(all_days, m)
        results[m] = {**summarize(rs, candidate_days, excluded), "r_values": [round(r, 3) for r in rs]}

    out = {
        "universe": tickers,
        "universe_note": "watch_top5経由で集まった銘柄群。日によって銘柄構成が変わるため銘柄選定バイアスの可能性あり。",
        "total_candidate_days": len(all_days),
        "assumptions": {
            "entry_threshold_pct": ENTRY_THRESHOLD,
            "stop_distance_pct": STOP_DISTANCE,
            "target_distance_pct": TARGET_DISTANCE,
            "cost_pct": COST_PCT,
            "note": "真の高値・安値を使用。同一足内で損切り・利確の両方に触れた場合は順序不明として除外。",
        },
        "results": results,
    }
    Path("stage2_comparison_v2.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
