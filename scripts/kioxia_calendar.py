"""Kioxia 5-minute calendar and nearest historical intraday pattern search."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kioxia_5m_calendar.json"
JST = ZoneInfo("Asia/Tokyo")


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def flat(frame):
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.columns = [str(x).title() for x in frame.columns]
    return frame.dropna(subset=["Close"])


def session_days(frame):
    if frame.empty:
        return []
    idx = pd.to_datetime(frame.index)
    if idx.tz is None:
        idx = idx.tz_localize("UTC").tz_convert(JST)
    else:
        idx = idx.tz_convert(JST)
    frame = frame.copy()
    frame.index = idx
    frame = frame.between_time("09:00", "15:30")
    return [(str(day), part.copy()) for day, part in frame.groupby(frame.index.date) if len(part) >= 3]


def series_points(values, limit=61):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return []
    if len(values) > limit:
        pick = np.linspace(0, len(values) - 1, limit).round().astype(int)
        values = values[pick]
    return [round(float(x), 3) for x in values]


def classify(day):
    close = day["Close"].astype(float)
    open_ = float(day["Open"].iloc[0])
    last = float(close.iloc[-1])
    high_at = int(np.argmax(day["High"].astype(float).values))
    low_at = int(np.argmin(day["Low"].astype(float).values))
    ret = (last / open_ - 1) * 100
    vwap = ((day["High"] + day["Low"] + day["Close"]) / 3 * day["Volume"].fillna(0)).cumsum()
    vol = day["Volume"].fillna(0).cumsum().replace(0, np.nan)
    vwap_last = finite((vwap / vol).iloc[-1])
    if ret >= 1 and last > (vwap_last or last):
        return "上昇トレンド"
    if high_at <= 3 and ret <= -.5:
        return "寄り天"
    if low_at <= 3 and ret >= .5:
        return "寄り底"
    if ret <= -1 and last < (vwap_last or last):
        return "下落継続"
    return "レンジ"


def day_view(date, day):
    open_ = float(day["Open"].iloc[0])
    close = day["Close"].astype(float)
    normalized = (close / open_ - 1) * 100
    return {
        "date": date, "ret": round(float(normalized.iloc[-1]), 2),
        "high": round((float(day["High"].max()) / open_ - 1) * 100, 2),
        "low": round((float(day["Low"].min()) / open_ - 1) * 100, 2),
        "type": classify(day), "bars": len(day),
        "path": series_points(normalized.values),
        "volume_path": series_points(day["Volume"].fillna(0).cumsum().values),
    }


def scaled(values, count):
    values = np.asarray(values, dtype=float)
    if len(values) == count:
        return values
    xp = np.linspace(0, 1, len(values))
    return np.interp(np.linspace(0, 1, count), xp, values)


def match_distance(current, past, observed):
    cur_close = current["Close"].astype(float).iloc[:observed]
    old_close = past["Close"].astype(float).iloc[:observed]
    if len(old_close) < observed:
        return None
    cur_path = (cur_close / float(current["Open"].iloc[0]) - 1).values * 100
    old_path = (old_close / float(past["Open"].iloc[0]) - 1).values * 100
    cur_vol = current["Volume"].fillna(0).iloc[:observed].cumsum().values
    old_vol = past["Volume"].fillna(0).iloc[:observed].cumsum().values
    cur_vol = cur_vol / max(cur_vol[-1], 1)
    old_vol = old_vol / max(old_vol[-1], 1)
    path_rmse = float(np.sqrt(np.mean((cur_path - old_path) ** 2)))
    volume_rmse = float(np.sqrt(np.mean((cur_vol - old_vol) ** 2)))
    # Opening 15 minutes and the most recent bars matter most for actual execution.
    or_count = min(4, observed)
    or_rmse = float(np.sqrt(np.mean((cur_path[:or_count] - old_path[:or_count]) ** 2)))
    recent_count = min(6, observed)
    recent_rmse = float(np.sqrt(np.mean((cur_path[-recent_count:] - old_path[-recent_count:]) ** 2)))
    distance = path_rmse * .40 + or_rmse * .25 + recent_rmse * .25 + volume_rmse * 2.0 * .10
    return distance


def main():
    try:
        raw = yf.download("285A.T", period="60d", interval="5m", auto_adjust=False,
                          progress=False, threads=False, timeout=45)
        frame = flat(raw)
    except Exception as exc:
        print(f"キオクシア5分足取得失敗。前回値を保持: {exc}")
        return
    sessions = session_days(frame)
    if len(sessions) < 2:
        print("キオクシア5分足の比較可能日数が不足。前回値を保持")
        return
    views = [day_view(date, day) for date, day in sessions]
    current_date, current = sessions[-1]
    today = datetime.now(JST).date().isoformat()
    current_is_today = current_date == today
    # At most the available current bars; before 9:15 no direction prediction is issued.
    observed = min(len(current), 78)
    matches = []
    for (date, past), view in zip(sessions[:-1], views[:-1]):
        distance = match_distance(current, past, observed)
        if distance is None:
            continue
        open_ = float(past["Open"].iloc[0])
        at_match = float(past["Close"].iloc[observed - 1])
        rest = past.iloc[observed - 1:]
        final = float(past["Close"].iloc[-1])
        after = (final / at_match - 1) * 100
        max_up = (float(rest["High"].max()) / at_match - 1) * 100
        max_down = (float(rest["Low"].min()) / at_match - 1) * 100
        similarity = max(0, min(100, 100 - distance * 18))
        matches.append({
            **view, "similarity": round(similarity, 1),
            "after_ret": round(after, 2), "max_up_after": round(max_up, 2),
            "max_down_after": round(max_down, 2),
        })
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    top = matches[:5]
    valid = [x for x in top if x["similarity"] >= 60]
    if not current_is_today:
        status = "本日9:00開始待ち"
        bias = "判定保留"
        valid = []
    elif len(current) < 4:
        status = "9:15まで判定保留"
        bias = "判定保留"
    elif len(valid) < 3:
        status = "類似度不足"
        bias = "見送り"
    else:
        status = "類似日あり"
        up_prob = sum(x["after_ret"] > 0 for x in valid) / len(valid) * 100
        bias = "上方向優位" if up_prob >= 65 else "下方向優位" if up_prob <= 35 else "レンジ優位"
    up_prob = (sum(x["after_ret"] > 0 for x in valid) / len(valid) * 100) if valid else None
    current_view = day_view(current_date, current)
    output = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": "Yahoo Finance 285A.T 5分足（取得可能な直近60日）",
        "calendar": views[-25:], "current": current_view,
        "current_is_today": current_is_today,
        "observed_bars": observed, "matches": top,
        "prediction": {
            "status": status, "bias": bias,
            "up_probability": round(up_prob, 1) if up_prob is not None else None,
            "expected_after_ret": round(float(np.mean([x["after_ret"] for x in valid])), 2) if valid else None,
            "expected_max_up": round(float(np.mean([x["max_up_after"] for x in valid])), 2) if valid else None,
            "expected_max_down": round(float(np.mean([x["max_down_after"] for x in valid])), 2) if valid else None,
            "sample": len(valid),
        },
        "rule": "9:15までは判定保留。類似度60%以上が3日未満なら見送り。OR15・VWAP・EMA9/20・出来高の4/5一致が優先。",
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
