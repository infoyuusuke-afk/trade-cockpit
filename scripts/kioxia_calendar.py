"""Kioxia 5-minute calendar and nearest historical intraday pattern search."""
from __future__ import annotations

import json
import math
import html
import re
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kioxia_5m_calendar.json"
CREDIT = ROOT / "credit_supply.json"
DATA = ROOT / "data.json"
JST = ZoneInfo("Asia/Tokyo")
US_TICKERS = {"sndk": "SNDK", "mu": "MU", "sox": "^SOX", "nasdaq": "^IXIC"}
US_LABELS = {"sndk": "SanDisk", "mu": "Micron", "sox": "SOX", "nasdaq": "NASDAQ"}
UA = "Mozilla/5.0 (compatible; TradeCockpit/1.0; +https://infoyuusuke-afk.github.io/trade-cockpit/)"
PAGE_PAYLOADS = {}


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


def yahoo_embedded_payload(symbol, endpoint_fragment, page="history"):
    """Read Yahoo's public page-embedded response when the chart API is rate limited."""
    cache_key = (symbol, page)
    if cache_key not in PAGE_PAYLOADS:
        quoted = urllib.parse.quote(symbol, safe="")
        url = f"https://finance.yahoo.com/quote/{quoted}/{page}/"
        request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
        with urllib.request.urlopen(request, timeout=45) as response:
            source = response.read().decode("utf-8", "ignore")
        pattern = re.compile(r'<script[^>]+data-sveltekit-fetched[^>]*>(.*?)</script>', re.S)
        decoded = []
        for raw in pattern.findall(source):
            try:
                wrapper = json.loads(html.unescape(raw))
                body = wrapper.get("body", "")
                decoded.append((raw, body, json.loads(body)))
            except Exception:
                continue
        PAGE_PAYLOADS[cache_key] = decoded
    for raw, body, payload in PAGE_PAYLOADS[cache_key]:
        if endpoint_fragment in body or endpoint_fragment in raw:
            return payload
    return None


def yahoo_daily_html(symbol):
    payload = yahoo_embedded_payload(symbol, '"chart"', "history") or {}
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        return pd.Series(dtype=float)
    stamps = result.get("timestamp") or []
    quotes = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    if not stamps or len(stamps) != len(quotes):
        return pd.Series(dtype=float)
    return pd.Series(quotes, index=pd.to_datetime(stamps, unit="s", utc=True)).dropna().astype(float)


def yahoo_latest_change(symbol):
    payload = yahoo_embedded_payload(symbol, '"quoteSummary"', "history") or {}
    result = ((payload.get("quoteSummary") or {}).get("result") or [None])[0]
    price = (result or {}).get("price") or {}
    if price.get("symbol") != symbol:
        return None
    value = (price.get("regularMarketChangePercent") or {}).get("raw")
    stamp = price.get("regularMarketTime")
    if value is None or not stamp:
        return None
    date = str(pd.to_datetime(stamp, unit="s", utc=True).tz_convert("America/New_York").date())
    return date, float(value) * 100


