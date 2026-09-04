#!/usr/bin/env python3
"""Five-minute verified tape for Kioxia and the two TOP5 lists."""

import json
import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from update import fetch_secondary_quotes, price_tick


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data.json"
OUT = ROOT / "live_focus.json"
KIOXIA = ROOT / "kioxia_5m_calendar.json"
JST = ZoneInfo("Asia/Tokyo")


def trading_times(count):
    """Return TSE five-minute bar labels, excluding the lunch recess."""
    labels = []
    for hour, start, end in ((9, 0, 60), (10, 0, 60), (11, 0, 30),
                             (12, 30, 60), (13, 0, 60), (14, 0, 60),
                             (15, 0, 30)):
        minute = start
        while minute < end:
            labels.append(f"{hour:02d}:{minute:02d}")
            minute += 5
    return labels[:count]


def kioxia_forecast(now):
    try:
        payload = json.loads(KIOXIA.read_text(encoding="utf-8"))
    except Exception:
        return {"forecast_verified": False, "forecast_status": "予測データ未取得"}
    best = payload.get("best_match") or {}
    path = [float(x) for x in best.get("path") or []]
    current_day = payload.get("analysis_date") == now.date().isoformat()
    usable = bool(current_day and len(path) >= 6 and best.get("similarity") is not None)
    labels = trading_times(len(path))
    return {
        "forecast_verified": usable,
        "forecast_status": "本日予測" if usable else "予測日不一致・売買利用禁止",
        "forecast_date": payload.get("analysis_date"),
        "analog_date": best.get("date"),
        "analog_similarity": best.get("similarity"),
        "forecast_path": path if usable else [],
        "forecast_times": labels if usable else [],
        "forecast_bias": (payload.get("prediction") or {}).get("bias"),
        "forecast_tradable": bool((payload.get("decision") or {}).get("tradable")),
    }


def next_attention(labels, path, observed, now):
    windows = [("09:00", "09:15", "寄り直後・OR15形成"),
               ("11:25", "11:30", "前引け注文"),
               ("12:30", "12:45", "後場寄り"),
               ("14:25", "14:35", "大口注文・方向再判定"),
               ("15:15", "15:30", "大引け需給")]
    # Add forecast turning points only when the expected swing is material.
    for i in range(max(2, observed + 1), len(path) - 2):
        left, mid, right = path[i - 2], path[i], path[i + 2]
        if (mid - left) * (right - mid) < 0 and max(abs(mid - left), abs(right - mid)) >= .25:
            stamp = labels[i]
            hh, mm = map(int, stamp.split(":"))
            start_min = max(9 * 60, hh * 60 + mm - 5)
            end_min = min(15 * 60 + 30, hh * 60 + mm + 5)
            kind = "予測ピーク" if mid > left else "予測ボトム"
            windows.append((f"{start_min//60:02d}:{start_min%60:02d}",
                            f"{end_min//60:02d}:{end_min%60:02d}", kind))
    windows.sort()
    current = now.strftime("%H:%M")
    for start, end, reason in windows:
        if end >= current:
            state = "注意時間中" if start <= current <= end else "次の注意時間"
            return {"attention_state": state, "attention_start": start,
                    "attention_end": end, "attention_reason": reason}
    return {"attention_state": "本日終了", "attention_start": None,
            "attention_end": None, "attention_reason": "大引け後"}


