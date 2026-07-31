import json
import math
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
JPX_LIST_URL = (
    "https://www.jpx.co.jp/markets/statistics-equities/"
    "misc/tvdivq0000001vg2-att/data_j.xls"
)


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def load_universe():
    """JPX上場銘柄一覧を取得。失敗時は従来の監視リストを使う。"""
    try:
        req = Request(JPX_LIST_URL, headers={"User-Agent": "Mozilla/5.0 trade-cockpit"})
        raw = urlopen(req, timeout=45).read()
        frame = pd.read_excel(BytesIO(raw))
        code_col = next(c for c in frame.columns if "コード" in str(c))
        name_col = next(c for c in frame.columns if "銘柄名" in str(c))
        product_col = next((c for c in frame.columns if "市場・商品区分" in str(c)), None)
        rows = []
        for _, row in frame.iterrows():
            code = str(row[code_col]).replace(".0", "").strip()
            name = str(row[name_col]).strip()
            product = str(row[product_col]) if product_col else ""
            if not code or code == "nan" or not name or name == "nan":
                continue
            # ETF、REIT、優先出資証券などを除き、国内株式を中心に走査。
            if product_col and not any(x in product for x in ("プライム", "スタンダード", "グロース")):
                continue
            rows.append({"code": code, "ticker": f"{code}.T", "name": name})
        if rows:
            return rows, "JPX全市場"
    except Exception:
        pass

    config = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    rows = []
    for display_name, meta in config["stocks"].items():
        code = meta["ticker"].split(".")[0]
        name = display_name.rsplit("（", 1)[0]
        rows.append({"code": code, "ticker": meta["ticker"], "name": name})
    return rows, "固定監視リスト（JPX取得失敗）"


def one_frame(downloaded, ticker, only_one):
    try:
        if only_one:
            frame = downloaded.copy()
        elif isinstance(downloaded.columns, pd.MultiIndex):
            # yfinanceの版によって ticker が列の第0/第1階層になる。
            if ticker in downloaded.columns.get_level_values(0):
                frame = downloaded[ticker].copy()
            elif ticker in downloaded.columns.get_level_values(1):
                frame = downloaded.xs(ticker, axis=1, level=1).copy()
            else:
                return None
        else:
            return None
        frame.columns = [str(c).title() for c in frame.columns]
        return frame.dropna(subset=["Close"])
    except Exception:
        return None


