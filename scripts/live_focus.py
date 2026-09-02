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
JST = ZoneInfo("Asia/Tokyo")


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
    for ticker, name in names.items():
        code = ticker.split(".")[0]
        shown = re.search(r"（([0-9A-Z]{3,5})）$", name)
        sec = secondary.get(ticker, {})
        frame = frame_for(raw, ticker)
        chart = []
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
        rows[code] = {
            "name": name, "ticker": ticker, "price": secondary_price,
            "primary_price": primary_price, "quote_time": last_stamp.isoformat() if last_stamp is not None else None,
            "age_minutes": age_minutes, "verified": verified,
            "status": "リアルタイム照合済み" if verified else "更新停止・売買禁止",
            "chart": chart if verified else [],
            "signal": signal if verified else "更新停止・売買禁止",
            **(indicators if verified else {}),
        }
    verified_count = sum(x["verified"] for x in rows.values())
    output = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "refresh_seconds": 60, "backend_interval_minutes": 5,
        "verified_count": verified_count, "expected_count": len(rows),
        "status": "稼働" if verified_count == len(rows) and rows else "一部停止",
        "rows": rows,
        "rule": "Yahoo 5分足と野村/QUICK現在値、コード、取引日、鮮度が一致した銘柄だけ更新。",
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