def compare_kioxia(actual, forecast, indicators, now):
    result = {
        "monitor_status": "開始待ち", "actual_time": None,
        "forecast_time": None, "actual_return": None,
        "forecast_return": None, "deviation_pct": None,
        "path_mae_pct": None, "path_fit": None,
        "expected_next": "判定待ち", "trade_signal": "見送り",
        "signal_reason": "9:15以降にOR15と実績を確認",
        "entry_price": None, "stop_price": None, "entry_order": None,
    }
    path = forecast.get("forecast_path") or []
    labels = forecast.get("forecast_times") or []
    if not forecast.get("forecast_verified") or not path:
        result.update({"monitor_status": "予測停止", "trade_signal": "売買禁止",
                       "signal_reason": forecast.get("forecast_status")})
        return {**result, **next_attention(labels, path, 0, now)}
    if not actual:
        result.update({"forecast_time": labels[0] if labels else "09:00",
                       "forecast_return": path[0] if path else None})
        return {**result, **next_attention(labels, path, 0, now)}
    observed = min(len(actual), len(path))
    base = float(actual[0]["o"])
    actual_path = [(float(x["c"]) / base - 1) * 100 for x in actual[:observed]]
    expected = path[:observed]
    deviation = actual_path[-1] - expected[-1]
    mae = sum(abs(a - b) for a, b in zip(actual_path, expected)) / observed
    fit = max(0.0, min(100.0, 100.0 - mae * 22.0))
    idx = observed - 1
    look = min(len(path) - 1, idx + 3)
    next_delta = path[look] - path[idx]
    expected_next = "上向き" if next_delta >= .12 else "下向き" if next_delta <= -.12 else "横ばい"
    status = "予測内" if abs(deviation) <= .45 and mae <= .55 else "差異拡大" if abs(deviation) <= .9 and mae <= 1.0 else "予測崩れ"
    result.update({
        "monitor_status": status,
        "actual_time": actual[idx]["t"], "forecast_time": labels[idx],
        "actual_return": round(actual_path[-1], 3),
        "forecast_return": round(expected[-1], 3),
        "deviation_pct": round(deviation, 3), "path_mae_pct": round(mae, 3),
        "path_fit": round(fit, 1), "expected_next": expected_next,
        "observed_bars": observed,
    })
    needed = ("vwap", "ema9", "ema20", "or15_high", "or15_low")
    if not forecast.get("forecast_tradable"):
        result["signal_reason"] = "類似日合意度不足・予測単独では見送り"
    elif observed < 4 or not all(indicators.get(x) is not None for x in needed):
        result["signal_reason"] = "OR15確定と4本以上の実績を待つ"
    elif status == "予測崩れ":
        result["signal_reason"] = "予測と実績の差が許容幅を超過"
    else:
        price = float(actual[idx]["c"])
        vols = [float(x.get("v") or 0) for x in actual]
        volume_ok = len(vols) < 7 or vols[-1] >= (sum(vols[-7:-1]) / max(1, len(vols[-7:-1]))) * .8
        long_ok = (price > indicators["vwap"] and price > indicators["or15_high"]
                   and indicators["ema9"] > indicators["ema20"] and expected_next != "下向き" and volume_ok)
        short_ok = (price < indicators["vwap"] and price < indicators["or15_low"]
                    and indicators["ema9"] < indicators["ema20"] and expected_next != "上向き" and volume_ok)
        if long_ok:
            tick = price_tick(price)
            entry = math.ceil(float(actual[idx]["h"]) / tick) * tick + tick
            stop = math.floor(float(actual[idx]["l"]) / tick) * tick - tick
            result.update({"trade_signal": "押し目買い候補",
                           "signal_reason": "OR15上抜け・VWAP上・EMA上向き・予測方向一致",
                           "entry_price": round(entry, 3), "stop_price": round(stop, 3),
                           "entry_order": "逆指値買い"})
        elif short_ok:
            tick = price_tick(price)
            entry = math.floor(float(actual[idx]["l"]) / tick) * tick - tick
            stop = math.ceil(float(actual[idx]["h"]) / tick) * tick + tick
            result.update({"trade_signal": "戻り売り候補",
                           "signal_reason": "OR15下抜け・VWAP下・EMA下向き・予測方向一致",
                           "entry_price": round(entry, 3), "stop_price": round(stop, 3),
                           "entry_order": "逆指値売り"})
        else:
            result["signal_reason"] = "価格・VWAP・EMA・予測方向が未一致"
    return {**result, **next_attention(labels, path, observed, now)}


def frame_for(raw, ticker):
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        for level in range(raw.columns.nlevels):
            if ticker in raw.columns.get_level_values(level):
                return raw.xs(ticker, axis=1, level=level).dropna(how="all")
        return pd.DataFrame()
    return raw.dropna(how="all")