def analyse(item, frame):
    if frame is None or len(frame) < 65:
        return None
    close_s = frame["Close"].astype(float)
    high_s = frame["High"].astype(float)
    low_s = frame["Low"].astype(float)
    open_s = frame["Open"].astype(float)
    volume_s = frame["Volume"].fillna(0).astype(float)

    close = finite(close_s.iloc[-1])
    high = finite(high_s.iloc[-1])
    low = finite(low_s.iloc[-1])
    open_ = finite(open_s.iloc[-1])
    volume = finite(volume_s.iloc[-1]) or 0
    if None in (close, high, low, open_) or close <= 0:
        return None

    ma5_s = close_s.rolling(5).mean()
    ma20_s = close_s.rolling(20).mean()
    ma60_s = close_s.rolling(60).mean()
    ma5, ma20, ma60 = map(finite, (ma5_s.iloc[-1], ma20_s.iloc[-1], ma60_s.iloc[-1]))
    if None in (ma5, ma20, ma60):
        return None

    tr = pd.concat([
        high_s - low_s,
        (high_s - close_s.shift()).abs(),
        (low_s - close_s.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = finite(tr.rolling(14).mean().iloc[-1])
    avg_volume = finite(volume_s.rolling(20).mean().iloc[-1]) or 0
    if not atr:
        return None

    ret20 = (close / float(close_s.iloc[-21]) - 1) * 100
    rvol = volume / avg_volume if avg_volume else 0
    turnover = close * volume
    atr_pct = atr / close * 100
    ma20_dist = (close / ma20 - 1) * 100
    ma5_dist = (close / ma5 - 1) * 100
    prior20 = float(high_s.iloc[-21:-1].max())
    prior252 = float(high_s.iloc[:-1].tail(252).max())

    basis = close_s.rolling(20).mean()
    dev = close_s.rolling(20).std(ddof=0) * 2
    upper = basis + dev
    lower = basis - dev
    width = ((upper - lower) / basis * 100).dropna()
    if len(width) < 2:
        return None
    previous_window = width.iloc[:-1].tail(120)
    previous_rank = float((previous_window <= width.iloc[-2]).mean() * 100)

    bull = close > open_
    volume_ok = rvol >= .90
    liquidity_ok = turnover >= 30_000_000
    overheat_ok = atr_pct <= 9 and ma20_dist <= 18
    trend_ok = close > ma20 and ma20 >= float(ma20_s.iloc[-2])

    ma5_setup = (
        ma5 > ma20 and ma5 > float(ma5_s.iloc[-2])
        and low <= ma5 * 1.02 and close >= ma5
        and ma5_dist <= 5 and ret20 >= 3 and bull
    )
    stable_setup = (
        close > ma20 > ma60 and ma20 > float(ma20_s.iloc[-6])
        and low <= ma20 * 1.01 and close >= ma20
        and atr_pct <= 5 and bull
    )
    bb_setup = (
        previous_rank <= 35 and close > float(upper.iloc[-1])
        and float(width.iloc[-1]) > float(width.iloc[-2])
        and float(upper.iloc[-1]) > float(upper.iloc[-2])
        and volume_ok and bull
    )
    high_setup = close > prior20 and close >= prior252 * .98 and volume_ok and bull

    base = (
        (15 if trend_ok else 0)
        + (10 if ma20 > ma60 else 0)
        + (15 if volume_ok else 7 if rvol >= .9 else 0)
        + (10 if liquidity_ok else 0)
        + (10 if atr_pct <= 5 else 5 if atr_pct <= 9 else 0)
        + (10 if ma20_dist <= 10 else 5 if ma20_dist <= 18 else 0)
    )
    choices = []
    if stable_setup:
        choices.append((min(100, base + 30), "安定押し目", ma20 - atr * .50))
    if ma5_setup:
        choices.append((min(100, base + 30), "5日線反発", ma5 - atr * .30))
    if bb_setup:
        choices.append((min(100, base + 35), "BB上方拡大", float(basis.iloc[-1])))
    if high_setup:
        choices.append((min(100, base + 35), "新高値更新", low - atr * .30))
    if not choices or not liquidity_ok or not overheat_ok:
        return None

    score, setup, stop = sorted(choices, reverse=True)[0]
    if score < 60:
        return None
    tick = 1 if close < 3000 else 5
    trigger = math.ceil((high + tick) / tick) * tick
    stop = math.floor(stop / tick) * tick
    risk = max(trigger - stop, tick)
    return {
        "code": item["code"], "ticker": item["ticker"],
        "name": f"{item['name']}（{item['code']}）",
        "setup": setup, "score": int(score),
        "close": round(close, 2), "trigger": round(trigger, 2),
        "stop": round(stop, 2),
        "target1": round((trigger + risk * 1.5) / tick) * tick,
        "target2": round((trigger + risk * 2.5) / tick) * tick,
        "ma5": round(ma5, 2), "rvol": round(rvol, 2),
        "ret20": round(ret20, 2), "atr_pct": round(atr_pct, 2),
        "signal_date": frame.index[-1].strftime("%Y-%m-%d"),
        "reason": f"{setup}／終値が主要移動平均線上／出来高比{rvol:.2f}倍",
        "event_risk": "決算・重要IR・海外指数急変を確認。決算7日以内は原則見送り。",
        "caution": "大幅GU時は飛び乗らず、寄り後の高値更新を再確認。",
    }


def analyse_short(item, frame):
    """翌日の安値割れで発動する持ち越しショート候補。"""
    if frame is None or len(frame) < 65:
        return None
    close_s = frame["Close"].astype(float)
    high_s = frame["High"].astype(float)
    low_s = frame["Low"].astype(float)
    open_s = frame["Open"].astype(float)
    volume_s = frame["Volume"].fillna(0).astype(float)
    close, high, low, open_ = map(finite, (
        close_s.iloc[-1], high_s.iloc[-1], low_s.iloc[-1], open_s.iloc[-1]
    ))
    if None in (close, high, low, open_) or close <= 0:
        return None
    ma5_s = close_s.rolling(5).mean()
    ma20_s = close_s.rolling(20).mean()
    ma60_s = close_s.rolling(60).mean()
    ma5, ma20, ma60 = map(finite, (ma5_s.iloc[-1], ma20_s.iloc[-1], ma60_s.iloc[-1]))
    if None in (ma5, ma20, ma60):
        return None
    tr = pd.concat([
        high_s - low_s,
        (high_s - close_s.shift()).abs(),
        (low_s - close_s.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = finite(tr.rolling(14).mean().iloc[-1])
    avg_volume = finite(volume_s.rolling(20).mean().iloc[-1]) or 0
    volume = finite(volume_s.iloc[-1]) or 0
    if not atr:
        return None
    ret5 = (close / float(close_s.iloc[-6]) - 1) * 100
    ret20 = (close / float(close_s.iloc[-21]) - 1) * 100
    rvol = volume / avg_volume if avg_volume else 0
    turnover = close * volume
    atr_pct = atr / close * 100
    from_ma20 = (close / ma20 - 1) * 100
    prior20_low = float(low_s.iloc[-21:-1].min())
    down_order = close < ma5 < ma20
    falling = ma5 < float(ma5_s.iloc[-2]) and ma20 < float(ma20_s.iloc[-6])
    bearish = close < open_
    low_break = close <= prior20_low or low < float(low_s.iloc[-2])
    rebound_failed = high >= ma5 * .98 and close < ma5
    liquid = turnover >= 300_000_000 and rvol >= .90
    not_oversold = ret5 > -12 and ret20 > -25 and from_ma20 > -18
    not_squeeze_prone = close >= 500 and atr_pct <= 8
    if not (down_order and falling and bearish and liquid and not_oversold and not_squeeze_prone
            and (low_break or rebound_failed)):
        return None
    score = (
        20 + 15
        + (10 if bearish else 0)
        + (15 if rvol >= 1.2 else 10)
        + (15 if turnover >= 3_000_000_000 else 10)
        + (15 if low_break else 8)
        + (10 if atr_pct <= 5 else 5)
    )
    score = min(100, score)
    if score < 70:
        return None
    tick = 1 if close < 3000 else 5
    trigger = math.floor((low - tick) / tick) * tick
    stop = math.ceil(max(high + atr * .30, ma5 + atr * .30) / tick) * tick
    risk = max(stop - trigger, tick)
    setup = "安値割れ" if low_break else "5日線戻り失敗"
    return {
        "code": item["code"], "ticker": item["ticker"],
        "name": f"{item['name']}（{item['code']}）",
        "setup": setup, "score": int(score),
        "close": round(close, 2), "trigger": round(trigger, 2),
        "stop": round(stop, 2),
        "target1": round((trigger - risk * 1.5) / tick) * tick,
        "target2": round((trigger - risk * 2.5) / tick) * tick,
        "ma5": round(ma5, 2), "rvol": round(rvol, 2),
        "ret20": round(ret20, 2), "atr_pct": round(atr_pct, 2),
        "signal_date": frame.index[-1].strftime("%Y-%m-%d"),
        "reason": f"{setup}／終値＜5日線＜20日線／出来高比{rvol:.2f}倍",
        "event_risk": "決算・上方修正・自社株買い・海外指数反発を確認。決算7日以内は原則見送り。",
        "caution": "貸借銘柄・在庫・逆日歩・空売り規制を楽天MS2で確認。大幅GDは追いかけない。",
    }


def resample_ohlcv(frame, rule):
    """日足から週足・月足を作る。未確定の当週・当月も最新行として残す。"""
    indexed = frame.copy()
    if not isinstance(indexed.index, pd.DatetimeIndex):
        indexed.index = pd.to_datetime(indexed.index)
    return indexed.resample(rule).agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }).dropna(subset=["Open", "High", "Low", "Close"])


def hammer_row(item, frame, timeframe):
    """陽線ハンマー＋移動平均線反発を週足・月足で判定する。"""
    rule = "W-FRI" if timeframe == "週足" else "ME"
    bars = resample_ohlcv(frame, rule)
    required = 22 if timeframe == "週足" else 13
    if len(bars) < required:
        return None

    bar = bars.iloc[-1]
    open_, high, low, close = map(float, (bar["Open"], bar["High"], bar["Low"], bar["Close"]))
    volume = float(bar["Volume"])
    body = max(close - open_, close * .002)
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)
    candle_range = max(high - low, close * .002)
    close_location = (close - low) / candle_range

    if timeframe == "週足":
        fast_len, slow_len = 10, 20
        provisional = pd.Timestamp(frame.index[-1]).weekday() < 4
    else:
        fast_len, slow_len = 6, 12
        last_date = pd.Timestamp(frame.index[-1])
        provisional = (last_date + pd.offsets.BMonthEnd(0)).date() != last_date.date()

    closes = bars["Close"].astype(float)
    fast = float(closes.rolling(fast_len).mean().iloc[-1])
    slow = float(closes.rolling(slow_len).mean().iloc[-1])
    avg_volume = float(bars["Volume"].astype(float).iloc[-7:-1].mean())
    volume_ratio = volume / avg_volume if avg_volume else 0
    turnover = close * volume

    touch_tolerance = .03 if timeframe == "月足" and provisional else .015
    touched = []
    if low <= fast * (1 + touch_tolerance) and close >= fast:
        touched.append(f"{fast_len}{'週' if timeframe == '週足' else '月'}線")
    if low <= slow * (1 + touch_tolerance) and close >= slow:
        touched.append(f"{slow_len}{'週' if timeframe == '週足' else '月'}線")

    strict_hammer = (
        close > open_
        and lower_wick >= body * 2.0
        and upper_wick <= body * .75
        and close_location >= .67
    )
    provisional_month_hammer = (
        timeframe == "月足" and provisional
        and close > open_
        and lower_wick >= body * 1.5
        and upper_wick <= body
        and close_location >= .60
    )
    bullish_hammer = strict_hammer or provisional_month_hammer
    liquidity_floor = 500_000_000 if timeframe == "週足" else 2_000_000_000
    if not bullish_hammer or not touched or turnover < liquidity_floor:
        return None

    score = 55
    score += 12 if lower_wick >= body * 3 else 8
    score += 10 if upper_wick <= body * .35 else 5
    score += 10 if volume_ratio >= 1.20 else 6 if volume_ratio >= .90 else 2
    score += 8 if close >= fast >= slow else 4 if close >= slow else 0
    score += 5 if len(touched) >= 2 else 2
    score = min(100, score)

    tick = 1 if close < 3000 else 5
    trigger = math.ceil((high + tick) / tick) * tick
    stop = math.floor((low - tick) / tick) * tick
    risk = max(trigger - stop, tick)
    return {
        "code": item["code"], "ticker": item["ticker"],
        "name": f"{item['name']}（{item['code']}）",
        "timeframe": timeframe,
        "status": (
            "暫定・準ハンマー" if provisional and not strict_hammer
            else "暫定" if provisional else "確定"
        ),
        "score": int(score),
        "close": round(close, 2),
        "trigger": round(trigger, 2),
        "stop": round(stop, 2),
        "target1": round((trigger + risk * 1.5) / tick) * tick,
        "target2": round((trigger + risk * 2.5) / tick) * tick,
        "ma_rebound": "・".join(touched),
        "lower_wick_ratio": round(lower_wick / body, 1),
        "upper_wick_ratio": round(upper_wick / body, 1),
        "volume_ratio": round(volume_ratio, 2),
        "signal_date": pd.Timestamp(frame.index[-1]).strftime("%Y-%m-%d"),
        "reason": (
            f"{timeframe}陽線ハンマー／下ヒゲ{lower_wick / body:.1f}倍／"
            f"{'・'.join(touched)}反発／出来高比{volume_ratio:.2f}倍"
        ),
        "caution": "高値＋1ティックを上抜くまで準備。月足・週足確定前に形が崩れた場合は除外。",
    }



def long_term_rebound_row(item, frame, setup_type):
    """長期上昇トレンドの50週線反発／日足200日線ハンマーを抽出する。"""
    if frame is None or len(frame) < 230:
        return None

    close_s = frame["Close"].astype(float)
    high_s = frame["High"].astype(float)
    low_s = frame["Low"].astype(float)
    open_s = frame["Open"].astype(float)
    volume_s = frame["Volume"].fillna(0).astype(float)
    close = float(close_s.iloc[-1])
    current_turnover = close * float(volume_s.iloc[-1])
    avg_daily_turnover = float((close_s * volume_s).tail(20).mean())
    if close < 100 or current_turnover < 300_000_000 or avg_daily_turnover < 500_000_000:
        return None

    if setup_type == "週足50週線反発":
        bars = resample_ohlcv(frame, "W-FRI")
        if len(bars) < 55:
            return None
        closes = bars["Close"].astype(float)
        ma_s = closes.rolling(50).mean()
        ma_value = float(ma_s.iloc[-1])
        ma_old = float(ma_s.iloc[-5])
        bar = bars.iloc[-1]
        open_, high, low, close = map(
            float, (bar["Open"], bar["High"], bar["Low"], bar["Close"])
        )
        volume = float(bar["Volume"])
        avg_volume = float(bars["Volume"].astype(float).iloc[-13:-1].mean())
        volume_ratio = volume / avg_volume if avg_volume else 0
        trend_return = (
            (close / float(closes.iloc[-27]) - 1) * 100
            if len(closes) >= 27 else 0
        )
        ma_slope = (ma_value / ma_old - 1) * 100 if ma_old else 0
        candle_range = max(high - low, close * .002)
        close_location = (close - low) / candle_range
        body = max(abs(close - open_), close * .002)
        lower_wick = min(open_, close) - low
        touched = low <= ma_value * 1.03 and high >= ma_value * .97
        reclaimed = close >= ma_value
        bullish_reaction = close > open_ or close_location >= .68
        trend_ok = ma_slope > 0 and trend_return >= 5
        if not (touched and reclaimed and bullish_reaction and trend_ok):
            return None
        candle = "陽線反発" if close > open_ else "下ヒゲ反発"
        score = 55
        score += 15 if ma_slope >= 2 else 10
        score += 12 if trend_return >= 20 else 8 if trend_return >= 10 else 4
        score += 10 if close_location >= .75 else 6
        score += 8 if volume_ratio >= 1.20 else 5 if volume_ratio >= .90 else 2
        score += 5 if lower_wick >= body * 1.5 else 2
        timeframe = "週足"
        ma_label = "50週線"
        provisional = pd.Timestamp(frame.index[-1]).weekday() < 4
        status = "暫定" if provisional else "確定"
    else:
        ma_s = close_s.rolling(200).mean()
        ma_value = float(ma_s.iloc[-1])
        ma_old = float(ma_s.iloc[-21])
        open_ = float(open_s.iloc[-1])
        high = float(high_s.iloc[-1])
        low = float(low_s.iloc[-1])
        close = float(close_s.iloc[-1])
        volume = float(volume_s.iloc[-1])
        avg_volume = float(volume_s.iloc[-21:-1].mean())
        volume_ratio = volume / avg_volume if avg_volume else 0
        trend_return = (
            (close / float(close_s.iloc[-127]) - 1) * 100
            if len(close_s) >= 127 else 0
        )
        ma_slope = (ma_value / ma_old - 1) * 100 if ma_old else 0
        body = max(abs(close - open_), close * .002)
        lower_wick = min(open_, close) - low
        upper_wick = high - max(open_, close)
        candle_range = max(high - low, close * .002)
        close_location = (close - low) / candle_range
        hammer = (
            close > open_
            and lower_wick >= body * 1.8
            and upper_wick <= body
            and close_location >= .65
        )
        touched = low <= ma_value * 1.02 and high >= ma_value * .98
        reclaimed = close >= ma_value
        trend_ok = ma_slope > 0 and trend_return >= 0
        if not (hammer and touched and reclaimed and trend_ok):
            return None
        candle = "陽線ハンマー"
        score = 58
        score += 15 if lower_wick >= body * 3 else 10
        score += 12 if ma_slope >= 2 else 8
        score += 10 if trend_return >= 20 else 6 if trend_return >= 8 else 3
        score += 8 if volume_ratio >= 1.20 else 5 if volume_ratio >= .90 else 2
        score += 5 if close_location >= .80 else 3
        timeframe = "日足"
        ma_label = "200日線"
        status = "確定"

    score = int(min(100, score))
    if score < 70:
        return None
    tick = 1 if close < 3000 else 5
    trigger = math.ceil((high + tick) / tick) * tick
    stop = math.floor((low - tick) / tick) * tick
    risk = max(trigger - stop, tick)
    return {
        "code": item["code"], "ticker": item["ticker"],
        "name": f"{item['name']}（{item['code']}）",
        "setup": setup_type, "timeframe": timeframe, "status": status,
        "score": score, "close": round(close, 2),
        "ma_label": ma_label, "ma_value": round(ma_value, 2),
        "ma_slope": round(ma_slope, 2),
        "trend_return": round(trend_return, 2),
        "candle": candle, "volume_ratio": round(volume_ratio, 2),
        "trigger": round(trigger, 2), "stop": round(stop, 2),
        "target1": round((trigger + risk * 1.5) / tick) * tick,
        "target2": round((trigger + risk * 2.5) / tick) * tick,
        "signal_date": pd.Timestamp(frame.index[-1]).strftime("%Y-%m-%d"),
        "reason": (
            f"{setup_type}／{ma_label}傾斜{ma_slope:+.1f}%／"
            f"半年騰落{trend_return:+.1f}%／出来高比{volume_ratio:.2f}倍"
        ),
        "caution": (
            "反転足高値＋1ティックを上抜くまで買わない。"
            "反転足安値割れで撤退。決算7日以内・大幅GUは見送り。"
        ),
    }

def analyse_daily_reversal(item, frame):
    """急落後の出来高急増と複数足の底打ちを検出する。"""
    if frame is None or len(frame) < 65:
        return None
    close_s = frame["Close"].astype(float)
    open_s = frame["Open"].astype(float)
    high_s = frame["High"].astype(float)
    low_s = frame["Low"].astype(float)
    volume_s = frame["Volume"].fillna(0).astype(float)

    o = float(open_s.iloc[-1])
    h = float(high_s.iloc[-1])
    l = float(low_s.iloc[-1])
    c = float(close_s.iloc[-1])
    po = float(open_s.iloc[-2])
    ph = float(high_s.iloc[-2])
    pl = float(low_s.iloc[-2])
    pc = float(close_s.iloc[-2])
    p2o = float(open_s.iloc[-3])
    p2h = float(high_s.iloc[-3])
    p2l = float(low_s.iloc[-3])
    p2c = float(close_s.iloc[-3])

    ma5 = float(close_s.rolling(5).mean().iloc[-1])
    ma20 = float(close_s.rolling(20).mean().iloc[-1])
    avg_volume = float(volume_s.iloc[-23:-3].mean())
    max_recent_volume = float(volume_s.iloc[-3:].max())
    volume_ratio = max_recent_volume / avg_volume if avg_volume else 0
    turnover = c * float(volume_s.iloc[-1])
    pattern_low = float(low_s.iloc[-3:].min())
    fall_from_10d = (float(close_s.iloc[-11]) / pattern_low - 1) * 100

    body = max(abs(c - o), c * .002)
    lower_wick = min(o, c) - l
    prior_body = max(abs(pc - po), pc * .002)
    prior_lower_wick = min(po, pc) - pl
    second_body = max(abs(p2c - p2o), p2c * .002)

    current_hammer = lower_wick >= body * 1.5 and c >= l + (h - l) * .60
    prior_hammer = prior_lower_wick >= prior_body * 1.5 and pc >= pl + (ph - pl) * .55
    bullish_engulfing = c > o and pc < po and o <= pc and c >= po
    morning_star = (
        p2c < p2o
        and prior_body <= second_body * .55
        and c > o
        and c >= (p2o + p2c) / 2
    )
    high_break_confirmation = c > o and c > ph
    midpoint_confirmation = c > o and c >= (ph + pl) / 2

    downtrend = (
        fall_from_10d >= 8
        and (c < ma20 or float(close_s.iloc[-4]) < ma20)
        and float(close_s.iloc[-6:-1].max()) > pattern_low * 1.06
    )
    climax = volume_ratio >= 1.5
    base_pattern = current_hammer or prior_hammer or bullish_engulfing or morning_star
    confirmation = high_break_confirmation or bullish_engulfing or morning_star
    liquid = turnover >= 300_000_000 and c >= 100
    if not (downtrend and climax and base_pattern and liquid and midpoint_confirmation):
        return None

    score = 55
    score += 15 if volume_ratio >= 2.5 else 10
    score += 10 if confirmation else 5
    score += 10 if bullish_engulfing or morning_star else 6
    score += 5 if c >= ma5 else 2
    score += 5 if c > (h + l) / 2 else 0
    score = min(100, score)

    if morning_star:
        setup = "明けの明星"
    elif bullish_engulfing:
        setup = "陽線包み足"
    elif prior_hammer and high_break_confirmation:
        setup = "ハンマー高値突破"
    else:
        setup = "セリクラ下ヒゲ反転"
    phase = "反転確認" if confirmation and c >= ma5 else "底打ち準備"

    tick = 1 if c < 3000 else 5
    trigger = math.ceil((h + tick) / tick) * tick
    stop = math.floor((pattern_low - tick) / tick) * tick
    risk = max(trigger - stop, tick)
    return {
        "code": item["code"], "ticker": item["ticker"],
        "name": f"{item['name']}（{item['code']}）",
        "setup": setup, "phase": phase, "score": int(score),
        "close": round(c, 2), "trigger": round(trigger, 2),
        "stop": round(stop, 2),
        "target1": round((trigger + risk * 1.5) / tick) * tick,
        "target2": round((trigger + risk * 2.5) / tick) * tick,
        "volume_ratio": round(volume_ratio, 2),
        "fall_from_10d": round(fall_from_10d, 2),
        "ma5": round(ma5, 2), "ma20": round(ma20, 2),
        "signal_date": pd.Timestamp(frame.index[-1]).strftime("%Y-%m-%d"),
        "reason": f"10日高値圏から−{fall_from_10d:.1f}%／出来高{volume_ratio:.2f}倍／{setup}",
        "caution": "逆張り候補。発動価格を上抜かなければ買わず、パターン安値割れで即撤退。",
    }


def main():
    now = datetime.now(JST)
    universe, source = load_universe()
    old_path = ROOT / "signals.json"
    try:
        old = json.loads(old_path.read_text(encoding="utf-8"))
    except Exception:
        old = {}
    old_prepared = {x["ticker"]: x for x in old.get("prepared", [])}

    results = []
    short_results = []
    hammer_results = []
    long_term_rebounds = []
    daily_reversals = []
    failed = 0
    batch_size = 120
    for start in range(0, len(universe), batch_size):
        batch = universe[start:start + batch_size]
        tickers = [x["ticker"] for x in batch]
        try:
            downloaded = yf.download(
                tickers, period="2y", interval="1d", auto_adjust=False,
                group_by="ticker", progress=False, threads=True, timeout=30
            )
        except Exception:
            downloaded = pd.DataFrame()
        for item in batch:
            frame = one_frame(downloaded, item["ticker"], len(batch) == 1)
            row = analyse(item, frame)
            short_row = analyse_short(item, frame)
            if row:
                results.append(row)
            if short_row:
                short_results.append(short_row)
            if frame is not None:
                for timeframe in ("月足", "週足"):
                    hammer = hammer_row(item, frame, timeframe)
                    if hammer:
                        hammer_results.append(hammer)
                for setup_type in ("週足50週線反発", "日足200日線ハンマー"):
                    rebound = long_term_rebound_row(item, frame, setup_type)
                    if rebound:
                        long_term_rebounds.append(rebound)
                daily_reversal = analyse_daily_reversal(item, frame)
                if daily_reversal:
                    daily_reversals.append(daily_reversal)
            if frame is None:
                failed += 1
        time.sleep(.2)

    results.sort(key=lambda x: (x["score"], x["rvol"], x["ret20"]), reverse=True)
    short_results.sort(key=lambda x: (x["score"], x["rvol"], -x["ret20"]), reverse=True)
    hammer_results.sort(
        key=lambda x: (
            x["score"],
            1 if x["timeframe"] == "月足" else 0,
            x["volume_ratio"],
        ),
        reverse=True,
    )
    long_term_rebounds.sort(
        key=lambda x: (x["score"], x["setup"] == "日足200日線ハンマー", x["volume_ratio"]),
        reverse=True,
    )
    daily_reversals.sort(
        key=lambda x: (x["score"], x["phase"] == "反転確認", x["volume_ratio"]),
        reverse=True,
    )
    overnight_long = [
        x for x in results
        if (
            x["score"] >= 70
            and x["rvol"] >= .90
            and x["atr_pct"] <= 7
            and x["code"] != "285A"  # キオクシアHDは朝スキャル専用
        )
    ][:15]
    entered = []
    for row in results:
        prior = old_prepared.get(row["ticker"])
        if prior and prior.get("signal_date") != row["signal_date"]:
            # 最新日高値を超えたものはIN候補。日足終値データなので最終確認は板で行う。
            if row["close"] >= float(prior.get("trigger", float("inf"))) and row["close"] >= row["ma5"]:
                entered.append({**row, "trigger": prior["trigger"], "prepared_date": prior["signal_date"]})

    output = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": source,
        "universe_count": len(universe),
        "scanned_count": len(universe) - failed,
        "failed_count": failed,
        "signal_count": len(results),
        "prepared": results[:100],
        "entered": entered[:50],
        "overnight_long": overnight_long,
        "overnight_short": short_results[:15],
        "monthly_weekly_hammers": hammer_results[:40],
        "long_term_ma_rebounds": long_term_rebounds[:50],
        "daily_capitulation_reversals": daily_reversals[:40],
        "note": "日足終値ベース。準備足高値を翌日以降に上抜いた場合のみIN。最終判断は板・出来高・会社IRで確認。"
    }
    old_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