def yahoo_intraday_html(symbol):
    """Fallback current 5-minute closes. Volume is deliberately left zero, never estimated."""
    payload = yahoo_embedded_payload(symbol, '"spark"', "chart") or {}
    responses = ((payload.get("spark") or {}).get("result") or [])
    if not responses:
        return pd.DataFrame()
    response = (responses[0].get("response") or [None])[0]
    if not response:
        return pd.DataFrame()
    stamps = response.get("timestamp") or []
    closes = (((response.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    if not stamps or len(stamps) != len(closes):
        return pd.DataFrame()
    close = pd.Series(closes, index=pd.to_datetime(stamps, unit="s", utc=True), dtype=float).dropna()
    frame = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 0.0})
    return frame


def stored_sessions():
    """Recover normalized historical paths only; no missing OHLC or volume is invented."""
    try:
        payload = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return []
    sessions = []
    for row in payload.get("calendar", []):
        path = row.get("path") or []
        if len(path) < 3:
            continue
        close = pd.Series([100.0 * (1 + float(value) / 100) for value in path])
        volume = pd.Series(row.get("volume_path") or [0.0] * len(close)).reindex(range(len(close))).fillna(0.0)
        frame = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": volume})
        sessions.append((row["date"], frame))
    return sessions


def stored_views():
    try:
        payload = json.loads(OUT.read_text(encoding="utf-8"))
        return {row["date"]: row for row in payload.get("calendar", []) if row.get("date")}
    except Exception:
        return {}


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


def us_market_history():
    """Return completed US-session percentage changes keyed by US date."""
    tickers = list(US_TICKERS.values())
    raw = yf.download(tickers, period="120d", interval="1d", auto_adjust=False,
                      progress=False, threads=True, timeout=45)
    result = {}
    for key, ticker in US_TICKERS.items():
        try:
            close = raw["Close"][ticker] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
            pct = close.dropna().astype(float).pct_change() * 100
            for stamp, value in pct.dropna().items():
                result.setdefault(str(pd.Timestamp(stamp).date()), {})[key] = round(float(value), 3)
        except Exception:
            continue
    # Yahoo occasionally throttles its JSON chart endpoint. Its public quote page
    # embeds the same completed daily series, so use it only for missing symbols.
    for key, ticker in US_TICKERS.items():
        if any(key in values for values in result.values()):
            continue
        try:
            pct = yahoo_daily_html(ticker).pct_change() * 100
            for stamp, value in pct.dropna().items():
                result.setdefault(str(pd.Timestamp(stamp).date()), {})[key] = round(float(value), 3)
        except Exception as exc:
            print(f"{ticker} 公開ページ履歴取得失敗: {exc}")
    # The history widget can omit the immediately preceding session for an index.
    # QuoteSummary provides the exchange-calculated percentage, so it wins for the latest date.
    for key, ticker in US_TICKERS.items():
        try:
            latest = yahoo_latest_change(ticker)
            if latest:
                date, value = latest
                result.setdefault(date, {})[key] = round(value, 3)
        except Exception as exc:
            print(f"{ticker} 最新騰落率取得失敗: {exc}")
    return result


def prior_us_context(japan_date, history):
    eligible = [date for date in history if date < japan_date and len(history[date]) >= 3]
    if not eligible:
        return None
    date = max(eligible)
    values = history[date]
    return {
        "date": date,
        "values": values,
        "labels": {key: US_LABELS[key] for key in values},
    }


def market_similarity(current, past):
    if not current or not past:
        return None
    scales = {"sndk": 4.0, "mu": 3.0, "sox": 2.0, "nasdaq": 1.5}
    common = [key for key in scales if key in current["values"] and key in past["values"]]
    if len(common) < 3:
        return None
    distance = math.sqrt(np.mean([
        ((current["values"][key] - past["values"][key]) / scales[key]) ** 2
        for key in common
    ]))
    return max(0.0, min(100.0, 100.0 - distance * 18.0))


def supply_data():
    try:
        payload = json.loads(CREDIT.read_text(encoding="utf-8"))
        stock = payload.get("stocks", {}).get("285A", {})
        return stock if stock.get("verified") else {}
    except Exception:
        return {}


def supply_at(date, stock):
    rows = [x for x in stock.get("history", []) if x.get("date", "") <= date]
    return sorted(rows, key=lambda x: x["date"])[-1] if rows else None


def supply_similarity(current, past):
    if not current or not past:
        return None
    phase_score = 100 if current.get("phase") == past.get("phase") else 78
    cur_ratio, old_ratio = current.get("ratio"), past.get("ratio")
    if cur_ratio and old_ratio:
        ratio_score = max(0, 100 - abs(math.log(cur_ratio / old_ratio)) * 45)
        return phase_score * .55 + ratio_score * .45
    return phase_score


def gap_bucket(value):
    if value <= -5: return "GD 5%以上"
    if value <= -3: return "GD 3–5%"
    if value <= -1: return "GD 1–3%"
    if value < 1: return "±1%以内"
    if value < 3: return "GU 1–3%"
    if value < 5: return "GU 3–5%"
    return "GU 5%以上"


def gap_studies(sessions):
    """Describe actual post-gap behavior; never manufacture a rule from tiny samples."""
    groups = {}
    for i in range(1, len(sessions)):
        date, day = sessions[i]
        prev_close = float(sessions[i - 1][1]["Close"].iloc[-1])
        open_ = float(day["Open"].iloc[0])
        if prev_close <= 0 or open_ <= 0:
            continue
        gap = (open_ / prev_close - 1) * 100
        first = day.iloc[:min(4, len(day))]
        or_high, or_low = float(first["High"].max()), float(first["Low"].min())
        close = float(day["Close"].iloc[-1])
        filled = (gap > 0 and float(day["Low"].min()) <= prev_close) or (gap < 0 and float(day["High"].max()) >= prev_close)
        groups.setdefault(gap_bucket(gap), []).append({
            "date": date, "gap": gap, "or15_ret": (float(first["Close"].iloc[-1]) / open_ - 1) * 100,
            "day_ret": (close / open_ - 1) * 100, "max_up": (float(day["High"].max()) / open_ - 1) * 100,
            "max_down": (float(day["Low"].min()) / open_ - 1) * 100, "gap_fill": filled,
            "or15_range": (or_high / or_low - 1) * 100 if or_low else 0,
        })
    order = ["GD 5%以上", "GD 3–5%", "GD 1–3%", "±1%以内", "GU 1–3%", "GU 3–5%", "GU 5%以上"]
    result = []
    for label in order:
        rows = groups.get(label, [])
        sample = len(rows)
        if not rows:
            result.append({"bucket": label, "sample": 0, "usable": False})
            continue
        result.append({
            "bucket": label, "sample": sample, "usable": sample >= 3,
            "or15_up_rate": round(sum(x["or15_ret"] > 0 for x in rows) / sample * 100, 1),
            "close_up_rate": round(sum(x["day_ret"] > 0 for x in rows) / sample * 100, 1),
            "gap_fill_rate": round(sum(x["gap_fill"] for x in rows) / sample * 100, 1),
            "median_day_ret": round(float(np.median([x["day_ret"] for x in rows])), 2),
            "median_max_up": round(float(np.median([x["max_up"] for x in rows])), 2),
            "median_max_down": round(float(np.median([x["max_down"] for x in rows])), 2),
            "median_or15_range": round(float(np.median([x["or15_range"] for x in rows])), 2),
        })
    return result


def daily_gap_studies():
    """Use identity/price-gated daily OHLC; OR15 is deliberately not inferred."""
    try:
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        row = (payload.get("stocks") or {}).get("キオクシアHD（285A）") or {}
        if not row.get("quote_verified") or not row.get("identity_verified") or row.get("ticker") != "285A.T":
            return []
        chart = row.get("chart") or []
        groups = {}
        for i in range(1, len(chart)):
            prev, bar = chart[i - 1], chart[i]
            prev_close, open_ = float(prev["c"]), float(bar["o"])
            gap = (open_ / prev_close - 1) * 100
            groups.setdefault(gap_bucket(gap), []).append({
                "day_ret": (float(bar["c"]) / open_ - 1) * 100,
                "max_up": (float(bar["h"]) / open_ - 1) * 100,
                "max_down": (float(bar["l"]) / open_ - 1) * 100,
                "gap_fill": (gap > 0 and float(bar["l"]) <= prev_close) or (gap < 0 and float(bar["h"]) >= prev_close),
            })
        order = ["GD 5%以上", "GD 3–5%", "GD 1–3%", "±1%以内", "GU 1–3%", "GU 3–5%", "GU 5%以上"]
        out = []
        for label in order:
            rows = groups.get(label, [])
            n = len(rows)
            out.append({"bucket": label, "sample": n, "usable": n >= 3, "source": "検証済み日足OHLC",
                        **({"close_up_rate": round(sum(x["day_ret"] > 0 for x in rows) / n * 100, 1),
                            "gap_fill_rate": round(sum(x["gap_fill"] for x in rows) / n * 100, 1),
                            "median_day_ret": round(float(np.median([x["day_ret"] for x in rows])), 2),
                            "median_max_up": round(float(np.median([x["max_up"] for x in rows])), 2),
                            "median_max_down": round(float(np.median([x["max_down"] for x in rows])), 2)} if n else {})})
        return out
    except Exception:
        return []


def turning_points(path):
    labels = []
    if len(path) < 5:
        return labels
    # 78 five-minute bars across the split Tokyo session; this is display timing,
    # not a promise that the turn will occur.
    minutes = list(range(9 * 60, 11 * 60 + 31, 5)) + list(range(12 * 60 + 30, 15 * 60 + 31, 5))
    for i in range(2, len(path) - 2):
        left, mid, right = path[i - 2], path[i], path[i + 2]
        if (mid - left) * (right - mid) < 0 and max(abs(mid - left), abs(right - mid)) >= .25:
            m = minutes[min(i, len(minutes) - 1)]
            labels.append({"time": f"{m//60:02d}:{m%60:02d}", "kind": "予測ピーク" if mid > left else "予測ボトム", "ret": round(float(mid), 2)})
    return labels[:6]


def ma_playbook():
    return {
        "note": "EMA9/20は日数ではなく5分足の9本・20本。日足移動平均とは分けて判定。",
        "long_first_pullback": "EMA9>EMA20、VWAP上、EMA9上向き。EMA9へ下ヒゲ接触後、5分足終値で回復し、その足の高値+1ティックで発動。",
        "long_deep_pullback": "EMA20またはVWAPまでの押し。下ヒゲ回収と出来高減速を確認し、反発足高値+1ティック。OR15安値割れなら禁止。",
        "short_first_return": "EMA9<EMA20、VWAP下、EMA9下向き。EMA9へ上ヒゲ接触後、5分足終値で拒否し、その足の安値-1ティックで発動。",
        "short_deep_return": "EMA20またはVWAPまでの戻り。上ヒゲ拒否と買い出来高失速後、反落足安値-1ティック。OR15高値超えなら禁止。",
        "whipsaw_guard": "OR15内、EMA9/20交差、VWAPを2本連続往復、長い上下ヒゲは往復ピンタ帯。新規注文を置かない。",
    }


def main():
    now = datetime.now(JST)
    # There is no Tokyo cash session on weekends. Preserve Friday's verified
    # prediction instead of relabeling it as a Saturday forecast.
    if now.weekday() >= 5 and OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            previous["gap_studies"] = daily_gap_studies()
            previous["forecast_turns"] = turning_points(((previous.get("best_match") or {}).get("path") or []))
            previous["ma_playbook"] = ma_playbook()
            previous["weekend_status"] = "休場日：直前営業日の検証済み予測を保持。次営業日版は当日8:00に更新。"
            OUT.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return
        except Exception:
            pass
    intraday_source = "Yahoo Finance 285A.T 5分足"
    try:
        raw = yf.download("285A.T", period="60d", interval="5m", auto_adjust=False,
                          progress=False, threads=False, timeout=45)
        frame = flat(raw)
    except Exception as exc:
        print(f"キオクシア5分足API取得失敗。公開ページへ切替: {exc}")
        frame = pd.DataFrame()
    if frame.empty:
        try:
            frame = yahoo_intraday_html("285A.T")
            intraday_source = "Yahoo Finance公開ページ 285A.T 5分足終値（出来高判定なし）"
        except Exception as exc:
            print(f"キオクシア公開ページ取得失敗。前回正常取得足で再判定: {exc}")
            frame = pd.DataFrame()
    sessions = session_days(frame)
    if len(sessions) < 2:
        current_only = sessions[-1:] if sessions else []
        stored = stored_sessions()
        if current_only:
            current_date = current_only[0][0]
            sessions = [(date, day) for date, day in stored if date != current_date] + current_only
        elif stored:
            sessions = stored
            intraday_source = "前回正常取得の285A.T 5分足（API制限時保持）"
        if len(sessions) < 2:
            print("キオクシア5分足の比較可能日数が不足。前回値を保持")
            return
    prior_views = stored_views() if "前回正常取得" in intraday_source else {}
    views = [prior_views.get(date) or day_view(date, day) for date, day in sessions]
    current_date, current = sessions[-1]
    current_gap_pct = None
    if len(sessions) >= 2:
        previous_close = float(sessions[-2][1]["Close"].iloc[-1])
        current_gap_pct = round((float(current["Open"].iloc[0]) / previous_close - 1) * 100, 2) if previous_close else None
    today = datetime.now(JST).date().isoformat()
    current_is_today = current_date == today
    market_closed = current_is_today and datetime.now(JST).strftime("%H:%M") > "15:30"
    analysis_date = today if not current_is_today else current_date
    try:
        us_history = us_market_history()
    except Exception as exc:
        print(f"米国市場履歴取得失敗。5分足だけで判定: {exc}")
        us_history = {}
    current_market = prior_us_context(analysis_date, us_history)
    stock_supply = supply_data()
    current_supply = supply_at(analysis_date, stock_supply)
    # At most the available current bars; before 9:15 no direction prediction is issued.
    observed_cap = 61 if "出来高判定なし" in intraday_source else 78
    observed = min(len(current), observed_cap) if current_is_today else 0
    selection_mode = "米国市場＋信用需給（寄り前）" if not current_is_today else "5分足＋米国市場＋信用需給"
    matches = []
    for (date, past), view in zip(sessions[:-1], views[:-1]):
        path_similarity = None
        if observed:
            distance = match_distance(current, past, observed)
            if distance is None:
                continue
            path_similarity = max(0, min(100, 100 - distance * 18))
        past_market = prior_us_context(date, us_history)
        us_similarity = market_similarity(current_market, past_market)
        historical_supply = supply_at(date, stock_supply)
        credit_similarity = supply_similarity(current_supply, historical_supply)
        components = []
        if path_similarity is not None:
            components.append((path_similarity, .65))
        if us_similarity is not None:
            components.append((us_similarity, .25 if observed else .80))
        if credit_similarity is not None:
            components.append((credit_similarity, .10 if observed else .20))
        if not components:
            continue
        similarity = sum(value * weight for value, weight in components) / sum(weight for _, weight in components)
        at_match = float(past["Close"].iloc[observed - 1]) if observed else float(past["Open"].iloc[0])
        rest = past.iloc[max(observed - 1, 0):]
        final = float(past["Close"].iloc[-1])
        after = (final / at_match - 1) * 100
        max_up = (float(rest["High"].max()) / at_match - 1) * 100
        max_down = (float(rest["Low"].min()) / at_match - 1) * 100
        matches.append({
            **view, "similarity": round(similarity, 1),
            "after_ret": round(after, 2), "max_up_after": round(max_up, 2),
            "max_down_after": round(max_down, 2),
            "score_components": {
                "five_minute": round(path_similarity, 1) if path_similarity is not None else None,
                "us_market": round(us_similarity, 1) if us_similarity is not None else None,
                "credit_supply": round(credit_similarity, 1) if credit_similarity is not None else None,
            },
            "us_context": past_market,
            "supply_context": historical_supply,
        })
    matches.sort(key=lambda x: x["similarity"], reverse=True)
    top = matches[:5]
    valid = [x for x in top if x["similarity"] >= 60]
    total_similarity = sum(float(x["similarity"]) for x in valid)
    up_prob = (
        sum(float(x["similarity"]) for x in valid if x["after_ret"] > 0)
        / total_similarity * 100
        if total_similarity else None
    )
    weighted_after = (
        sum(float(x["after_ret"]) * float(x["similarity"]) for x in valid)
        / total_similarity if total_similarity else None
    )
    direction_agreement = max(up_prob or 0, 100 - (up_prob or 0)) if up_prob is not None else None
    return_dispersion = float(np.std([x["after_ret"] for x in valid])) if len(valid) >= 2 else None
    if not current_is_today:
        status = "寄り前・米国市場と信用需給から事前選定"
        if len(valid) < 3:
            bias = "事前類似度不足・見送り"
        else:
            bias = "上方向候補" if up_prob >= 65 else "下方向候補" if up_prob <= 35 else "レンジ候補"
    elif market_closed:
        status = "大引け後・当日照合完了"
        bias = "翌営業日の米国市場確定待ち"
    elif len(current) < 4:
        status = "9:15まで判定保留"
        bias = "判定保留"
    elif len(valid) < 3:
        status = "類似度不足"
        bias = "見送り"
    else:
        status = "類似日あり"
        bias = "上方向優位" if up_prob >= 65 else "下方向優位" if up_prob <= 35 else "レンジ優位"
    if market_closed:
        up_prob = None
    market_values = (current_market or {}).get("values", {})
    negative_us = sum(float(market_values.get(k) or 0) < 0 for k in ("sndk", "mu", "sox", "nasdaq"))
    credit_bad = bool(current_supply and (
        current_supply.get("phase") == "悪化"
        or float(current_supply.get("ratio") or 0) >= 10
    ))
    if not current_is_today and negative_us == 4 and credit_bad:
        risk_overlay = {
            "status": "下方向リスク優勢",
            "action": "寄り買い禁止。OR15安値割れは戻り売り、VWAP回復・OR15高値突破で無効化",
        }
    else:
        risk_overlay = {
            "status": "方向確認待ち",
            "action": "OR15・VWAP・EMA9/20・出来高の4/5一致まで見送り",
        }
    low_confidence = (
        market_closed
        or len(valid) < 3
        or direction_agreement is None or direction_agreement < 65
        or return_dispersion is None or return_dispersion > 4.0
        or weighted_after is None or abs(weighted_after) < .30
    )
    decision = {
        "grade": "見送り" if low_confidence else "条件付き",
        "tradable": not low_confidence,
        "agreement": round(direction_agreement, 1) if direction_agreement is not None else None,
        "dispersion": round(return_dispersion, 2) if return_dispersion is not None else None,
        "reason": (
            "類似日間の方向または値幅が揃っていないため、予測だけで入らない"
            if low_confidence else
            "類似日が同方向へ収束。OR15・VWAP・出来高一致後だけ利用"
        ),
        "invalidate": "OR15とVWAPが予測方向と逆へ同時確定したら無効",
    }
    current_view = prior_views.get(current_date) or day_view(current_date, current)
    output = {
        "name": "キオクシアHD（285A）",
        "ticker": "285A.T",
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": intraday_source + "（取得可能な直近60日）",
        "calendar": views[-25:], "current": current_view,
        "current_is_today": current_is_today,
        "current_gap_pct": current_gap_pct if current_is_today else None,
        "analysis_date": analysis_date,
        "observed_bars": observed, "matches": top,
        "best_match": top[0] if top else None,
        "selection_mode": selection_mode,
        "market_context": current_market,
        "credit_context": current_supply,
        "prediction": {
            "status": status, "bias": bias,
            "up_probability": round(up_prob, 1) if up_prob is not None else None,
            "expected_after_ret": round(weighted_after, 2) if weighted_after is not None and not market_closed else None,
            "expected_max_up": round(float(np.mean([x["max_up_after"] for x in valid])), 2) if valid and not market_closed else None,
            "expected_max_down": round(float(np.mean([x["max_down_after"] for x in valid])), 2) if valid and not market_closed else None,
            "sample": len(valid),
        },
        "risk_overlay": risk_overlay,
        "decision": decision,
        "gap_studies": daily_gap_studies(),
        "forecast_turns": turning_points((top[0] if top else {}).get("path") or []),
        "ma_playbook": ma_playbook(),
        "rule": "寄り前は前夜のSanDisk・Micron・SOX・NASDAQと信用需給で事前類似日を選定。9:15以降は当日5分足を65%へ引き上げる。類似度60%以上が3日未満なら見送り。OR15・VWAP・EMA9/20・出来高の4/5一致が最終条件。",
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