def iso_jst(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return stamp.tz_convert(JST)


def main():
    now = datetime.now(JST)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    names = {}
    for item in data.get("precision_top5", []):
        names[item.get("ticker")] = item.get("name")
    for item in (data.get("strong_yen_top5") or {}).get("candidates", []):
        names[item.get("ticker")] = item.get("name")
    names["285A.T"] = "キオクシアHD（285A）"
    names = {k: v for k, v in names.items() if k and v}
    tickers = list(names)

    try:
        raw = yf.download(
            tickers, period="1d", interval="5m", auto_adjust=False,
            progress=False, threads=True, timeout=20, group_by="column",
        )
    except Exception:
        raw = pd.DataFrame()
    secondary = fetch_secondary_quotes(tickers, workers=min(8, len(tickers)))
    rows = {}
    kio_forecast = kioxia_forecast(now)
    for ticker, name in names.items():
        code = ticker.split(".")[0]
        shown = re.search(r"（([0-9A-Z]{3,5})）$", name)
        sec = secondary.get(ticker, {})
        frame = frame_for(raw, ticker)
        chart = []
        session_chart = []
        indicators = {}
        last_stamp = None
        primary_price = None
        if not frame.empty and "Close" in frame:
            frame = frame.dropna(subset=["Close"])
            if not frame.empty:
                last_stamp = iso_jst(frame.index[-1])
                primary_price = float(frame["Close"].iloc[-1])
                for stamp, bar in frame.tail(78).iterrows():
                    chart.append({
                        "t": iso_jst(stamp).strftime("%H:%M"),
                        "o": round(float(bar["Open"]), 3),
                        "h": round(float(bar["High"]), 3),
                        "l": round(float(bar["Low"]), 3),
                        "c": round(float(bar["Close"]), 3),
                        "v": round(float(bar.get("Volume") or 0)),
                    })
                work = frame.copy()
                close = work["Close"].astype(float)
                volume = work["Volume"].fillna(0).astype(float)
                typical = (
                    work["High"].astype(float)
                    + work["Low"].astype(float)
                    + close
                ) / 3
                cumulative_volume = volume.cumsum()
                vwap_series = (typical * volume).cumsum() / cumulative_volume.replace(0, math.nan)
                session = work[work.index.map(lambda value: iso_jst(value).date() == now.date())]
                session = session[session.index.map(lambda value: "09:00" <= iso_jst(value).strftime("%H:%M") <= "15:30")]
                for stamp, bar in session.iterrows():
                    session_chart.append({
                        "t": iso_jst(stamp).strftime("%H:%M"),
                        "o": round(float(bar["Open"]), 3),
                        "h": round(float(bar["High"]), 3),
                        "l": round(float(bar["Low"]), 3),
                        "c": round(float(bar["Close"]), 3),
                        "v": round(float(bar.get("Volume") or 0)),
                    })
                or15 = session.head(3)
                indicators = {
                    "vwap": round(float(vwap_series.iloc[-1]), 3) if not pd.isna(vwap_series.iloc[-1]) else None,
                    "ema9": round(float(close.ewm(span=9, adjust=False).mean().iloc[-1]), 3),
                    "ema20": round(float(close.ewm(span=20, adjust=False).mean().iloc[-1]), 3),
                    "or15_high": round(float(or15["High"].max()), 3) if len(or15) == 3 else None,
                    "or15_low": round(float(or15["Low"].min()), 3) if len(or15) == 3 else None,
                }
        secondary_price = sec.get("price") if sec.get("ok") else None
        tolerance = max(price_tick(secondary_price or primary_price or 1) * 2, (secondary_price or 0) * .002)
        prices_match = (
            primary_price is not None and secondary_price is not None
            and math.isclose(primary_price, float(secondary_price), rel_tol=0, abs_tol=tolerance)
        )
        age_minutes = (
            round((now - last_stamp.to_pydatetime()).total_seconds() / 60, 1)
            if last_stamp is not None else None
        )
        in_session = (now.hour, now.minute) >= (9, 0) and (now.hour, now.minute) <= (15, 30)
        fresh = age_minutes is not None and (age_minutes <= 12 if in_session else age_minutes <= 1080)
        verified = bool(
            shown and shown.group(1) == code and sec.get("code") == code
            and sec.get("data_date") == now.date().isoformat()
            and prices_match and fresh
        )
        signal = "判定待ち"
        if verified and code == "285A" and all(
            indicators.get(key) is not None
            for key in ("vwap", "ema9", "ema20", "or15_high", "or15_low")
        ):
            if primary_price > indicators["or15_high"] and primary_price > indicators["vwap"] and indicators["ema9"] > indicators["ema20"]:
                signal = "OR15上抜け・押し目待ち"
            elif primary_price < indicators["or15_low"] and primary_price < indicators["vwap"] and indicators["ema9"] < indicators["ema20"]:
                signal = "OR15下抜け・戻り待ち"
            else:
                signal = "OR15内・往復警戒"
        monitor = {}
        if code == "285A":
            monitor = compare_kioxia(session_chart, kio_forecast, indicators, now)
            if verified:
                signal = monitor["trade_signal"]
            monitor["signal_key"] = "|".join(str(monitor.get(x) or "") for x in (
                "trade_signal", "monitor_status", "attention_state", "attention_start"
            ))
            attention = (f"{monitor.get('attention_start')}から{monitor.get('attention_end')}、{monitor.get('attention_reason')}"
                         if monitor.get("attention_start") else monitor.get("attention_reason"))
            fit_spoken = (f"{monitor.get('path_fit')}パーセント"
                          if monitor.get("path_fit") is not None else "未算出")
            monitor["voice_message"] = (
                f"キオクシア、{monitor.get('trade_signal')}。{monitor.get('signal_reason')}。"
                + (f"発動価格{monitor.get('entry_price')}円。" if monitor.get("entry_price") else "")
                + f"予測一致度{fit_spoken}。{attention}。"
            )
        rows[code] = {
            "name": name, "ticker": ticker, "price": secondary_price,
            "primary_price": primary_price, "quote_time": last_stamp.isoformat() if last_stamp is not None else None,
            "age_minutes": age_minutes, "verified": verified,
            "status": "リアルタイム照合済み" if verified else "更新停止・売買禁止",
            "chart": chart if verified else [],
            "signal": signal if verified else "更新停止・売買禁止",
            **(indicators if verified else {}),
            **(kio_forecast if code == "285A" else {}),
            **(monitor if code == "285A" else {}),
        }
    verified_count = sum(x["verified"] for x in rows.values())
    output = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "refresh_seconds": 60, "backend_interval_minutes": 5,
        "verified_count": verified_count, "expected_count": len(rows),
        "status": "稼働" if verified_count == len(rows) and rows else "一部停止",
        "rows": rows,
        "rule": "Yahoo 5分足と野村/QUICK現在値、コード、取引日、鮮度が一致した銘柄だけ更新。キオクシアは予測差・OR15・VWAP・EMA・出来高一致時だけ条件付きサイン。",
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
