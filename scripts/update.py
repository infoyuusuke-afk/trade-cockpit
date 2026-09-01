import json
import os
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")


def _number(value):
    """Convert a Japanese quote string to float without guessing."""
    if value is None:
        return None
    value = str(value).replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return None
    return float(value)


def nomura_quote(ticker):
    """Read an independent QUICK-based quote used to verify the primary feed."""
    code = str(ticker).split(".", 1)[0]
    if not re.fullmatch(r"[0-9A-Z]{4,5}", code):
        return {"ok": False, "source": "Nomura/QUICK", "error": "invalid_code"}
    url = (
        "https://quote.nomura.co.jp/nomura/cgi-bin/parser.pl?"
        f"MKTN=T&QCODE={code}&TEMPLATE=nomura_tp_kabu_01"
    )
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; TradeCockpitVerifier/1.0)",
            "Accept-Language": "ja-JP,ja;q=0.9",
        })
        html = urlopen(req, timeout=25).read().decode("utf-8", "replace")

        def labelled_value(label):
            m = re.search(
                rf'<th[^>]*>\s*{label}\s*</th>\s*<td[^>]*>\s*([0-9,.]+)',
                html, re.S,
            )
            return m.group(1) if m else None

        stamp = re.search(r'<div class="time">\s*(\d{4}/\d{2}/\d{2})', html)
        values = {
            "price": _number(labelled_value("現在値")),
            "open": _number(labelled_value("始値")),
            "high": _number(labelled_value("高値")),
            "low": _number(labelled_value("安値")),
            "prev_close": _number(labelled_value("前日終値")),
        }
        quote_date = stamp.group(1).replace("/", "-") if stamp else ""
        valid = (
            f"({code}/T)" in html
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", quote_date or "")
            and all(v is not None and v > 0 for v in values.values())
            and values["high"] >= max(values["open"], values["price"])
            and values["low"] <= min(values["open"], values["price"])
        )
        return {
            "ok": bool(valid), "source": "Nomura/QUICK", "url": url,
            "code": code, "data_date": quote_date, **values,
        }
    except Exception as exc:
        return {"ok": False, "source": "Nomura/QUICK", "url": url,
                "code": code, "error": type(exc).__name__}


def fetch_secondary_quotes(tickers, workers=12):
    """Fetch verification quotes concurrently to keep scheduled runs bounded."""
    unique = list(dict.fromkeys(tickers))
    results = {}
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(unique)))) as pool:
        jobs = {pool.submit(nomura_quote, ticker): ticker for ticker in unique}
        for job in as_completed(jobs):
            ticker = jobs[job]
            try:
                results[ticker] = job.result()
            except Exception as exc:
                results[ticker] = {"ok": False, "source": "Nomura/QUICK",
                                   "error": type(exc).__name__}
    return results

US_SECTOR_ETFS = {
    "情報技術・AI": "XLK",
    "コミュニケーション": "XLC",
    "一般消費財": "XLY",
    "資本財・工業": "XLI",
    "金融": "XLF",
    "ヘルスケア": "XLV",
    "エネルギー": "XLE",
    "素材": "XLB",
    "生活必需品": "XLP",
    "公益": "XLU",
    "不動産": "XLRE",
}

SILICON_PHOTONICS_WATCH = [
    {
        "name": "古河電気工業（5801）",
        "code": "5801",
        "role": "CPO向け外部光源・光デバイス",
        "relevance": 96,
        "source": "https://www.furukawa.co.jp/release/2022/comm_20220307.html",
    },
    {
        "name": "住友電気工業（5802）",
        "code": "5802",
        "role": "CPO向け高密度光接続部品",
        "relevance": 93,
        "source": "https://sumitomoelectric.com/jp/rd/technical-reviews/j202",
    },
    {
        "name": "NTT（9432）",
        "code": "9432",
        "role": "光電融合デバイス CoPKG・IOWN",
        "relevance": 90,
        "source": "https://group.ntt/en/newsrelease/2024/03/12/240312a.html",
    },
    {
        "name": "フジクラ（5803）",
        "code": "5803",
        "role": "AIデータセンター向け光配線",
        "relevance": 84,
        "source": "https://www.fujikura.co.jp/news/pressrelease/2026030913824swr_wtc.html",
    },
    {
        "name": "富士通（6702）",
        "code": "6702",
        "role": "光電融合・次世代ネットワーク",
        "relevance": 76,
        "source": "https://www.fujitsu.com/global/about/resources/news/press-releases/2021/0426-01.html",
    },
]


def flat_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def daily_snapshot(ticker, secondary=None):
    try:
        df = flat_columns(yf.download(
            ticker, period="1y", interval="1d", auto_adjust=False,
            actions=True, progress=False, threads=False
        )).dropna(subset=["Close"])
        if len(df) < 3:
            return {"ok": False}
        close = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        high = float(df["High"].iloc[-1])
        low = float(df["Low"].iloc[-1])
        open_ = float(df["Open"].iloc[-1])
        vol = float(df["Volume"].iloc[-1]) if "Volume" in df else 0
        avg_vol = float(df["Volume"].tail(20).mean()) if "Volume" in df else 0
        turnover = close * vol
        tr = pd.concat([
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean())
        ma5 = float(df["Close"].tail(5).mean())
        ma20 = float(df["Close"].tail(20).mean())
        ma60 = float(df["Close"].tail(60).mean()) if len(df) >= 60 else ma20
        old_ma20 = float(df["Close"].iloc[-40:-20].mean()) if len(df) >= 40 else ma20
        prior_high20 = float(df["High"].iloc[-21:-1].max()) if len(df) >= 21 else high
        high52 = float(df["High"].tail(252).max())
        rolling_ma = df["Close"].rolling(20).mean()
        rolling_sd = df["Close"].rolling(20).std(ddof=0)
        bb_upper = float((rolling_ma + rolling_sd * 2).iloc[-1])
        bb_lower = float((rolling_ma - rolling_sd * 2).iloc[-1])
        bb_width_series = ((rolling_sd * 4) / rolling_ma * 100).dropna()
        bb_width = float(bb_width_series.iloc[-1])
        bb_width_prev5 = float(bb_width_series.iloc[-6:-1].mean()) if len(bb_width_series) >= 6 else bb_width
        bb_percentile = float((bb_width_series.tail(120) <= bb_width).mean() * 100)
        ret5 = (close / float(df["Close"].iloc[-6]) - 1) * 100 if len(df) >= 6 else 0
        ret5_prev = (
            (float(df["Close"].iloc[-6]) / float(df["Close"].iloc[-11]) - 1) * 100
            if len(df) >= 11 else ret5
        )
        ret20 = (close / float(df["Close"].iloc[-21]) - 1) * 100 if len(df) >= 21 else 0
        change = (close / prev - 1) * 100 if prev else 0
        rvol = vol / avg_vol if avg_vol else 0
        atr_pct = atr / close * 100 if close else 0
        from_ma20 = (close / ma20 - 1) * 100 if ma20 else 0
        from_ma5 = (close / ma5 - 1) * 100 if ma5 else 0
        touch_ma5 = low <= ma5 * 1.01 and close >= ma5
        to_high20 = (close / prior_high20 - 1) * 100 if prior_high20 else 0
        to_high52 = (close / high52 - 1) * 100 if high52 else 0
        day_score = (
            min(max(change, -4), 4) * .8
            + min(max(ret5, -8), 8) * .35
            + min(rvol, 3) * 1.5
            + (2 if turnover >= 5_000_000_000 else 0)
            + (1 if close >= ma5 else -1)
        )
        swing_score = (
            min(max(ret20, -15), 15) * .25
            + min(max(ret5, -8), 8) * .35
            + (2 if ma5 > ma20 else -2)
            + (1 if close > ma20 else -1)
            + min(rvol, 2)
        )
        stable_score = (
            (3 if close > ma20 > ma60 else 0)
            + (2 if ma20 > old_ma20 else -1)
            + min(max(ret20, -5), 15) * .18
            + min(rvol, 2)
            + (2 if atr_pct <= 3.5 else 0)
            + (2 if turnover >= 5_000_000_000 else 0)
        )
        momentum_score = (
            min(max(ret5, -5), 25) * .32
            + min(max(ret20, -10), 35) * .12
            + min(rvol, 4) * 2
            + (3 if to_high20 >= -1 else 0)
            + (4 if touch_ma5 else 1 if 0 <= from_ma5 <= 5 else 0)
            + (2 if turnover >= 3_000_000_000 else 0)
            - (4 if from_ma20 > 18 or atr_pct > 9 else 0)
        )
        high_score = (
            (5 if to_high52 >= -1 else 3 if to_high52 >= -3 else 0)
            + (3 if close >= prior_high20 else 0)
            + min(rvol, 3) * 1.5
            + (2 if ma20 > old_ma20 else 0)
            + (2 if turnover >= 5_000_000_000 else 0)
            - (3 if from_ma20 > 15 else 0)
        )
        bb_expansion_score = (
            max(0, 35 - bb_percentile * .35)
            + (20 if close >= bb_upper else 12 if close >= ma20 else 0)
            + min(rvol, 3) / 3 * 20
            + (10 if ma20 > old_ma20 else 0)
            + (15 if to_high20 >= -3 else 8 if to_high20 >= -8 else 0)
        )
        supply_frame = df.tail(20)
        direction = supply_frame["Close"].diff().fillna(0)
        up_volume = float(supply_frame.loc[direction > 0, "Volume"].sum())
        down_volume = float(supply_frame.loc[direction < 0, "Volume"].sum())
        volume_ratio = up_volume / down_volume if down_volume else 2.0
        obv_impulse = float((direction.apply(lambda x: 1 if x > 0 else -1 if x < 0 else 0) * supply_frame["Volume"]).sum())
        volume_total = max(float(supply_frame["Volume"].sum()), 1)
        higher_lows = float(supply_frame["Low"].tail(5).mean()) > float(supply_frame["Low"].iloc[-10:-5].mean())
        close_location = (close - low) / max(high - low, .01)
        market_supply_score = round(min(max(
            35 + min(volume_ratio, 2.5) * 15
            + max(min(obv_impulse / volume_total, .35), -.35) * 55
            + (12 if higher_lows else 0) + close_location * 8, 0), 100))
        dividend_rows = df[df.get("Dividends", pd.Series(0, index=df.index)).fillna(0) > 0]
        last_dividend = float(dividend_rows["Dividends"].iloc[-1]) if not dividend_rows.empty else 0
        estimated_ex_date = None
        dividend_days = None
        if not dividend_rows.empty:
            dates = [pd.Timestamp(x).tz_localize(None) for x in dividend_rows.index]
            interval_days = int((dates[-1] - dates[-2]).days) if len(dates) >= 2 else 182
            interval_days = min(max(interval_days, 150), 220)
            next_date = dates[-1] + pd.Timedelta(days=interval_days)
            today = pd.Timestamp.now(tz=JST).tz_localize(None).normalize()
            while next_date < today:
                next_date += pd.Timedelta(days=interval_days)
            estimated_ex_date = next_date.strftime("%Y-%m-%d")
            dividend_days = int((next_date - today).days)
        data_ts = pd.Timestamp(df.index[-1])
        if data_ts.tzinfo is not None:
            data_ts = data_ts.tz_convert(JST).tz_localize(None)
        data_date = data_ts.date()
        age_days = (datetime.now(JST).date() - data_date).days
        ohlc_valid = bool(
            close > 0 and high >= max(open_, close) and low <= min(open_, close)
            and high >= low and prev > 0
        )
        chart = [
            {
                "o": round(float(r["Open"]), 2),
                "h": round(float(r["High"]), 2),
                "l": round(float(r["Low"]), 2),
                "c": round(float(r["Close"]), 2), "v": round(float(r["Volume"])),
            }
            for _, r in df.tail(40).iterrows()
        ]
        chart_close = chart[-1]["c"] if chart else None
        chart_matches = bool(chart_close is not None and abs(chart_close - close) <= max(.11, close * .0001))
        # Fail closed: at 8:00 a Friday close can be three calendar days old,
        # but anything older must never be presented as the current reference.
        secondary = secondary or {}
        secondary_matches = bool(
            secondary.get("ok")
            and secondary.get("code") == str(ticker).split(".", 1)[0]
            and secondary.get("data_date") == data_date.isoformat()
            and all(
                abs(float(secondary[field]) - primary) <= .01
                for field, primary in (
                    ("price", close), ("open", open_), ("high", high),
                    ("low", low), ("prev_close", prev),
                )
            )
        )
        quote_verified = bool(
            ohlc_valid and chart_matches and secondary_matches
            and 0 <= age_days <= 3
        )
        return {
            "ok": True, "price": round(close, 2), "open": round(open_, 2),
            "high": round(high, 2), "low": round(low, 2),
            "prev_close": round(prev, 2), "change_pct": round(change, 2),
            "ret5": round(ret5, 2), "ret5_prev": round(ret5_prev, 2),
            "ret20": round(ret20, 2),
            "rvol": round(rvol, 2), "turnover": round(turnover),
            "atr14": round(atr, 2), "atr_pct": round(atr_pct, 2),
            "ma5": round(ma5, 2), "ma20": round(ma20, 2), "ma60": round(ma60, 2),
            "from_ma5": round(from_ma5, 2), "from_ma20": round(from_ma20, 2),
            "touch_ma5": touch_ma5, "to_high20": round(to_high20, 2),
            "to_high52": round(to_high52, 2),
            "bb_upper": round(bb_upper, 2), "bb_lower": round(bb_lower, 2),
            "bb_width": round(bb_width, 2),
            "bb_width_change": round(bb_width - bb_width_prev5, 2),
            "bb_percentile": round(bb_percentile, 1),
            "bb_expansion_score": round(min(bb_expansion_score, 100), 1),
            "day_score": round(day_score, 2), "swing_score": round(swing_score, 2),
            "stable_score": round(stable_score, 2),
            "momentum_score": round(momentum_score, 2),
            "high_score": round(high_score, 2), "chart": chart,
            "data_date": data_date.isoformat(), "data_age_days": age_days,
            "chart_last_close": chart_close, "quote_verified": quote_verified,
            "secondary_source": secondary.get("source", "未取得"),
            "secondary_price": secondary.get("price"),
            "secondary_date": secondary.get("data_date"),
            "secondary_verified": secondary_matches,
            "quote_status": (
                f"二経路検証済み：{data_date.isoformat()}終値 {close:,.2f}円"
                if quote_verified else
                f"売買利用禁止：一次株価・QUICK照合・チャート終点の不一致（{data_date.isoformat()}）"
            ),
            "market_supply_score": market_supply_score,
            "market_supply_improved": market_supply_score >= 60,
            "market_supply_status": f"市場需給{market_supply_score}点／上昇日出来高÷下落日{volume_ratio:.2f}倍／安値切上げ{'○' if higher_lows else '×'}"
            ,"last_dividend": round(last_dividend, 2), "estimated_ex_date": estimated_ex_date,
            "dividend_days": dividend_days
        }
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def intraday_snapshot(ticker):
    try:
        df = flat_columns(yf.download(
            ticker, period="5d", interval="5m", auto_adjust=False,
            progress=False, threads=False, prepost=False
        )).dropna(subset=["Close"])
        if df.empty:
            return {"ok": False}
        dates = pd.Index(df.index.date)
        df = df[dates == dates[-1]].copy()
        if df.empty:
            return {"ok": False}
        vol = df["Volume"].fillna(0)
        typical = (df["High"] + df["Low"] + df["Close"]) / 3
        vwap = float((typical * vol).sum() / vol.sum()) if float(vol.sum()) else float(df["Close"].iloc[-1])
        data_ts = pd.Timestamp(df.index[-1])
        if data_ts.tzinfo is not None:
            data_ts = data_ts.tz_convert(JST)
        return {
            "ok": True, "open": round(float(df["Open"].iloc[0]), 2),
            "high": round(float(df["High"].max()), 2),
            "low": round(float(df["Low"].min()), 2),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "vwap": round(vwap, 2), "volume": round(float(vol.sum())),
            "data_date": data_ts.strftime("%Y-%m-%d"),
            "data_time": data_ts.strftime("%Y-%m-%d %H:%M JST"),
        }
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def earnings_date(ticker, now):
    try:
        cal = yf.Ticker(ticker).get_earnings_dates(limit=4)
        if cal is None or cal.empty:
            return None
        dates = []
        for dt in cal.index:
            ts = pd.Timestamp(dt)
            if ts.tzinfo is None:
                ts = ts.tz_localize(JST)
            else:
                ts = ts.tz_convert(JST)
            delta = (ts.date() - now.date()).days
            if -1 <= delta <= 7:
                dates.append((delta, ts.strftime("%Y-%m-%d")))
        return sorted(dates)[0][1] if dates else None
    except Exception:
        return None


def jpx_earnings_map(now):
    """Read JPX's official monthly earnings schedule spreadsheets."""
    page = "https://www.jpx.co.jp/listing/event-schedules/financial-announcement/"
    try:
        req = Request(page, headers={"User-Agent": "Mozilla/5.0 trade-cockpit"})
        html = urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
        links = re.findall(r'href=["\']([^"\']+\.(?:xlsx?|XLSX?))', html)
        result = {}
        for href in links[-4:]:
            url = urljoin(page, href)
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 trade-cockpit"})
            raw = urlopen(req, timeout=30).read()
            sheets = pd.read_excel(BytesIO(raw), sheet_name=None, header=None)
            for frame in sheets.values():
                for _, row in frame.iterrows():
                    vals = [x for x in row.tolist() if pd.notna(x)]
                    text_vals = [str(x).strip() for x in vals]
                    code = next((re.sub(r"\.0$", "", x) for x in text_vals
                                 if re.fullmatch(r"\d{4}[A-Z]?(?:\.0)?", x)), None)
                    if not code:
                        continue
                    found_date = None
                    for value in vals:
                        try:
                            ts = pd.Timestamp(value)
                            if 2025 <= ts.year <= 2028:
                                found_date = ts.strftime("%Y-%m-%d")
                                break
                        except Exception:
                            pass
                    if found_date:
                        delta = (pd.Timestamp(found_date).date() - now.date()).days
                        if -1 <= delta <= 7:
                            result[code] = {"date": found_date, "source": "JPX"}
        return result
    except Exception:
        return {}


def price_tick(price):
    """Return a conservative valid order step for the displayed MS2 prices.

    A decimal last price is used as evidence that the issue trades in 0.1-yen
    units (for example NTT).  For the other issues we use the wider standard
    TSE steps, which remain valid even when a TOPIX100 issue accepts a finer
    step.
    """
    price = float(price)
    if price < 1000 and abs(price - round(price)) >= .05:
        return .1
    if price < 3000:
        return 1
    if price < 5000:
        return 5
    if price < 30000:
        return 10
    if price < 50000:
        return 50
    return 100


def round_to_tick(value, tick):
    rounded = round(float(value) / tick) * tick
    return round(rounded, 1) if tick < 1 else round(rounded)


def trade_plan(r, intraday=None):
    p = float((intraday or {}).get("close") or r["price"])
    atr = max(float(r.get("atr14") or p * .02), p * .008)
    vwap = (intraday or {}).get("vwap")
    if vwap:
        entry = min(p, float(vwap) * 1.002)
        stop = min(entry - atr * .55, float(vwap) * .992)
    else:
        entry = min(p, float(r.get("prev_close") or p)) + atr * .12
        stop = entry - atr * .65
    risk = max(entry - stop, p * .004)
    target1 = entry + risk * 1.5
    target2 = entry + risk * 2.2
    tick = price_tick(p)
    rounded = lambda x: round_to_tick(x, tick)
    return {
        "entry": rounded(entry), "stop": rounded(stop),
        "target1": rounded(target1), "target2": rounded(target2),
        "risk": rounded(risk), "tick": tick
    }


def material_lifecycle(row):
    """Classify momentum without treating social buzz as a buy signal."""
    ret5 = float(row.get("ret5") or 0)
    ret20 = float(row.get("ret20") or 0)
    rvol = float(row.get("rvol") or 0)
    stretched = float(row.get("from_ma20") or 0)
    if not row.get("quote_verified"):
        return {"stage": "事実確認待ち", "action": "株価再照合まで売買禁止", "priority_penalty": 99}
    if ret5 >= 25 or (ret5 >= 15 and rvol >= 2.5) or stretched >= 18:
        return {"stage": "材料出尽くし警戒", "action": "飛び乗り禁止・初押し反転待ち", "priority_penalty": 30}
    if ret5 >= 10 or rvol >= 1.8:
        return {"stage": "期待形成中", "action": "高値追い禁止・発動足待ち", "priority_penalty": 8}
    if rvol >= 1.25 and 0 <= ret5 <= 10:
        return {"stage": "先回り候補", "action": "OR15・VWAP一致で発動", "priority_penalty": 0}
    if ret20 >= 8:
        return {"stage": "織り込み進行", "action": "押し目反転だけ監視", "priority_penalty": 2}
    return {"stage": "事実確認待ち", "action": "出来高・需給確認待ち", "priority_penalty": 5}


def expectation_score(r, earnings=False):
    score = 0
    score += 20 if r["turnover"] >= 10_000_000_000 else 14 if r["turnover"] >= 3_000_000_000 else 8
    score += 20 if r["price"] > r["ma5"] > r["ma20"] else 12 if r["price"] > r["ma20"] else 4
    score += min(max(r["ret20"], 0), 20)
    score += min(r["rvol"], 2) / 2 * 15
    score += 15 if r["to_high52"] >= -3 else 10 if r["to_high52"] >= -10 else 4
    score += 10 if r["to_high20"] >= -2 else 5 if r["to_high20"] >= -7 else 0
    if r["from_ma20"] > 18 or r["atr_pct"] > 9:
        score -= 15
    if earnings:
        score += 5 if r["bb_width_change"] > 0 and r["price"] >= r["ma20"] else 0
    return round(max(0, min(score, 100)))


def first_number(frame, row_name, columns):
    try:
        if frame is None or frame.empty or row_name not in frame.index:
            return None
        for column in columns:
            if column in frame.columns:
                value = frame.loc[row_name, column]
                if pd.notna(value):
                    return float(value)
    except Exception:
        pass
    return None


def earnings_expectation(ticker, technical_score):
    """Score expected earnings quality from estimates, revisions and surprise history."""
    parts = []
    details = []
    eps_growth = None
    revenue_growth = None
    surprise_avg = None
    revision_up = 0
    revision_down = 0
    dispersion = None
    try:
        stock = yf.Ticker(ticker)
        eps = stock.get_earnings_estimate()
        rev = stock.get_revenue_estimate()
        revisions = stock.get_eps_revisions()
        history = stock.get_earnings_history()

        eps_growth = first_number(eps, "0q", ["growth"])
        if eps_growth is not None:
            value = max(0, min(100, 50 + min(eps_growth, .30) * 100))
            parts.append((value, 30))
            details.append(f"予想EPS成長 {eps_growth*100:+.1f}%")
            eps_avg = first_number(eps, "0q", ["avg"])
            eps_low = first_number(eps, "0q", ["low"])
            eps_high = first_number(eps, "0q", ["high"])
            if eps_avg not in (None, 0) and eps_low is not None and eps_high is not None:
                dispersion = abs(eps_high - eps_low) / abs(eps_avg) * 100
                details.append(f"EPS予想幅 {dispersion:.1f}%")

        revenue_growth = first_number(rev, "0q", ["growth"])
        if revenue_growth is not None:
            value = max(0, min(100, 50 + min(revenue_growth, .20) * 130))
            parts.append((value, 20))
            details.append(f"予想売上成長 {revenue_growth*100:+.1f}%")

        if history is not None and not history.empty:
            surprise_col = next((c for c in history.columns if "surprise" in str(c).lower()), None)
            if surprise_col is not None:
                surprises = pd.to_numeric(history[surprise_col], errors="coerce").dropna().tail(4)
                if not surprises.empty:
                    avg = float(surprises.mean())
                    if abs(avg) <= 1:
                        avg *= 100
                    surprise_avg = avg
                    beat_rate = float((surprises > 0).mean())
                    value = max(0, min(100, 40 + avg * 2 + beat_rate * 35))
                    parts.append((value, 25))
                    details.append(f"過去4回サプライズ平均 {avg:+.1f}%")

        if revisions is not None and not revisions.empty and "0q" in revisions.index:
            row = revisions.loc["0q"]
            ups = sum(float(row.get(c, 0) or 0) for c in ["upLast7days", "upLast30days"])
            downs = sum(float(row.get(c, 0) or 0) for c in ["downLast7Days", "downLast7days", "downLast30days"])
            revision_up, revision_down = ups, downs
            total = ups + downs
            if total > 0:
                value = max(0, min(100, 50 + (ups - downs) / total * 45))
                parts.append((value, 15))
                details.append(f"予想修正 上{ups:.0f}／下{downs:.0f}")

    except Exception:
        pass

    parts.append((technical_score, 10))
    details.append(f"決算前テクニカル {technical_score}/100")
    total_weight = sum(weight for _, weight in parts)
    raw_score = sum(value * weight for value, weight in parts) / total_weight
    hurdle = 0
    if eps_growth is not None:
        hurdle += 25 if eps_growth >= .50 else 18 if eps_growth >= .35 else 10 if eps_growth >= .20 else 0
    if revenue_growth is not None:
        hurdle += 15 if revenue_growth >= .30 else 10 if revenue_growth >= .20 else 5 if revenue_growth >= .10 else 0
    if dispersion is not None:
        hurdle += 15 if dispersion >= 25 else 10 if dispersion >= 15 else 5 if dispersion >= 8 else 0
    if revision_down > revision_up:
        hurdle += 20
    elif revision_down > 0:
        hurdle += 8
    if surprise_avg is not None:
        hurdle += 12 if surprise_avg < 2 else 7 if surprise_avg < 5 else 0
    hurdle += 15 if technical_score >= 80 else 8 if technical_score >= 65 else 0
    hurdle = round(min(hurdle, 100))
    penalty = hurdle * .28
    score = round(raw_score - penalty)
    coverage = round(total_weight)
    details.append(f"コンセンサス警戒 {hurdle}/100（−{penalty:.1f}点）")
    return {
        "score": max(0, min(score, 100)),
        "coverage": coverage,
        "detail": "／".join(details),
        "hurdle_risk": hurdle,
        "raw_score": round(raw_score)
    }


def review_trade(plan, intra):
    if not intra or not intra.get("ok"):
        return {"result": "検証不能"}
    entry, stop = plan["entry"], plan["stop"]
    entry_limit = plan.get("entry_limit", entry)
    t1 = plan["target1"]
    entered = intra["high"] >= entry and intra["low"] <= entry_limit
    if not entered:
        return {"result": "未約定", "detail": f"安値{intra['low']:,.0f}／高値{intra['high']:,.0f}"}
    stop_hit = intra["low"] <= stop
    target_hit = intra["high"] >= t1
    if stop_hit and target_hit:
        result = "順序不明（成績除外）"
    elif target_hit:
        result = "IFO利確"
    elif stop_hit:
        result = "IFO損切り"
    else:
        result = "継続・未決済"
    pnl = intra["close"] - entry
    return {
        "result": result,
        "detail": f"終値差 {pnl:+,.0f}円／VWAP {intra['vwap']:,.0f}円"
    }


def money(v):
    if v is None:
        return "—"
    value = float(v)
    return f"{value:,.1f}" if abs(value - round(value)) >= .05 else f"{value:,.0f}"


def load_active_buybacks(now):
    """Return officially sourced, currently active buybacks ranked by supply impact."""
    try:
        payload = json.loads((ROOT / "buybacks.json").read_text(encoding="utf-8"))
    except Exception:
        return [], "未取得"
    rows = []
    for raw in payload.get("programs", []):
        try:
            start = pd.Timestamp(raw["start_date"]).date()
            end = pd.Timestamp(raw["end_date"]).date()
            if not (start <= now.date() <= end) or not raw.get("official_source"):
                continue
            cap_pct = float(raw["max_share_pct"])
            progress = float(raw.get("progress_pct", 0))
            remaining_pct = max(0.0, 100.0 - progress)
            daily_impact = float(raw.get("daily_volume_impact_pct", 0))
            score = min(100, round(
                min(cap_pct, 10) * 4 + remaining_pct * .25
                + min(daily_impact, 30)
                + (5 if raw.get("cancellation_planned") else 0)
            ))
            rows.append({**raw, "score": score, "remaining_pct": round(remaining_pct, 1)})
        except Exception:
            continue
    rows.sort(key=lambda x: (x["score"], x["max_share_pct"], x["remaining_pct"]), reverse=True)
    return rows[:5], payload.get("updated_at", "未更新")


def load_credit_supply_map():
    """Load verified credit-supply inputs without inventing missing values."""
    try:
        payload = json.loads((ROOT / "credit_supply.json").read_text(encoding="utf-8"))
        return payload.get("stocks", {}), payload.get("updated_at", "未取得")
    except Exception:
        return {}, "未取得"


def pct(v):
    return "—" if v is None else f"{v:+.2f}%"


def css(v):
    return "up" if isinstance(v, (int, float)) and v > 0 else "down" if isinstance(v, (int, float)) and v < 0 else ""


def average(rows, key, default=0):
    values = [
        float(row.get(key, 0)) for row in rows
        if isinstance(row.get(key), (int, float))
    ]
    return sum(values) / len(values) if values else default


def clamp(value, low=0, high=100):
    return max(low, min(high, value))


def broad_sector(sector):
    """Group the watchlist themes into investable top-down buckets."""
    if any(x in sector for x in ("銀行", "保険", "金融")):
        return "金融"
    if any(x in sector for x in ("自動車", "EV", "MaaS")):
        return "自動車・モビリティ"
    if any(x in sector for x in ("防衛", "重工", "FA", "ロボット", "機械", "電線", "電力", "蓄電池")):
        return "資本財・インフラ"
    if any(x in sector for x in ("半導体", "AI", "電子", "DX", "データセンター")):
        return "AI・テクノロジー"
    if any(x in sector for x in ("資源", "原油", "商社", "海運", "素材")):
        return "資源・素材・商社"
    if any(x in sector for x in ("通信", "鉄道", "内需", "ゲーム", "コンテンツ", "サービス")):
        return "内需・ディフェンシブ"
    return "その他"


def rotation_phase(rel5, rel20, acceleration, ma_gap=0):
    """Classify money flow without treating the strongest sector as an automatic buy."""
    if rel20 >= 7 and ma_gap >= 7 and (rel5 <= 0 or acceleration <= -1):
        return "過熱・失速注意"
    if rel5 > 0 and acceleration >= .7 and rel20 <= 3:
        return "流入初期"
    if rel5 > 0 and rel20 > 0 and acceleration >= -1:
        return "拡大"
    if rel5 < 0 and acceleration < 0:
        return "流出"
    if rel20 < 0 and rel5 <= 0:
        return "低迷"
    return "中立"


def rotation_score(rel5, rel20, acceleration, ma_gap=0, breadth=50, rvol=1):
    raw = (
        50
        + clamp(rel5, -8, 8) * 3.2
        + clamp(rel20, -15, 15) * .9
        + clamp(acceleration, -8, 8) * 1.8
        + clamp(ma_gap, -10, 10) * .45
        + (breadth - 50) * .12
        + clamp(rvol - 1, -1, 2) * 3
    )
    return round(clamp(raw), 1)


def phase_action(phase):
    return {
        "流入初期": "最優先監視・初押し",
        "拡大": "順張り・押し目",
        "過熱・失速注意": "利確優先・飛び乗り禁止",
        "流出": "新規ロング停止",
        "低迷": "見送り",
        "中立": "方向確認待ち",
    }.get(phase, "待機")


def phase_badge(phase):
    cls = {
        "流入初期": "in",
        "拡大": "long",
        "過熱・失速注意": "prep",
        "流出": "short",
        "低迷": "short",
    }.get(phase, "")
    return f"<span class='pill {cls}'>{phase}</span>"


def build_sector_rotation(indices, valid):
    """Top-down view: macro -> sector -> Japanese group -> stock."""
    sp500 = indices.get("S&P500", {})
    topix = indices.get("TOPIX", {})
    us_rows = []
    sector_items = [] if os.getenv("COCKPIT_OFFLINE_RENDER", "0") == "1" else US_SECTOR_ETFS.items()
    for sector, ticker in sector_items:
        snap = daily_snapshot(ticker)
        if not snap.get("ok") or not sp500.get("ok"):
            continue
        rel5 = snap.get("ret5", 0) - sp500.get("ret5", 0)
        rel20 = snap.get("ret20", 0) - sp500.get("ret20", 0)
        acceleration = (
            snap.get("ret5", 0) - snap.get("ret5_prev", snap.get("ret5", 0))
            - sp500.get("ret5", 0) + sp500.get("ret5_prev", sp500.get("ret5", 0))
        )
        breadth_proxy = 100 if snap.get("price", 0) >= snap.get("ma20", float("inf")) else 0
        phase = rotation_phase(rel5, rel20, acceleration, snap.get("from_ma20", 0))
        us_rows.append({
            "sector": sector, "ticker": ticker, "phase": phase,
            "score": rotation_score(
                rel5, rel20, acceleration, snap.get("from_ma20", 0),
                breadth_proxy, snap.get("rvol", 1)
            ),
            "rel5": round(rel5, 2), "rel20": round(rel20, 2),
            "acceleration": round(acceleration, 2),
            "from_ma20": snap.get("from_ma20", 0),
            "action": phase_action(phase),
        })
    us_rows.sort(key=lambda x: x["score"], reverse=True)

    groups = {}
    for name, row in valid:
        group = broad_sector(row.get("sector", ""))
        row["rotation_group"] = group
        groups.setdefault(group, []).append((name, row))

    jp_rows = []
    for group, members in groups.items():
        rows = [row for _, row in members]
        group_ret5 = average(rows, "ret5")
        group_ret5_prev = average(rows, "ret5_prev", group_ret5)
        group_ret20 = average(rows, "ret20")
        rel5 = group_ret5 - topix.get("ret5", 0)
        rel20 = group_ret20 - topix.get("ret20", 0)
        acceleration = (
            group_ret5 - group_ret5_prev
            - topix.get("ret5", 0) + topix.get("ret5_prev", topix.get("ret5", 0))
        )
        breadth = sum(row.get("price", 0) >= row.get("ma20", float("inf")) for row in rows) / len(rows) * 100
        ma_gap = average(rows, "from_ma20")
        rvol = average(rows, "rvol", 1)
        phase = rotation_phase(rel5, rel20, acceleration, ma_gap)
        leaders = sorted(
            members,
            key=lambda x: (
                x[1].get("ret5", 0) - topix.get("ret5", 0)
                + min(x[1].get("rvol", 0), 3) * 1.5
            ),
            reverse=True,
        )[:3]
        jp_rows.append({
            "sector": group, "phase": phase,
            "score": rotation_score(rel5, rel20, acceleration, ma_gap, breadth, rvol),
            "rel5": round(rel5, 2), "rel20": round(rel20, 2),
            "acceleration": round(acceleration, 2),
            "breadth": round(breadth, 1), "rvol": round(rvol, 2),
            "members": len(members),
            "leaders": [
                {
                    "name": name,
                    "ret5": row.get("ret5", 0),
                    "rvol": row.get("rvol", 0),
                }
                for name, row in leaders
            ],
            "action": phase_action(phase),
        })
    jp_rows.sort(key=lambda x: x["score"], reverse=True)
    jp_by_sector = {row["sector"]: row for row in jp_rows}

    growth_scores = [
        row["score"] for row in us_rows
        if row["sector"] in ("情報技術・AI", "コミュニケーション", "一般消費財")
    ]
    rotation_scores = [
        row["score"] for row in us_rows
        if row["sector"] in ("資本財・工業", "金融", "ヘルスケア", "エネルギー", "素材")
    ]
    growth_score = sum(growth_scores) / len(growth_scores) if growth_scores else 50
    rotation_value_score = sum(rotation_scores) / len(rotation_scores) if rotation_scores else 50
    spread = rotation_value_score - growth_score
    if spread >= 5:
        regime = "グロースからバリュー・資本財へ"
        regime_action = "AI一本へ集中せず、金融・資本財・ヘルスケアの初押しを優先"
    elif spread <= -5:
        regime = "グロース回帰"
        regime_action = "AI・情報技術の押し目を優先。ただし過熱判定なら追わない"
    else:
        regime = "混在・切替中"
        regime_action = "指数ではなく、流入初期または拡大のセクターだけを選ぶ"

    positive_breadth = sum(row["rel5"] > 0 for row in us_rows)
    us10y = indices.get("米10年金利", {})
    rate5 = us10y.get("ret5", 0)
    if rate5 >= 1:
        rate_view = "金利上昇：高PERグロースに逆風"
    elif rate5 <= -1:
        rate_view = "金利低下：グロースに追い風"
    else:
        rate_view = "金利横ばい：業績と需給を優先"

    picks = []
    favored = {
        row["sector"]: row for row in jp_rows
        if row["phase"] in ("流入初期", "拡大") and row["score"] >= 55
    }
    for name, row in valid:
        group = row.get("rotation_group")
        group_row = favored.get(group)
        if not group_row or row.get("turnover", 0) < 500_000_000:
            continue
        stock_rel5 = row.get("ret5", 0) - topix.get("ret5", 0)
        lifecycle = material_lifecycle(row)
        score = clamp(
            group_row["score"] * .55
            + 35
            + clamp(stock_rel5, -8, 8) * 1.8
            + clamp(row.get("rvol", 1) - 1, -1, 2) * 3
            - lifecycle["priority_penalty"]
        )
        picks.append({
            "name": name, "sector": group, "phase": group_row["phase"],
            "score": round(score),
            "material_stage": lifecycle["stage"],
            "material_action": lifecycle["action"],
            "plan": trade_plan(row, row.get("intraday")),
            "reason": (
                f"{group}が{group_row['phase']}／TOPIX比5日 "
                f"{group_row['rel5']:+.2f}%／出来高比 {row.get('rvol', 0):.2f}倍"
            ),
        })
    picks.sort(key=lambda x: x["score"], reverse=True)
    picks = picks[:7]

    kioxia = next(
        ((name, row) for name, row in valid if "キオクシア" in name),
        None,
    )
    kioxia_view = {
        "status": "データなし",
        "action": "判定不能",
        "detail": "株価またはセクターデータを取得できませんでした。",
    }
    if kioxia:
        name, row = kioxia
        group_row = jp_by_sector.get(row.get("rotation_group"), {})
        phase = group_row.get("phase", "中立")
        if phase in ("流出", "低迷", "過熱・失速注意"):
            action = "追加買い停止"
            detail = "会社材料よりセクター需給を優先。セクターが流入初期へ戻り、個別が前日高値を上抜くまで新規資金を入れない。"
        elif phase in ("流入初期", "拡大"):
            action = "反転条件だけ再評価"
            detail = "セクターの追い風は確認。ただし前日高値突破＋VWAP上維持を満たすまで買い増し判定にはしない。"
        else:
            action = "新規追加は見送り"
            detail = "方向未確定。業績期待だけで平均取得単価を下げず、セクターと個別の両方の反転を待つ。"
        kioxia_view = {
            "name": name, "status": phase, "action": action, "detail": detail,
            "sector_score": group_row.get("score"),
            "sector_rel5": group_row.get("rel5"),
        }

    return {
        "method": "アセット→セクター→個別株のトップダウン",
        "regime": regime, "regime_action": regime_action,
        "rate_view": rate_view, "rate5": round(rate5, 2),
        "breadth": f"{positive_breadth}/{len(us_rows)}",
        "spread": round(spread, 1),
        "us_sectors": us_rows, "japan_sectors": jp_rows,
        "picks": picks, "kioxia": kioxia_view,
        "source_note": "米国11業種ETFのS&P500相対強弱と、日本株監視群のTOPIX相対強弱による公開データ代理指標",
    }


def build_day_ifo_candidates(valid, rotation, official_earnings, now, credit_supply=None):
    """Build the user's five primary 8:55 MS2 IFO trading candidates.

    Capital follows short-lived themes, so this list must not become a static
    large-cap watchlist.  Prefer money-game/IPO/growth and SaaS/AI-software
    names with actual turnover and relative-volume expansion.  Orders remain
    conditional and are cancelled when the 8:55 indication is already above
    the entry limit.
    """
    sector_rows = {
        row["sector"]: row for row in rotation.get("japan_sectors", [])
    }
    excluded_phases = {"低迷"}
    credit_supply = credit_supply or {}
    eligible = []
    for name, row in valid:
        code = str(row.get("ticker", "")).split(".")[0]
        supply = credit_supply.get(code, {})
        price = float(row.get("price") or 0)
        group = row.get("rotation_group") or broad_sector(row.get("sector", ""))
        sector = sector_rows.get(group, {})
        phase = sector.get("phase", "中立")
        if code == "285A" or "キオクシア" in name:
            continue
        bucket = row.get("day_bucket")
        if row.get("style") not in ("day", "both"):
            continue
        if not (100 <= price <= 30000):
            continue
        min_turnover = 300_000_000 if bucket else 2_000_000_000
        if row.get("turnover", 0) < min_turnover:
            continue
        if row.get("atr_pct", 99) > (20.0 if bucket else 9.0):
            continue
        if row.get("from_ma20", 99) > (45 if bucket else 15):
            continue
        if price < float(row.get("ma20") or price) * (.94 if bucket else .985):
            continue
        if phase in excluded_phases:
            continue

        event = official_earnings.get(code)
        event_days = None
        if event and event.get("date"):
            event_days = (pd.Timestamp(event["date"]).date() - now.date()).days
            if 0 <= event_days <= 2:
                # A 100-share IFO basket is not used for an imminent earnings bet.
                continue

        tick = price_tick(price)
        atr = max(float(row.get("atr14") or price * .02), price * .008)
        trigger = round_to_tick(
            max(float(row.get("high") or price), price) + tick, tick
        )
        entry_limit = round_to_tick(trigger + tick * 2, tick)
        stop = round_to_tick(
            max(
                float(row.get("low") or price) - atr * .10,
                trigger - atr * .85,
            ),
            tick,
        )
        if stop >= trigger:
            stop = round_to_tick(trigger - max(tick, atr * .55), tick)
        risk_per_share = max(entry_limit - stop, tick)
        target1 = round_to_tick(entry_limit + risk_per_share * 1.5, tick)
        target2 = round_to_tick(entry_limit + risk_per_share * 2.2, tick)

        technical = expectation_score(row)
        sector_score = float(sector.get("score", 50))
        liquidity = (
            100 if row.get("turnover", 0) >= 10_000_000_000
            else 82 if row.get("turnover", 0) >= 5_000_000_000
            else 68
        )
        trend = (
            100 if price > row.get("ma5", price) > row.get("ma20", price)
            else 72 if price >= row.get("ma20", price)
            else 45
        )
        volume_score = clamp(float(row.get("rvol", 1)) * 55, 35, 100)
        change = float(row.get("change_pct") or 0)
        momentum = clamp(50 + change * 3.2, 20, 100)
        supply_known = all(
            supply.get(key) is not None
            for key in ("margin_buy_change_1w_pct", "credit_ratio")
        )
        if supply_known:
            margin_change = float(supply["margin_buy_change_1w_pct"])
            credit_ratio = float(supply["credit_ratio"])
            short_change = float(supply.get("institutional_short_change_pct") or 0)
            supply_score = clamp(
                55 - margin_change * 1.2 - max(credit_ratio - 2, 0) * 4
                - short_change * .8,
                10,
                100,
            )
            supply_status = (
                f"需給{round(supply_score)}点：買残1週{margin_change:+.1f}%／"
                f"倍率{credit_ratio:.2f}倍／機関空売り{short_change:+.1f}%"
            )
        else:
            # Price/volume absorption is useful context, but it is not credit
            # supply. Never promote it to a verified 8:55 order candidate.
            supply_score = 0
            supply_known = False
            supply_status = "信用買残・信用倍率未取得（正式候補へ昇格不可）"
        if not supply_known:
            continue
        focus_bonus = 12 if bucket else 0
        score = (
            technical * .18
            + sector_score * .10
            + liquidity * .13
            + trend * .10
            + volume_score * .25
            + momentum * .14
            + supply_score * .10
            + focus_bonus
        )
        if event_days is not None and 3 <= event_days <= 7:
            score -= 8
        score = round(clamp(score))

        shares = 100
        required_capital = round(entry_limit * shares)
        max_loss = round(risk_per_share * shares)
        expected_profit = round((target1 - entry_limit) * shares)
        rr = round(expected_profit / max_loss, 2) if max_loss else 0
        event_risk = (
            f"決算予定 {event['date']}（{event.get('source', '確認済み')}）。"
            "当日まで持ち越さない。"
            if event
            else "7日以内のJPX確認済み決算なし。突発IR・指数急変に注意。"
        )
        reason = (
            f"{bucket or '当日資金流入'}／{group}＝{phase} {sector_score:.0f}点／"
            f"前日比 {change:+.2f}%／出来高比 {row.get('rvol', 0):.2f}倍／"
            f"売買代金 {row.get('turnover', 0) / 100_000_000:.0f}億円／"
            f"テクニカル {technical}点／{supply_status}"
        )
        eligible.append({
            "name": name,
            "code": code,
            "ticker": row.get("ticker", ""),
            "side": "LONG",
            "sector": group,
            "day_bucket": bucket or "当日資金流入",
            "supply_verified": supply_known,
            "supply_status": supply_status,
            "sector_phase": phase,
            "score": score,
            "shares": shares,
            "trigger": trigger,
            "entry_limit": entry_limit,
            "stop": stop,
            "target1": target1,
            "target2": target2,
            "required_capital": required_capital,
            "max_loss": max_loss,
            "expected_profit": expected_profit,
            "risk_reward": rr,
            "reason": reason,
            "event_risk": event_risk,
            "order_type": "逆指値注文＋IFO（利益確定＋損切り）",
            "market": "東証（SOR）",
            "credit_type": "制度（6カ月）",
            "entry_expiry": "当日中",
            "exit_expiry": "当日中",
            "quote_rule": (
                f"8:55気配が{entry_limit:,.1f}円を超えていたら価格を上げず注文取消。"
                if tick < 1 else
                f"8:55気配が{entry_limit:,.0f}円を超えていたら価格を上げず注文取消。"
            ),
            "chart": row.get("chart", []),
            "data_date": row.get("data_date"),
            "chart_last_close": row.get("chart_last_close"),
            "quote_status": row.get("quote_status", "株価検証不能"),
            "close_rule": (
                "15:20時点で未決済なら手仕舞い判断。持ち越す場合は、"
                "失効する決済注文を必ずOCOで再設定。"
            ),
        })

    eligible.sort(
        key=lambda x: (
            x["score"],
            x["risk_reward"],
            -x["max_loss"],
        ),
        reverse=True,
    )

    selected = []

    def take(bucket_names, count):
        for item in eligible:
            if item in selected or item["day_bucket"] not in bucket_names:
                continue
            selected.append(item)
            if sum(x["day_bucket"] in bucket_names for x in selected) >= count:
                break

    # Daily core: two speculative/IPO-growth names and two SaaS/AI software
    # names.  The fifth slot goes to the strongest remaining flow candidate.
    take({"テーマ・マネーゲーム", "IPO・グロース"}, 2)
    take({"SaaS・AIソフト"}, 2)
    for item in eligible:
        if item not in selected:
            selected.append(item)
        if len(selected) == 5:
            break
    return selected


def build_silicon_photonics_watch(stocks, official_earnings, now):
    """Create conditional IN/OUT levels for the morning CPO theme watch.

    Levels are based on the latest completed daily bar.  The trigger is one
    valid tick above that bar's high, so the list never means "buy at open".
    """
    rows = []
    for meta in SILICON_PHOTONICS_WATCH:
        row = stocks.get(meta["name"], {})
        if not row.get("ok"):
            continue

        price = float(row.get("price") or 0)
        high = float(row.get("high") or price)
        low = float(row.get("low") or price)
        atr = max(float(row.get("atr14") or price * .02), price * .008)
        tick = price_tick(price)
        trigger = round_to_tick(max(price, high) + tick, tick)
        entry_limit = round_to_tick(trigger + tick * 2, tick)
        stop = round_to_tick(
            max(low - atr * .10, entry_limit - atr * .85),
            tick,
        )
        if stop >= entry_limit:
            stop = round_to_tick(entry_limit - max(tick, atr * .55), tick)
        risk = max(entry_limit - stop, tick)
        target1 = round_to_tick(entry_limit + risk * 1.5, tick)
        target2 = round_to_tick(entry_limit + risk * 2.2, tick)

        technical = expectation_score(row)
        score = round(clamp(meta["relevance"] * .55 + technical * .45))
        event = official_earnings.get(meta["code"])
        event_days = None
        if event and event.get("date"):
            event_days = (pd.Timestamp(event["date"]).date() - now.date()).days
            if 0 <= event_days <= 2:
                score = max(0, score - 12)
        event_risk = (
            f"決算予定 {event['date']}。決算前の新規持ち越しは見送り。"
            if event and event_days is not None and event_days >= 0
            else "7日以内のJPX確認済み決算なし。突発IR・米半導体安に注意。"
        )
        status = (
            "決算接近・原則見送り"
            if event_days is not None and 0 <= event_days <= 2
            else "条件成立時だけLONG"
        )
        max_loss = round((entry_limit - stop) * 100)
        profit1 = round((target1 - entry_limit) * 100)
        rows.append({
            **meta,
            "score": score,
            "technical": technical,
            "price": price,
            "trigger": trigger,
            "entry_limit": entry_limit,
            "stop": stop,
            "target1": target1,
            "target2": target2,
            "max_loss_100": max_loss,
            "profit1_100": profit1,
            "status": status,
            "event_risk": event_risk,
            "condition": (
                "9:15以降、VWAP上＋5分足終値で発動価格を維持＋"
                "出来高増加。大幅GUと寄り直後の飛び乗りは禁止。"
            ),
        })

    rows.sort(key=lambda x: (x["score"], x["relevance"]), reverse=True)
    return rows


def render_day_ifo_cards(candidates):
    if not candidates:
        return (
            "<div class='rotation-box'>本日の短期資金・流動性・過熱度条件に"
            "合格した注文候補なし。無条件の注文は出しません。</div>"
        )
    cards = []
    for rank, item in enumerate(candidates, 1):
        cards.append(f"""
<article class="ifo-card">
  <div class="ifo-head">
    <span class="ifo-rank">#{rank}</span>
    <div><h3>{item['name']}</h3><small>{item['day_bucket']}／{item['sector']}／{item['sector_phase']}</small></div>
    <b class="ifo-score">{item['score']}/100</b>
  </div>
  <div class="ifo-columns">
    <div class="order-box entry-order">
      <b>左側｜信用新規・買建</b>
      <dl>
        <dt>市場</dt><dd>{item['market']}</dd>
        <dt>信用区分</dt><dd>{item['credit_type']}</dd>
        <dt>数量</dt><dd><strong>{item['shares']}株</strong></dd>
        <dt>新規注文</dt><dd>逆指値注文</dd>
        <dt>市場価格が</dt><dd><strong>{money(item['trigger'])}円以上</strong></dd>
        <dt>買い指値</dt><dd><strong>{money(item['entry_limit'])}円</strong></dd>
        <dt>執行期限</dt><dd>{item['entry_expiry']}</dd>
      </dl>
    </div>
    <div class="order-box exit-order">
      <b>右側｜IFO（利益確定＋損切り）</b>
      <dl>
        <dt>利益確定</dt><dd>売埋・指値 <strong class="up">{money(item['target1'])}円</strong></dd>
        <dt>損切り条件</dt><dd>市場価格が <strong class="down">{money(item['stop'])}円以下</strong></dd>
        <dt>損切り注文</dt><dd>成行</dd>
        <dt>執行期限</dt><dd>{item['exit_expiry']}</dd>
        <dt>利確2参考</dt><dd>{money(item['target2'])}円（注文には未入力）</dd>
      </dl>
    </div>
  </div>
  <div class="ifo-metrics">
    <span>建玉目安 <b>{item['required_capital']:,}円</b></span>
    <span>利確時 <b class="up">+{item['expected_profit']:,}円</b></span>
    <span>最大損失 <b class="down">−{item['max_loss']:,}円</b></span>
    <span>RR <b>{item['risk_reward']:.2f}</b></span>
  </div>
  <p><b>選定理由：</b>{item['reason']}</p>
  <p class="warning"><b>8:55確認：</b>{item['quote_rule']}</p>
  <p><small>{item['event_risk']} {item['close_rule']}</small></p>
</article>""")
    return "".join(cards)


def render_focus_dashboard(candidates):
    """A compact, self-contained trading surface with a native price chart."""
    if not candidates:
        return """<section id="action-dashboard" class="card wide focus-dashboard"><div class="focus-empty"><b>本日は見送り</b><span>条件を満たす候補がありません</span></div></section>"""
    rows = []
    for rank, item in enumerate(candidates[:5], 1):
        risk = max(float(item["entry_limit"]) - float(item["stop"]), 0)
        supply_ok = item.get("supply_verified", False)
        decision = "本命・発動待ち" if rank == 1 and supply_ok and item.get("score", 0) >= 80 else "発動待ち" if supply_ok else "需給確認待ち"
        rows.append({
            "rank": rank, "name": item["name"], "code": item["code"],
            "score": item["score"], "decision": decision,
            "decision_class": "go" if decision.startswith("本命") else "ready" if supply_ok else "wait",
            "trigger": item["trigger"], "entry": item["entry_limit"],
            "pullback_low": round(float(item["entry_limit"]) - risk * .55, 2),
            "pullback_high": round(float(item["entry_limit"]) - risk * .25, 2),
            "stop": item["stop"], "target1": item["target1"], "target2": item["target2"],
            "supply": item.get("supply_status", "信用需給未確認"),
            "reason": item["reason"], "chart": item.get("chart", []),
            "data_date": item.get("data_date"),
            "chart_last_close": item.get("chart_last_close"),
            "quote_status": item.get("quote_status", "株価検証不能"),
        })
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    return f"""
<section id="action-dashboard" class="card wide focus-dashboard">
 <div class="focus-topbar">
  <div><span class="focus-eyebrow">TODAY'S SETUPS</span><h2>今買う候補</h2></div>
  <div class="focus-legend"><span><i class="dot green"></i>発動</span><span><i class="dot amber"></i>押し目</span><span><i class="dot red"></i>撤退</span></div>
 </div>
 <div class="focus-layout">
  <aside><div class="focus-aside-head"><b>優先順位</b><small>最大5銘柄</small></div><div class="focus-picks" id="focus-picks"></div></aside>
  <div class="focus-chart-wrap">
   <div class="focus-chart-head"><div><b id="focus-chart-name"></b><small id="focus-chart-code"></small></div><span id="focus-chart-asof">検証中</span></div>
   <div id="focus-chart" role="img" aria-label="ローソク足チャート"></div>
  </div>
  <div class="focus-order">
   <div class="focus-symbol"><span id="focus-rank"></span><div><small>SELECTED</small><h3 id="focus-name"></h3></div><b id="focus-score"></b></div>
   <div id="focus-decision" class="decision-badge"></div>
   <div class="focus-action"><span>買い発動ライン</span><strong id="focus-trigger"></strong><small>ローソク足確定・VWAP上・出来高増加</small></div>
   <div class="focus-price-grid">
    <div><span>買い上限</span><b id="focus-entry"></b></div><div><span>押し目ゾーン</span><b id="focus-pullback"></b></div>
    <div><span>撤退ライン</span><b class="down" id="focus-stop"></b></div><div><span>利確 1 / 2</span><b class="up" id="focus-targets"></b></div>
   </div>
   <div class="focus-supply"><span>CREDIT FLOW</span><p id="focus-supply"></p></div>
   <details><summary>選定根拠を見る</summary><p id="focus-reason"></p></details>
  </div>
 </div>
 <div class="focus-rule"><b>飛び乗り禁止</b><span>発動ラインを勢いよく通過したら追わない。押し目ゾーンで反発足が確定するまで待つ。</span></div>
</section>
<script>
document.addEventListener("DOMContentLoaded",()=>{{
 const rows={payload}, yen=n=>Number(n).toLocaleString("ja-JP",{{maximumFractionDigits:1}})+"円";
 const list=document.getElementById("focus-picks");
 rows.forEach((x,i)=>{{const b=document.createElement("button");b.className="focus-pick";b.innerHTML=`<span class="focus-rank">${{String(i+1).padStart(2,"0")}}</span><span><b>${{x.name}}</b><small>${{x.decision}}</small></span><strong>${{x.score}}</strong>`;b.onclick=()=>select(i);list.appendChild(b);}});
 function chart(x){{const a=x.chart||[];if(!a.length)return `<div class="chart-empty">チャートデータ更新待ち</div>`;const W=720,H=390,p=28;let lo=Math.min(...a.map(v=>v.l),x.stop),hi=Math.max(...a.map(v=>v.h),x.trigger,x.target1);const y=v=>p+(hi-v)/(hi-lo||1)*(H-p*2),step=(W-p*2)/a.length,bw=Math.max(3,step*.55);let s=`<svg viewBox="0 0 ${{W}} ${{H}}" preserveAspectRatio="none">`;for(let i=0;i<5;i++){{let yy=p+i*(H-p*2)/4;s+=`<line class="grid" x1="${{p}}" y1="${{yy}}" x2="${{W-p}}" y2="${{yy}}"/>`;}}a.forEach((v,i)=>{{let x0=p+step*(i+.5),up=v.c>=v.o,cl=up?"c-up":"c-down",yo=y(v.o),yc=y(v.c);s+=`<line class="${{cl}}" x1="${{x0}}" y1="${{y(v.h)}}" x2="${{x0}}" y2="${{y(v.l)}}"/><rect class="${{cl}}" x="${{x0-bw/2}}" y="${{Math.min(yo,yc)}}" width="${{bw}}" height="${{Math.max(1,Math.abs(yo-yc))}}"/>`;}});[[x.trigger,"trigger","発動"],[x.pullback_high,"pullback","押し目"],[x.stop,"stop","撤退"]].forEach(z=>{{s+=`<line class="level ${{z[1]}}" x1="${{p}}" y1="${{y(z[0])}}" x2="${{W-p}}" y2="${{y(z[0])}}"/><text class="label ${{z[1]}}" x="${{W-p-3}}" y="${{y(z[0])-5}}">${{z[2]}} ${{yen(z[0])}}</text>`;}});return s+`</svg>`;}}
 function select(i){{const x=rows[i];[...list.children].forEach((b,j)=>b.classList.toggle("active",i===j));document.getElementById("focus-chart-name").textContent=x.name;document.getElementById("focus-chart-code").textContent=x.code;document.getElementById("focus-chart-asof").textContent=(x.data_date||"日付未確認")+" 終値 "+yen(x.chart_last_close);document.getElementById("focus-chart").innerHTML=chart(x);document.getElementById("focus-rank").textContent="#"+x.rank;document.getElementById("focus-name").textContent=x.name;document.getElementById("focus-score").textContent=x.score+" / 100";const d=document.getElementById("focus-decision");d.className="decision-badge "+x.decision_class;d.textContent=x.decision;document.getElementById("focus-trigger").textContent=yen(x.trigger)+" 以上";document.getElementById("focus-entry").textContent=yen(x.entry);document.getElementById("focus-pullback").textContent=yen(x.pullback_low)+" – "+yen(x.pullback_high);document.getElementById("focus-stop").textContent=yen(x.stop);document.getElementById("focus-targets").textContent=yen(x.target1)+" / "+yen(x.target2);document.getElementById("focus-supply").textContent=x.supply+"／"+x.quote_status;document.getElementById("focus-reason").textContent=x.reason;}}
 select(0);
}});
</script>"""


def render_trade_drawer():
    return r"""
<div id="trade-drawer-backdrop" aria-hidden="true"></div>
<aside id="trade-drawer" aria-label="銘柄チャートと売買判断" aria-hidden="true">
 <div class="drawer-head"><div><span>QUICK TRADE VIEW</span><h2 id="drawer-name">銘柄チャート</h2></div><button id="drawer-close" type="button" aria-label="閉じる">×</button></div>
 <div class="drawer-grid">
  <div id="drawer-chart" class="drawer-chart"></div>
  <div class="drawer-plan">
   <div id="drawer-status" class="drawer-status">判定中</div>
   <div class="drawer-main"><span>売買発動</span><strong id="drawer-trigger">—</strong><small id="drawer-confirm">ローソク足確定と出来高を確認</small></div>
   <div class="drawer-levels"><div><span>押し目</span><b id="drawer-pullback">—</b></div><div><span>損切り</span><b id="drawer-stop" class="down">—</b></div><div><span>利確1</span><b id="drawer-target1" class="up">—</b></div><div><span>利確2</span><b id="drawer-target2">—</b></div></div>
   <p id="drawer-note"></p>
  </div>
 </div>
</aside>
<script>
document.addEventListener("DOMContentLoaded",()=>{
 const drawer=document.getElementById("trade-drawer"),back=document.getElementById("trade-drawer-backdrop"),yen=n=>Number(n).toLocaleString("ja-JP",{maximumFractionDigits:1})+"円",records={};
 const close=()=>{drawer.classList.remove("open");back.classList.remove("open");drawer.setAttribute("aria-hidden","true")};document.getElementById("drawer-close").onclick=close;back.onclick=close;
 const codeOf=(v,key="")=>String(v?.code||v?.ticker||key).match(/(?:TSE:)?([0-9A-Z]{3,5})(?:\.T)?(?:）)?/)?.[1];
 function walk(v,key=""){if(Array.isArray(v)){v.forEach(x=>walk(x,key));return}if(!v||typeof v!=="object")return;const code=codeOf(v,key);if(code){const old=records[code]||{},incomingDate=String(v.data_date||""),oldDate=String(old.data_date||""),useIncoming=!oldDate||(incomingDate&&incomingDate>=oldDate),chart=useIncoming&&(v.chart||[]).length?v.chart:old.chart,merged=useIncoming?{...old,...v}:{...v,...old};records[code]={...merged,chart,name:(useIncoming?v.name:old.name)||v.name||old.name||(key.includes("（")?key:key+"（"+code+"）")}}Object.entries(v).forEach(([k,x])=>{if(typeof x==="object")walk(x,k)})}
 function chartSvg(x,levels){const a=x.chart||[];if(!a.length)return '<div class="drawer-empty">チャートデータ更新待ち</div>';const W=900,H=430,p=30,vals=[...a.flatMap(v=>[v.h,v.l]),levels.trigger,levels.stop,levels.target1].filter(Number.isFinite),lo=Math.min(...vals),hi=Math.max(...vals),y=v=>p+(hi-v)/(hi-lo||1)*(H-p*2),step=(W-p*2)/a.length,bw=Math.max(3,step*.55);let s=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`;for(let i=0;i<5;i++){const yy=p+i*(H-p*2)/4;s+=`<line class="grid" x1="${p}" y1="${yy}" x2="${W-p}" y2="${yy}"/>`}a.forEach((v,i)=>{const xx=p+step*(i+.5),cl=v.c>=v.o?"c-up":"c-down",yo=y(v.o),yc=y(v.c);s+=`<line class="${cl}" x1="${xx}" y1="${y(v.h)}" x2="${xx}" y2="${y(v.l)}"/><rect class="${cl}" x="${xx-bw/2}" y="${Math.min(yo,yc)}" width="${bw}" height="${Math.max(1,Math.abs(yo-yc))}"/>`});[[levels.trigger,"trigger","発動"],[levels.pullback,"pullback","押し目"],[levels.stop,"stop","撤退"]].forEach(z=>{s+=`<line class="level ${z[1]}" x1="${p}" y1="${y(z[0])}" x2="${W-p}" y2="${y(z[0])}"/><text class="label ${z[1]}" x="${W-p-3}" y="${y(z[0])-5}">${z[2]} ${yen(z[0])}</text>`});return s+"</svg>"}
 function openChart(code){const x=records[code];if(!x)return;const a=x.chart||[],last=Number(x.close||x.price||a.at(-1)?.c||0),hi=Math.max(...a.slice(-20).map(v=>v.h)),lo=Math.min(...a.slice(-10).map(v=>v.l)),official=Number.isFinite(Number(x.trigger))&&Number.isFinite(Number(x.stop)),short=official&&Number(x.target1)<Number(x.trigger),tick=last<3000?1:last<5000?5:last<30000?10:last<50000?50:100,trigger=Number(x.trigger)||(short?lo-tick:hi+tick),stop=Number(x.stop)||(short?hi:lo),risk=Math.max(Math.abs(trigger-stop),tick),target1=Number(x.target1)||(short?trigger-risk*1.5:trigger+risk*1.5),target2=Number(x.target2)||(short?trigger-risk*2.2:trigger+risk*2.2),pullback=short?trigger+risk*.35:trigger-risk*.35;let status="発動待ち",cls="ready";if((!short&&last>=trigger)|| (short&&last<=trigger)){status=Math.abs(last-trigger)<=risk*.5?"発動確認・ローソク足待ち":"走り過ぎ・追わない";cls=status.startsWith("発動")?"go":"wait"}if((!short&&last<=stop)||(short&&last>=stop)){status="条件崩れ・見送り";cls="stop"}const levels={trigger,stop,target1,target2,pullback};document.getElementById("drawer-name").textContent=x.name||code;document.getElementById("drawer-chart").innerHTML=chartSvg(x,levels);const st=document.getElementById("drawer-status");st.className="drawer-status "+cls;st.textContent=status;document.getElementById("drawer-trigger").textContent=(short?"売り ":"買い ")+yen(trigger)+(short?" 以下":" 以上");document.getElementById("drawer-pullback").textContent=yen(pullback);document.getElementById("drawer-stop").textContent=yen(stop);document.getElementById("drawer-target1").textContent=yen(target1);document.getElementById("drawer-target2").textContent=yen(target2);document.getElementById("drawer-confirm").textContent=short?"反落足確定・VWAP下・出来高増加":"反発足確定・VWAP上・出来高増加";document.getElementById("drawer-note").textContent=official?"正式候補の注文ライン。発動条件を満たさなければ見送り。":"参考ライン。監視銘柄から自動計算したため、正式候補へ昇格するまで注文しない。";drawer.classList.add("open");back.classList.add("open");drawer.setAttribute("aria-hidden","false")}
 function enhance(){document.querySelectorAll(".tab-pane table tbody tr,.tab-pane table>tr").forEach(tr=>{if(tr.dataset.chartReady)return;const code=tr.textContent.match(/（([0-9A-Z]{3,5})）/)?.[1];if(!code||!records[code]?.chart?.length)return;tr.dataset.chartReady="1";tr.classList.add("chart-row");const cell=[...tr.cells].find(td=>td.textContent.includes("（"+code+"）"))||tr.cells[1]||tr.cells[0];const b=document.createElement("button");b.type="button";b.className="chart-open";b.textContent="▥ チャート";b.onclick=e=>{e.stopPropagation();openChart(code)};cell.appendChild(b)})}
 Promise.all([fetch("data.json?t="+Date.now()).then(r=>r.json()),fetch("signals.json?t="+Date.now()).then(r=>r.json())]).then(([a,b])=>{walk(a);walk(b);enhance();setTimeout(enhance,700);setTimeout(enhance,1800)}).catch(()=>{});
});
</script>"""


def main():
    now = datetime.now(JST)
    active_buybacks, buybacks_updated_at = load_active_buybacks(now)
    credit_supply, credit_supply_updated_at = load_credit_supply_map()
    session_override = os.getenv("COCKPIT_SESSION", "auto").strip().lower()
    if session_override in {"morning", "midday", "close"}:
        session = session_override
    elif now.hour < 11:
        session = "morning"
    elif now.hour < 14 or (now.hour == 14 and now.minute < 30):
        session = "midday"
    else:
        # 14:45 JST run: build the pre-close carry edition in time for 15:00.
        session = "close"
    intraday_mode = session != "morning"
    config = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    previous = {}
    data_path = ROOT / "data.json"
    if data_path.exists():
        try:
            previous = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    offline_render = os.getenv("COCKPIT_OFFLINE_RENDER", "0") == "1"
    if offline_render:
        # Rebuild the page shell (calendar/tabs/safety notices) without
        # touching quotes. This mode never upgrades a stale quote to valid.
        indices = previous.get("indices", {})
        stocks = previous.get("stocks", {})
    else:
        stock_tickers = [meta["ticker"] for meta in config["stocks"].values()]
        secondary_quotes = fetch_secondary_quotes(stock_tickers)
        indices = {name: daily_snapshot(ticker) for name, ticker in config["indices"].items()}
        stocks = {}
        for name, meta in config["stocks"].items():
            row = daily_snapshot(meta["ticker"], secondary_quotes.get(meta["ticker"]))
            row.update({
                "ticker": meta["ticker"],
                "sector": meta["sector"],
                "style": meta["style"],
                "day_bucket": meta.get("day_bucket"),
            })
            if intraday_mode and row.get("ok"):
                row["intraday"] = intraday_snapshot(meta["ticker"])
            stocks[name] = row

    # A missing/stale quote produces zero candidates rather than a plausible
    # looking but wrong order ticket. This gate applies to every ranking.
    valid = [
        (n, r) for n, r in stocks.items()
        if r.get("ok") and r.get("quote_verified")
    ]
    akita_dc_watch = []
    for item in config.get("akita_dc_watch", []):
        market = stocks.get(item["name"], {})
        if market.get("ok"):
            akita_dc_watch.append({**item, **market})
    akita_dc_watch.sort(
        key=lambda x: (
            x.get("relation_score", 0),
            x.get("rvol", 0),
            x.get("change_pct", 0),
        ),
        reverse=True,
    )
    akita_dc_watch = akita_dc_watch[:5]
    gunma_rare_earth_watch = []
    for item in config.get("gunma_rare_earth_watch", []):
        market = stocks.get(item["name"], {})
        if market.get("ok"):
            gunma_rare_earth_watch.append({**item, **market})
    gunma_rare_earth_watch.sort(
        key=lambda x: (
            x.get("relation_score", 0),
            x.get("rvol", 0),
            x.get("change_pct", 0),
        ),
        reverse=True,
    )
    gunma_rare_earth_watch = gunma_rare_earth_watch[:5]
    rotation = build_sector_rotation(indices, valid)
    day_pool = []
    for n, r in valid:
        if r["style"] not in ("day", "both") or r["turnover"] < 2_000_000_000 or not r.get("market_supply_improved"):
            continue
        lifecycle = material_lifecycle(r)
        r["material_stage"] = lifecycle["stage"]
        r["material_action"] = lifecycle["action"]
        r["actionable_day_score"] = round(r["day_score"] - lifecycle["priority_penalty"], 2)
        day_pool.append((n, r))
    day_rank = sorted(day_pool, key=lambda x: x[1]["actionable_day_score"], reverse=True)[:5]
    swing_pool = [
        (n, r) for n, r in valid
        if r["style"] in ("swing", "both") and 500 <= r["price"] <= 30000
        and r["turnover"] >= 500_000_000 and r.get("market_supply_improved")
    ]
    stable_rank = sorted(
        [(n, r) for n, r in swing_pool
         if r["price"] > r["ma20"] > r["ma60"] and r["atr_pct"] <= 5.0],
        key=lambda x: x[1]["stable_score"], reverse=True
    )[:5]
    momentum_rank = sorted(
        [(n, r) for n, r in swing_pool
         if r["ret20"] >= 5 and r["from_ma20"] <= 18
         and r["price"] >= r["ma5"] and (r["touch_ma5"] or r["from_ma5"] <= 5)],
        key=lambda x: x[1]["momentum_score"], reverse=True
    )[:5]
    high_rank = sorted(
        [(n, r) for n, r in swing_pool if r["to_high52"] >= -5],
        key=lambda x: x[1]["high_score"], reverse=True
    )[:5]
    overheated_rank = sorted(
        [(n, r) for n, r in swing_pool
         if r["ret5"] >= 8 and r["ret20"] >= 15
         and (r["from_ma20"] > 12 or r["atr_pct"] > 7)],
        key=lambda x: x[1]["momentum_score"], reverse=True
    )[:5]
    bb_rank = sorted(
        [(n, r) for n, r in swing_pool
         if (r["bb_percentile"] <= 35
             or (r["bb_width_change"] > 0 and r["price"] >= r["ma20"]))],
        key=lambda x: x[1]["bb_expansion_score"], reverse=True
    )[:7]

    sector_scores = {}
    sector_members = {}
    for name, r in valid:
        sector_scores.setdefault(r["sector"], []).append(r["day_score"])
        sector_members.setdefault(r["sector"], []).append((name, r["day_score"], r["change_pct"]))
    themes = sorted(
        ((k, sum(v) / len(v), len(v),
          sorted(sector_members[k], key=lambda x: x[1], reverse=True)[:3])
         for k, v in sector_scores.items()),
        key=lambda x: x[1], reverse=True
    )[:5]

    # A policy association alone is not a trade thesis.  Keep official/company
    # evidence, business exposure and verified credit supply separate.
    policy_theme_specs = [
        ("physical-ai", "フィジカルAI", "https://www.cas.go.jp/jp/seisaku/nipponseichosenryaku/pdf/rm2026.pdf", [
            ("ファナック（6954）", "フィジカルAIロボット本体・制御", 98, 70, "https://www.fanuc.co.jp/ja/profile/pr/newsrelease/2026/news20260513.html"),
            ("安川電機（6506）", "AIロボット MOTOMAN NEXT", 98, 72, "https://www.yaskawa.co.jp/motoman-next/"),
            ("ハーモニック・ドライブ・システムズ（6324）", "ロボット用精密減速機", 82, 88, "https://www.hds.co.jp/company/about/"),
            ("ナブテスコ（6268）", "ロボット関節用精密減速機", 80, 78, "https://www.nabtesco.com/products/precision-reduction-gears/"),
        ]),
        ("autonomous-driving", "自動運転", "https://www.meti.go.jp/policy/mono_info_service/mono/automobile/index.html", [
            ("ティアフォー（593A）", "Autoware・自動運転システム", 100, 95, "https://tier4.co.jp/"),
            ("アイサンテクノロジー（4667）", "高精度3次元地図・運行支援", 92, 58, "https://www.aisantec.co.jp/information/5412/"),
            ("デンソー（6902）", "車載半導体・センシング・制御", 78, 35, "https://www.denso.com/jp/ja/business/automotive/mobility/"),
        ]),
        ("ai-drug-discovery", "AI創薬", "https://www.meti.go.jp/policy/mono_info_service/geniac/selection_2/index.html", [
            ("FRONTEO（2158）", "AI創薬支援 DDAIF", 96, 55, "https://lifescience.fronteo.com/products/drug-discovery-ai-factory"),
            ("NEC（6701）", "AI創薬・個別化がんワクチン", 90, 18, "https://jpn.nec.com/solution/ai-drug/index.html"),
        ]),
        ("ai-semiconductor", "AI・半導体基盤", "https://www.cas.go.jp/jp/seisaku/nipponseichosenryaku/pdf/rm2026.pdf", [
            ("キオクシアHD（285A）", "AI向けNAND・SSD", 92, 95, "https://www.kioxia-holdings.com/ja-jp/ir.html"),
            ("東京エレクトロン（8035）", "先端半導体製造装置", 94, 88, "https://www.tel.co.jp/ir/"),
            ("アドバンテスト（6857）", "AI半導体テスト", 94, 92, "https://www.advantest.com/investors/"),
            ("ディスコ（6146）", "先端半導体切断・研削", 88, 90, "https://www.disco.co.jp/jp/ir/"),
            ("ソシオネクスト（6526）", "先端SoC設計", 86, 82, "https://www.socionext.com/jp/ir/"),
        ]),
        ("defense-space", "防衛・宇宙", "https://www.cas.go.jp/jp/seisaku/nipponseichosenryaku/pdf/rm2026.pdf", [
            ("三菱重工業（7011）", "防衛装備・ロケット・宇宙", 98, 78, "https://www.mhi.com/jp/finance"),
            ("IHI（7013）", "航空エンジン・宇宙推進", 92, 62, "https://www.ihi.co.jp/ir/"),
            ("三菱電機（6503）", "防衛電子・衛星", 90, 45, "https://www.mitsubishielectric.co.jp/ir/"),
            ("QPS研究所（5595）", "小型SAR衛星・官公庁案件", 98, 95, "https://i-qps.net/ir/"),
        ]),
        ("gx-power", "GX・電力基盤", "https://www.cas.go.jp/jp/seisaku/nipponseichosenryaku/pdf/rm2026.pdf", [
            ("富士電機（6504）", "パワー半導体・電力設備", 90, 68, "https://www.fujielectric.co.jp/about/ir/"),
            ("日立製作所（6501）", "送配電・系統デジタル化", 88, 38, "https://www.hitachi.co.jp/IR/"),
            ("パワーエックス（485A）", "大型蓄電池・電力供給", 95, 95, "https://power-x.jp/ir"),
            ("住友電気工業（5802）", "送電ケーブル・電力網", 85, 48, "https://sumitomoelectric.com/jp/ir"),
        ]),
        ("quantum-computing", "量子・先端計算", "https://www.cas.go.jp/jp/seisaku/nipponseichosenryaku/pdf/rm2026.pdf", [
            ("富士通（6702）", "量子計算・HPC", 92, 15, "https://www.fujitsu.com/jp/about/research/technology/quantum/"),
            ("NEC（6701）", "量子アニーリング・量子暗号", 90, 12, "https://jpn.nec.com/quantum_annealing/"),
            ("NTT（9432）", "光・量子技術", 88, 10, "https://group.ntt/jp/rd/technology/quantum.html"),
        ]),
    ]
    valid_map = dict(valid)
    policy_theme_tabs = []
    for slug, title, policy_source, members in policy_theme_specs:
        ranked = []
        for name, role, directness, business_impact, evidence in members:
            r = valid_map.get(name)
            if not r:
                continue
            code = str(r.get("ticker", "")).split(".")[0]
            supply = credit_supply.get(code, {})
            supply_known = all(supply.get(k) is not None for k in ("margin_buy_change_1w_pct", "margin_buy_change_4w_pct", "credit_ratio"))
            if supply_known:
                m1 = float(supply["margin_buy_change_1w_pct"])
                m4 = float(supply["margin_buy_change_4w_pct"])
                ratio = float(supply["credit_ratio"])
                short = float(supply.get("institutional_short_change_pct") or 0)
                buybacks = float(supply.get("institutional_buyback_firms") or 0)
                credit70 = round(clamp(38 - m1 * .8 - m4 * .25 - max(ratio - 2, 0) * 3 - short * .45 + buybacks * 3, 0, 70))
                deteriorating = (m1 > 5 and r.get("change_pct", 0) < 0) or (short > 5 and buybacks == 0)
                supply_text = f"信用{credit70}/70｜買残1週{m1:+.1f}%・4週{m4:+.1f}%｜倍率{ratio:.2f}｜機関{short:+.1f}%"
            else:
                credit70, deteriorating = 0, False
                supply_text = "信用需給未取得（正式候補へ昇格不可）"
            p = trade_plan(r, r.get("intraday"))
            technical = round(clamp(50 + r.get("change_pct", 0) * 4 + (10 if r.get("price", 0) >= r.get("ma20", 0) else -10) + min(r.get("rvol", 0), 2) * 8, 0, 100))
            liquidity = 100 if r.get("turnover", 0) >= 10_000_000_000 else 80 if r.get("turnover", 0) >= 2_000_000_000 else 55
            total = round(directness * .25 + business_impact * .15 + (credit70 / 70 * 100) * .35 + technical * .15 + liquidity * .10)
            formal = supply_known and credit70 >= 45 and total >= 70 and not deteriorating
            status = "正式候補" if formal else "需給悪化で除外" if deteriorating else "信用需給待ち" if not supply_known else "監視のみ"
            ranked.append({"name": name, "role": role, "directness": directness, "business_impact": business_impact, "evidence": evidence, "credit70": credit70, "supply_known": supply_known, "supply_text": supply_text, "formal": formal, "status": status, "score": total, "plan": p, **r})
        ranked.sort(key=lambda x: (x["formal"], x["score"], x["directness"]), reverse=True)
        formal_count = sum(x["formal"] for x in ranked)
        best_score = max((x["score"] for x in ranked if x["formal"]), default=0)
        policy_theme_tabs.append({"slug": slug, "title": title, "source": policy_source, "formal_count": formal_count, "best_score": best_score, "candidates": ranked[:5]})
    policy_theme_tabs.sort(key=lambda x: (x["formal_count"], x["best_score"]), reverse=True)
    for priority, theme in enumerate(policy_theme_tabs, 1):
        theme["priority"] = priority

    official_earnings = jpx_earnings_map(now)
    for code, item in config.get("earnings_overrides", {}).items():
        delta = (pd.Timestamp(item["date"]).date() - now.date()).days
        if -1 <= delta <= 7:
            official_earnings[code] = item
    earnings = []
    for name, r in valid:
        code = r["ticker"].split(".")[0]
        official = official_earnings.get(code)
        dt = official["date"] if official else earnings_date(r["ticker"], now)
        if dt:
            p = trade_plan(r, r.get("intraday"))
            technical = expectation_score(r, earnings=True)
            fundamental = earnings_expectation(r["ticker"], technical)
            earnings.append({
                "name": name, "date": dt, "price": r["price"], "plan": p,
                "source": official["source"] if official else "Yahoo予想",
                "expectation_score": fundamental["score"],
                "raw_expectation_score": fundamental["raw_score"],
                "hurdle_risk": fundamental["hurdle_risk"],
                "score_coverage": fundamental["coverage"],
                "score_detail": fundamental["detail"],
                "technical_score": technical
            })
    earnings.sort(key=lambda x: (-x["expectation_score"], x["date"]))
    earnings = earnings[:15]

    generated_day_ifo = build_day_ifo_candidates(
        valid, rotation, official_earnings, now, credit_supply
    )
    generated_photonics_watch = build_silicon_photonics_watch(
        stocks, official_earnings, now
    )
    previous_morning = previous.get("morning_snapshot") or {}
    same_day_snapshot = previous_morning.get("date") == now.strftime("%Y-%m-%d")
    if session == "morning" or not same_day_snapshot:
        day_ifo_candidates = generated_day_ifo
        photonics_watch = generated_photonics_watch
    else:
        day_ifo_candidates = (
            previous.get("day_ifo_candidates") or generated_day_ifo
        )
        photonics_watch = (
            previous.get("silicon_photonics_watch")
            or generated_photonics_watch
        )

    morning = previous_morning
    if session == "morning":
        morning = {
            "date": now.strftime("%Y-%m-%d"),
            "fixed_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
            "rule": (
                "8:55に気配確認。発動価格以上かつ買い指値上限以内の時だけ"
                "100株IFOを手入力。"
            ),
            "candidates": [
                {
                    "name": item["name"],
                    "ticker": item["ticker"],
                    "side": item["side"],
                    "score": item["score"],
                    "price": stocks.get(item["name"], {}).get("price"),
                    "plan": {
                        "entry": item["trigger"],
                        "entry_limit": item["entry_limit"],
                        "stop": item["stop"],
                        "target1": item["target1"],
                        "target2": item["target2"],
                    },
                }
                for item in day_ifo_candidates
            ],
        }

    reviews = []
    if intraday_mode and morning and morning.get("date") == now.strftime("%Y-%m-%d"):
        for item in morning.get("candidates", []):
            row = stocks.get(item["name"], {})
            reviews.append({
                "name": item["name"], "plan": item["plan"],
                **review_trade(item["plan"], row.get("intraday"))
            })

    total_capital = sum(x["required_capital"] for x in day_ifo_candidates)
    total_profit = sum(x["expected_profit"] for x in day_ifo_candidates)
    total_loss = sum(x["max_loss"] for x in day_ifo_candidates)
    data = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "phase": (
            "寄り付き前8:00版" if session == "morning"
            else "前場検証11:45版" if session == "midday"
            else "引け前持ち越し15:00版"
        ),
        "session": session,
        "active_buybacks": active_buybacks,
        "buybacks_updated_at": buybacks_updated_at,
        "akita_dc_watch": akita_dc_watch,
        "gunma_rare_earth_watch": gunma_rare_earth_watch,
        "indices": indices, "stocks": stocks,
        "day_candidates": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in day_rank],
        "day_ifo_candidates": day_ifo_candidates,
        "silicon_photonics_watch": photonics_watch,
        "day_ifo_summary": {
            "count": len(day_ifo_candidates),
            "selection_rule": "マネーゲーム／IPO 2＋SaaS／AIソフト 2＋当日資金最上位 1",
            "credit_supply_updated_at": credit_supply_updated_at,
            "shares_each": 100,
            "total_capital": total_capital,
            "total_profit": total_profit,
            "total_max_loss": total_loss,
            "order_time": "8:55",
            "manual_entry": True,
        },
        "swing_candidates": {
            "stable": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in stable_rank],
            "momentum": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in momentum_rank],
            "new_high": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in high_rank],
            "overheated_watch": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in overheated_rank]
        },
        "earnings_candidates": earnings, "themes": themes,
        "sector_rotation": rotation,
        "policy_theme_tabs": policy_theme_tabs,
        "bb_expansion_candidates": [
            {"name": n, **r, "plan": trade_plan(r, r.get("intraday"))}
            for n, r in bb_rank
        ],
        "morning_snapshot": morning, "morning_reviews": reviews
    }
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    idx_rows = "".join(
        f"<tr><td>{n}</td><td>{money(r.get('price'))}</td><td class='{css(r.get('change_pct'))}'>{pct(r.get('change_pct'))}</td>"
        f"<td>{'上向き' if r.get('change_pct',0)>.3 else '下向き' if r.get('change_pct',0)<-.3 else '横ばい'}</td></tr>"
        for n, r in indices.items()
    )
    theme_rows = "".join(
        f"<tr><td>{i}</td><td>{name}</td><td class='{css(score)}'>{score:+.1f}</td>"
        f"<td>{'<br>'.join(f'{m[0]} <small>強度{m[1]:+.1f}／{m[2]:+.2f}%</small>' for m in members)}</td>"
        f"<td>{count}銘柄の実測平均</td></tr>"
        for i, (name, score, count, members) in enumerate(themes, 1)
    )
    policy_priority_rows = "".join(
        f"<tr><td><b>#{x['priority']}</b></td><td>{x['title']}</td><td>{x['formal_count']}/5</td><td>{x['best_score'] or '—'}</td><td>{'正式候補あり' if x['formal_count'] else '信用需給待ち・売買不可'}</td><td><a href='{x['source']}' target='_blank' rel='noopener'>政策根拠</a></td></tr>"
        for x in policy_theme_tabs
    )
    policy_theme_sections = ""
    for theme in policy_theme_tabs:
        rows = "".join(
            f"<tr><td>{i}</td><td>{x['name']}<br><small>{x['role']}</small></td><td><span class='pill {'in' if x['formal'] else 'prep'}'>{x['status']}</span></td><td><b>{x['directness']}</b></td><td>{x['business_impact']}</td><td><b class='{'up' if x['formal'] else ''}'>{x['score']}/100</b></td><td>{x['supply_text']}</td><td>{money(x['price'])}<br><small>出来高比{x.get('rvol', 0):.2f}倍</small></td><td>{money(x['plan']['entry'])}</td><td class='down'>{money(x['plan']['stop'])}</td><td>{money(x['plan']['target1'])}／{money(x['plan']['target2'])}</td><td><a href='{x['evidence']}' target='_blank' rel='noopener'>会社公式根拠</a></td></tr>"
            for i, x in enumerate(theme['candidates'], 1)
        ) or "<tr><td colspan='12'>直接関与を会社公式で確認できる上場候補なし。無理に5銘柄へ埋めません。</td></tr>"
        policy_theme_sections += f'''<section id="policy-{theme['slug']}" class="card wide policy-theme-card" data-policy-tab="{theme['slug']}"><h2>実戦優先 #{theme['priority']}｜{theme['title']}・厳格選定</h2><p class="sub">正式候補 {theme['formal_count']}銘柄　／　総合70点以上＋信用需給45/70以上＋悪化除外が必須</p><table><thead><tr><th>研究順位</th><th>会社名＋コード／直接関与</th><th>判定</th><th>政策直接度</th><th>業績寄与度</th><th>総合点</th><th>信用需給</th><th>株価・出来高</th><th>発動</th><th>損切り</th><th>利確1／2</th><th>根拠</th></tr></thead><tbody>{rows}</tbody></table><p class="warning">TOP5を埋めるための周辺銘柄は採用しません。信用需給未取得は研究順位に表示しても売買不可。政策根拠は<a href="{theme['source']}" target="_blank" rel="noopener">政府公式資料</a>、企業関与は各行の会社公式資料で確認します。</p></section>'''
    buyback_rows = "".join(
        f"<tr><td>{i}</td><td>{x['name']}（{x['code']}）</td>"
        f"<td><b class='up'>{x['score']}/100</b></td><td>{float(x['max_share_pct']):.2f}%</td>"
        f"<td>{float(x.get('progress_pct', 0)):.1f}%</td><td>{x['remaining_pct']:.1f}%</td>"
        f"<td>{float(x.get('daily_volume_impact_pct', 0)):.1f}%</td>"
        f"<td>{x['start_date']}～{x['end_date']}</td>"
        f"<td>{'消却予定' if x.get('cancellation_planned') else '取得後保有等'}"
        f"<br><small>{x.get('note', '')}</small></td></tr>"
        for i, x in enumerate(active_buybacks, 1)
    ) or "<tr><td colspan='9'>公式情報を確認できた実施期間中の自社株買い候補なし。推測銘柄は表示しません。</td></tr>"
    dividend_watch = sorted(
        [(n, r) for n, r in valid if r.get("dividend_days") is not None
         and 0 <= r["dividend_days"] <= 45 and r.get("market_supply_improved")],
        key=lambda x: (x[1]["dividend_days"], -x[1]["market_supply_score"]),
    )[:10]
    dividend_rows = "".join(
        f"<tr><td>{i}</td><td>{name}</td><td>{r['estimated_ex_date']}<br><small>過去実績からの推定・あと{r['dividend_days']}日</small></td>"
        f"<td>{money(r['last_dividend'])}</td><td><b>{r['market_supply_score']}/100</b><br><small>{r['market_supply_status']}</small></td>"
        f"<td>{'権利前上昇を監視' if r['price'] >= r['ma20'] else '戻り確認待ち'}</td>"
        f"<td>{money(max(r['high'], r['price']) + price_tick(r['price']))}</td>"
        f"<td class='down'>{money(r['low'] - r['atr14'] * .2)}</td>"
        f"<td>権利落ち日は配当相当の下落・つなぎ売り増加に注意</td></tr>"
        for i, (name, r) in enumerate(dividend_watch, 1)
    ) or "<tr><td colspan='9'>45日以内の推定権利日＋需給改善に合格した監視銘柄なし。</td></tr>"
    akita_dc_rows = "".join(
        f"<tr><td>{i}</td><td>{x['name']}</td>"
        f"<td><b class='up'>{x['relation_score']}/100</b></td>"
        f"<td>{money(x.get('price'))}</td><td class='{css(x.get('change_pct'))}'>{pct(x.get('change_pct'))}</td>"
        f"<td>{x.get('rvol', 0):.2f}倍</td><td>{x['role']}</td>"
        f"<td>{x['evidence']}<br><small>{x['contract_status']}</small></td>"
        f"<td><a href='{x['source']}' target='_blank' rel='noopener'>公式根拠</a></td></tr>"
        for i, x in enumerate(akita_dc_watch, 1)
    ) or "<tr><td colspan='9'>株価データ取得待ち。受注確認前は売買候補に昇格しません。</td></tr>"
    gunma_rare_earth_rows = "".join(
        f"<tr><td>{i}</td><td>{x['name']}</td>"
        f"<td><b>{x['relation_score']}/100</b></td>"
        f"<td>{money(x.get('price'))}</td><td class='{css(x.get('change_pct'))}'>{pct(x.get('change_pct'))}</td>"
        f"<td>{x.get('rvol', 0):.2f}倍</td><td>{x['role']}</td>"
        f"<td>{x['evidence']}<br><small>{x['contract_status']}</small></td>"
        f"<td><a href='{x['source']}' target='_blank' rel='noopener'>公式根拠</a></td></tr>"
        for i, x in enumerate(gunma_rare_earth_watch, 1)
    ) or "<tr><td colspan='9'>株価データ取得待ち。研究段階のため売買候補には昇格しません。</td></tr>"
    us_rotation_rows = "".join(
        f"<tr><td>{i}</td><td>{row['sector']} <small>{row['ticker']}</small></td>"
        f"<td>{phase_badge(row['phase'])}</td><td><b>{row['score']:.0f}/100</b></td>"
        f"<td class='{css(row['rel5'])}'>{pct(row['rel5'])}</td>"
        f"<td class='{css(row['rel20'])}'>{pct(row['rel20'])}</td>"
        f"<td class='{css(row['acceleration'])}'>{row['acceleration']:+.2f}pt</td>"
        f"<td>{row['action']}</td></tr>"
        for i, row in enumerate(rotation["us_sectors"], 1)
    ) or "<tr><td colspan='8'>米国セクターETFを取得できませんでした。</td></tr>"
    jp_rotation_rows = "".join(
        f"<tr><td>{i}</td><td>{row['sector']}</td><td>{phase_badge(row['phase'])}</td>"
        f"<td><b>{row['score']:.0f}/100</b></td>"
        f"<td class='{css(row['rel5'])}'>{pct(row['rel5'])}</td>"
        f"<td class='{css(row['rel20'])}'>{pct(row['rel20'])}</td>"
        f"<td class='{css(row['acceleration'])}'>{row['acceleration']:+.2f}pt</td>"
        f"<td>{row['breadth']:.0f}%</td><td>{row['rvol']:.2f}倍</td>"
        f"<td>{'<br>'.join(x['name'] for x in row['leaders'])}</td>"
        f"<td>{row['action']}</td></tr>"
        for i, row in enumerate(rotation["japan_sectors"], 1)
    ) or "<tr><td colspan='11'>日本株の業種群を計算できませんでした。</td></tr>"
    rotation_pick_rows = "".join(
        f"<tr><td>{i}</td><td>{row['name']}</td><td>{row['sector']}</td>"
        f"<td>{phase_badge(row['phase'])}</td><td><b class='up'>{row['score']}/100</b></td>"
        f"<td>{money(row['plan']['entry'])}</td><td class='down'>{money(row['plan']['stop'])}</td>"
        f"<td>{money(row['plan']['target1'])}／{money(row['plan']['target2'])}</td>"
        f"<td><b>{row.get('material_stage', '事実確認待ち')}</b>｜{row.get('material_action', '')}<br><small>{row['reason']}</small></td></tr>"
        for i, row in enumerate(rotation["picks"], 1)
    ) or "<tr><td colspan='9'>流入初期・拡大かつ流動性条件を満たす候補なし。見送りです。</td></tr>"
    kioxia_view = rotation["kioxia"]
    photonics_rows = "".join(
        f"<tr><td>{i}</td><td><b>{row['name']}</b><br><small>{row['role']}</small></td>"
        f"<td><b class='up'>{row['score']}/100</b><br><small>技術関連度 {row['relevance']}／"
        f"株価技術点 {row['technical']}</small></td>"
        f"<td>{money(row['price'])}</td><td><b>{money(row['trigger'])}</b><br>"
        f"<small>買い上限 {money(row['entry_limit'])}</small></td>"
        f"<td class='down'><b>{money(row['stop'])}</b><br>"
        f"<small>100株 −{row['max_loss_100']:,}円</small></td>"
        f"<td class='up'><b>{money(row['target1'])}</b><br>"
        f"<small>100株 +{row['profit1_100']:,}円</small></td>"
        f"<td>{money(row['target2'])}</td>"
        f"<td>{row['status']}<br><small>{row['condition']} {row['event_risk']}</small></td>"
        f"<td><a href='{row['source']}' target='_blank' rel='noopener'>公式資料</a></td></tr>"
        for i, row in enumerate(photonics_watch, 1)
    ) or (
        "<tr><td colspan='10'>株価データを取得できませんでした。"
        "価格なしでの注文は行いません。</td></tr>"
    )
    ifo_cards = render_day_ifo_cards(day_ifo_candidates)
    focus_dashboard = render_focus_dashboard(day_ifo_candidates)
    trade_drawer = render_trade_drawer()
    ifo_count_note = (
        "分散条件を満たす5銘柄を選定"
        if len(day_ifo_candidates) == 5
        else f"厳格条件合格は{len(day_ifo_candidates)}銘柄。無理に5銘柄へ増やさない"
    )
    day_rows = ""
    for i, (name, r) in enumerate(day_rank, 1):
        p = trade_plan(r, r.get("intraday"))
        shares = 100
        max_loss = abs(p["entry"] - p["stop"]) * shares
        intra = r.get("intraday") or {}
        trigger = "VWAP上維持" if intra.get("close", 0) >= intra.get("vwap", float("inf")) else "VWAP回復待ち"
        if session == "morning":
            trigger = "寄り後5分足＋VWAP確認"
        day_rows += (
            f"<tr><td>{i}</td><td>{name}</td><td>{money(r['price'])}</td><td>{money(p['entry'])}</td>"
            f"<td>{money(p['stop'])}</td><td>{money(p['target1'])}／{money(p['target2'])}</td>"
            f"<td><b>{r.get('material_stage', '事実確認待ち')}</b>｜{r.get('material_action', trigger)}<br>"
            f"<small>{trigger}／{r.get('market_supply_status', '需給未確認')}／{shares}株・最大損失 約{max_loss:,.0f}円</small></td></tr>"
        )
    def swing_rows(rank, kind):
        rows = ""
        for i, (name, r) in enumerate(rank, 1):
            p = trade_plan(r, r.get("intraday"))
            if r["from_ma20"] > 12:
                action = "過熱・押し目待ち"
            elif kind == "momentum" and r["touch_ma5"]:
                action = "5日線タッチ反発・高値更新で発動"
                p["stop"] = round((r["ma5"] - r["atr14"] * .30) / 5) * 5
                risk = max(p["entry"] - p["stop"], r["price"] * .004)
                p["target2"] = round((p["entry"] + risk * 2.2) / 5) * 5
            elif kind == "momentum" and r["price"] >= r["ma5"]:
                action = "5日線上継続・次の押しを待つ"
            elif kind == "new_high" and r["to_high20"] >= 0:
                action = "高値更新＋出来高で発動"
            elif kind == "momentum":
                action = "前日高値突破か5日線反発"
            else:
                action = "20日線上の押し目"
            rows += (
                f"<tr><td>{i}</td><td>{name}</td><td>{money(r['price'])}</td>"
                f"<td>{pct(r['ret5'])}</td><td>{pct(r['ret20'])}</td>"
                f"<td>{pct(r['to_high52'])}</td><td>{r['rvol']:.2f}倍</td>"
                f"<td>{money(p['entry'])}</td><td>{money(p['stop'])}</td>"
                f"<td>{money(p['target2'])}</td><td>{action}<br><small>{r.get('market_supply_status', '需給未確認')}</small></td></tr>"
            )
        return rows or "<tr><td colspan='11'>本日の条件合格銘柄なし。無理に選定しません。</td></tr>"

    stable_rows = swing_rows(stable_rank, "stable")
    momentum_rows = swing_rows(momentum_rank, "momentum")
    high_rows = swing_rows(high_rank, "new_high")
    overheat_rows = swing_rows(overheated_rank, "overheated")
    earning_rows = "".join(
        f"<tr><td>{x['name']}</td><td><b class='{'up' if x['expectation_score']>=80 else ''}'>{x['expectation_score']}/100</b>"
        f"<br><small>減点前 {x['raw_expectation_score']}／充足 {x['score_coverage']}%</small></td>"
        f"<td class='{'down' if x['hurdle_risk']>=50 else ''}'>{x['hurdle_risk']}/100</td>"
        f"<td>{x['technical_score']}/100</td>"
        f"<td>{x['date']}</td><td>{money(x['price'])}</td>"
        f"<td>{money(x['plan']['entry'])}</td><td>{money(x['plan']['stop'])}</td>"
        f"<td>{money(x['plan']['target1'])}</td><td>{x['score_detail']}<br><small>{x['source']}／発表時刻は会社IR確認</small></td></tr>"
        for x in earnings
    ) or "<tr><td colspan='10'>今後7日以内で取得確認できた決算候補なし</td></tr>"
    bb_rows = ""
    for i, (name, r) in enumerate(bb_rank, 1):
        p = trade_plan(r, r.get("intraday"))
        state = (
            "上方エクスパンション開始" if r["price"] >= r["bb_upper"] and r["bb_width_change"] > 0
            else "バンド拡大・上向き" if r["bb_width_change"] > 0 and r["price"] >= r["ma20"]
            else "スクイーズ中・上抜け待ち"
        )
        bb_rows += (
            f"<tr><td>{i}</td><td>{name}</td><td><b class='up'>{r['bb_expansion_score']:.0f}/100</b></td>"
            f"<td>{money(r['price'])}</td><td>{r['bb_width']:.2f}%</td>"
            f"<td>{r['bb_width_change']:+.2f}pt</td><td>{r['bb_percentile']:.0f}%</td>"
            f"<td>{r['rvol']:.2f}倍</td><td>{money(p['entry'])}</td><td>{money(p['stop'])}</td><td>{state}<br><small>{r.get('market_supply_status', '需給未確認')}</small></td></tr>"
        )
    bb_rows = bb_rows or "<tr><td colspan='11'>条件合格銘柄なし</td></tr>"
    review_rows = "".join(
        f"<tr><td>{x['name']}</td><td>{money(x['plan']['entry'])}</td><td>{money(x['plan']['stop'])}</td>"
        f"<td>{money(x['plan']['target1'])}／{money(x['plan']['target2'])}</td>"
        f"<td class='{'up' if '利確' in x['result'] else 'down' if '損切り' in x['result'] else ''}'>{x['result']}</td>"
        f"<td>{x.get('detail','—')}</td></tr>" for x in reviews
    ) or "<tr><td colspan='6'>朝版の同日スナップショットなし。次回8:00版から自動検証します。</td></tr>"

    # Public dashboard uses a date-only discipline score and stores no personal birth data.
    today_jst = datetime.now(JST).date()
    lived_days = (today_jst - datetime(2000, 1, 1, tzinfo=JST).date()).days
    bio_p = round(math.sin(2 * math.pi * lived_days / 23) * 100)
    bio_e = round(math.sin(2 * math.pi * lived_days / 28) * 100)
    bio_i = round(math.sin(2 * math.pi * lived_days / 33) * 100)
    personal_day_raw = sum(int(c) for c in f"{today_jst.year}{today_jst.month}{today_jst.day}")
    while personal_day_raw > 9:
        personal_day_raw = sum(int(c) for c in str(personal_day_raw))
    fortune_score = max(0, min(100, round(50 + bio_p * .15 + bio_e * .10 + bio_i * .10)))
    fortune_action = (
        "強気になりやすい日。利益を伸ばすより、決めた損切りを守る。"
        if fortune_score >= 65 else
        "平常運。普段の株数とルールを変えない。"
        if fortune_score >= 45 else
        "判断がぶれやすい日。発注前の指差し確認を1回増やす。"
    )
    fortune_html = f"""
<section class="card wide"><h2>🔮 本格占い・行動管理（売買AI点数とは完全分離）</h2>
<div class="grid3">
<div><b>本日の行動管理 {fortune_score}/100</b><br>日付数秘：{personal_day_raw}<br>個人情報は非表示</div>
<div><b>バイオリズム</b><br>身体 {bio_p:+d}／感情 {bio_e:+d}／知性 {bio_i:+d}</div>
<div><b>今日の行動ルール</b><br>{fortune_action}</div>
</div>
<p class="warning">公開ページには生年月日・出生地・出生時刻を保存しません。娯楽・心理管理用で、銘柄順位や売買期待値には加点しません。</p></section>
"""
    hindenburg_html = """
<section class="card wide"><h2>🚨 市場警報</h2>
<table><tr><th>警報</th><th>状態</th><th>確認日</th><th>扱い</th></tr>
<tr><td>ヒンデンブルグ・オーメン</td><td><b class="up">OFF（直近確認）</b></td><td>2026-08-05</td><td>本日分は未確認。古いOFFを安全宣言として使わない。</td></tr></table>
<p class="warning">点灯時も暴落確定ではありません。新高値・新安値、騰落、指数トレンドの複合警報として、株数を落とす判断にだけ使います。</p></section>
"""

    nikkei = indices.get("日経平均", {}).get("price")
    atr_n = indices.get("日経平均", {}).get("atr14")
    day_range = "取得不能" if not nikkei else f"{nikkei-(atr_n or nikkei*.015):,.0f} ～ {nikkei+(atr_n or nikkei*.015):,.0f}円"
    phase = data["phase"]
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="900"><title>AIトレードコクピット</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#05070a;color:#f4f7fa;font-family:"Segoe UI","Yu Gothic",sans-serif;font-size:13px}}header{{padding:10px 12px;border-bottom:2px solid #526274;background:#030405;display:flex;justify-content:space-between;gap:12px;align-items:center}}h1{{margin:0;font-size:25px}}h2{{font-size:17px;margin:0 0 7px;color:#d9e8ff;border-bottom:1px solid #405064;padding-bottom:5px}}h3{{color:#9fc8ff;margin:15px 0 7px}}a{{color:#70c7ff}}.sub{{color:#aebdcb;margin-top:4px}}.tag{{background:#ffe86b;color:#111;padding:7px 11px;border-radius:6px;font-weight:900}}main{{padding:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px}}.card{{background:linear-gradient(180deg,#151d27,#0e141c);border:1px solid #73808c;border-radius:6px;padding:7px;overflow:auto}}.wide{{grid-column:1/-1}}table{{width:100%;border-collapse:collapse}}th{{background:#1b2a39}}th,td{{border:1px solid #485664;padding:6px 5px;text-align:right;vertical-align:middle}}th:nth-child(-n+2),td:nth-child(-n+2){{text-align:left}}tr:nth-child(even) td{{background:#111923}}.up{{color:#52e46f;font-weight:900}}.down{{color:#ff6262;font-weight:900}}small{{color:#bac6d2}}.warning{{color:#ffe66d}}.steps,.rotation-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}}.step,.rotation-box{{background:#0b1118;border:1px solid #526274;border-radius:7px;padding:10px;line-height:1.65}}.step b,.rotation-box b{{display:block;color:#ffe66d;font-size:15px}}.rotation-box strong{{font-size:17px;color:#f4f7fa}}.pill{{display:inline-block;padding:3px 8px;border-radius:12px;font-weight:900}}.prep{{background:#f2a900;color:#111}}.in{{background:#52e46f;color:#071009}}.long{{background:#2f80ed;color:white}}.short{{background:#e23b3b;color:white}}.ifo-summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:9px 0}}.ifo-summary .rotation-box strong{{font-size:19px}}.ifo-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.ifo-card{{background:linear-gradient(145deg,#101c2a,#081019);border:1px solid #3b6588;border-radius:10px;padding:11px;box-shadow:0 8px 22px #0007}}.ifo-head{{display:grid;grid-template-columns:auto 1fr auto;gap:9px;align-items:center;border-bottom:1px solid #35506a;padding-bottom:8px}}.ifo-head h3{{margin:0;color:#f4f7fa;font-size:16px}}.ifo-rank{{background:#ffe66d;color:#101820;font-weight:900;border-radius:6px;padding:5px 7px}}.ifo-score{{font-size:18px;color:#52e46f}}.ifo-columns{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:9px}}.order-box{{background:#07101a;border:1px solid #425a70;border-radius:8px;padding:9px}}.order-box>b{{display:block;color:#79c7ff;margin-bottom:7px}}.exit-order>b{{color:#58e3ae}}.order-box dl{{display:grid;grid-template-columns:minmax(88px,.9fr) 1.25fr;gap:4px 8px;margin:0}}.order-box dt{{color:#9eafbf}}.order-box dd{{margin:0;text-align:right}}.ifo-metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin:8px 0}}.ifo-metrics span{{background:#182637;border-radius:5px;padding:6px;text-align:center}}.ifo-card p{{line-height:1.55;margin:6px 0}}footer{{padding:8px 12px;color:#aeb8c2;border-top:1px solid #33404b;display:flex;justify-content:space-between}}@media(max-width:800px){{header{{align-items:flex-start;flex-direction:column}}main{{grid-template-columns:1fr}}.wide{{grid-column:1}}table{{min-width:700px}}.steps,.rotation-grid,.ifo-summary,.ifo-grid,.ifo-columns{{grid-template-columns:1fr}}.ifo-metrics{{grid-template-columns:1fr 1fr}}}}</style></head><body>
<style>
.focus-dashboard{{padding:14px;background:radial-gradient(circle at 80% 0,#123454 0,#101923 42%,#081018 100%);border:1px solid #3e83a8;overflow:visible}}.focus-title{{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:12px}}.focus-title h2{{font-size:26px;margin:2px 0;border:0;color:#fff}}.focus-title>div>span{{color:#63d8ff;font-weight:900;letter-spacing:.08em}}.decision-badge{{padding:12px 16px;border-radius:10px;font-size:17px;white-space:nowrap}}.decision-go{{background:#38e477;color:#03140a}}.decision-ready{{background:#ffd84e;color:#191300}}.decision-wait{{background:#5c6874;color:#fff}}.focus-layout{{display:grid;grid-template-columns:minmax(230px,.7fr) minmax(420px,1.45fr) minmax(320px,1fr);gap:12px}}.focus-picks{{display:flex;flex-direction:column;gap:7px}}.focus-pick{{display:grid;grid-template-columns:auto 1fr auto;gap:9px;align-items:center;text-align:left;color:#e9f4ff;background:#0b1722;border:1px solid #30475b;border-radius:9px;padding:10px;cursor:pointer}}.focus-pick:hover,.focus-pick.active{{border-color:#54d6ff;background:#10283a;box-shadow:0 0 0 1px #54d6ff55}}.focus-pick small{{display:block;margin-top:3px}}.focus-pick strong{{font-size:20px;color:#65e993}}.focus-rank{{background:#20384b;padding:5px;border-radius:5px;font-weight:900}}.focus-chart-wrap,.focus-order{{background:#071019;border:1px solid #2a475d;border-radius:10px;overflow:hidden}}.focus-chart-head{{display:flex;justify-content:space-between;padding:9px 11px;background:#0e2030}}#focus-chart{{width:100%;height:430px;border:0;display:block}}.focus-order{{padding:12px;overflow:auto}}.focus-symbol{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:8px;border-bottom:1px solid #314354;padding-bottom:9px}}.focus-symbol h3{{margin:0;color:#fff;font-size:18px}}.focus-symbol>b{{font-size:21px;color:#63e990}}.focus-action{{margin:11px 0;padding:12px;border-radius:9px;background:#113421;border:1px solid #2b9c58}}.focus-action span,.focus-action small{{display:block}}.focus-action strong{{display:block;font-size:25px;color:#65ef91;margin:4px 0}}.focus-price-grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px}}.focus-price-grid>div{{background:#101e2a;border-radius:7px;padding:9px}}.focus-price-grid span{{display:block;color:#9fb0bf}}.focus-price-grid b{{font-size:17px}}.focus-supply{{margin-top:9px;padding:9px;border-left:4px solid #ffcf4a;background:#191a14}}.focus-supply b,.focus-supply span{{display:block}}.focus-rule{{color:#ffd75e;border-top:1px solid #4a3d16;padding-top:9px}}.focus-empty{{padding:28px;text-align:center;font-size:17px}}@media(max-width:1100px){{.focus-layout{{grid-template-columns:240px 1fr}}.focus-order{{grid-column:1/-1}}}}@media(max-width:800px){{.focus-layout{{grid-template-columns:1fr}}.focus-order{{grid-column:auto}}#focus-chart{{height:360px}}.focus-title{{align-items:flex-start;flex-direction:column}}}}
</style>
<link rel="stylesheet" href="theme.css?v=51">
<link rel="stylesheet" href="focus.css?v=41">
<header><div><h1>AIトレードコクピット Ver.5.1</h1><div class="sub">最初の画面で本命・買い時・押し目・撤退を判断</div></div><div><span class="tag">{phase}</span><div class="sub">{data['updated_at']}／日経想定 {day_range}</div></div></header><div class="tv-quick-link" style="max-width:1500px;margin:12px auto 0;padding:0 18px"><a href="#tv-watchlist-export" onclick="document.querySelector('.cockpit-tab[data-tab=&quot;daytrade&quot;]')?.click()" style="display:inline-block;padding:12px 18px;border-radius:10px;background:linear-gradient(135deg,#00b894,#0984e3);color:#fff;text-decoration:none;font-weight:800;box-shadow:0 5px 18px rgba(9,132,227,.25)">📥 TradingViewへ候補を登録</a></div><main>
{focus_dashboard}
<section id="event-calendar" class="card wide event-calendar"><h2>売買イベントカレンダー</h2>
<div id="event-meta" class="sub">公式日程と需給発生日を照合中...</div>
<div class="event-guard" id="event-guard"><div><span>本日の警戒</span><b id="event-level">確認中</b></div><p id="event-rule">イベント情報を取得中...</p></div>
<div class="event-summary">
 <div><span>本日のイベント</span><b id="event-today-count">—</b></div>
 <div><span>7日以内・高警戒</span><b id="event-week-high">—</b></div>
 <div><span>日付未確定</span><b id="event-blocked-count">—</b></div>
</div>
<h3>今後30日・売買判断表</h3>
<div class="event-table-wrap"><table><thead><tr><th>実需・発表日</th><th>時刻</th><th>イベント</th><th>分類</th><th>警戒</th><th>想定需給</th><th>当日の行動</th><th>発表日</th><th>基準日</th><th>需給日</th><th>反映日</th><th>確認状態</th><th>公式資料</th></tr></thead><tbody id="event-upcoming"><tr><td colspan="13">取得中...</td></tr></tbody></table></div>
<h3>月間カレンダー</h3><div id="event-months" class="event-months"><div class="focus-empty">作成中...</div></div>
<h3>未確定・売買利用禁止</h3><div id="event-unverified" class="event-unverified">確認中...</div>
<div class="steps">
 <div class="step"><b>1　日付を分離</b>発表日・基準日・大引けの需給日・指数反映日を別々に確認。</div>
 <div class="step"><b>2　方向は断定しない</b>月末・SQ・指数入替は買い一方向ではなく、採用買いと除外売りの双方向。</div>
 <div class="step"><b>3　未確定は取引禁止</b>公式日程や対象銘柄を確認できるまで、予想日を売買根拠にしない。</div>
 <div class="step"><b>4　価格で最終確認</b>イベント後もOR15・VWAP・出来高・先物を見て当日の方向を再判定。</div>
</div></section>
<section id="correlation-monitor" class="card wide"><h2>当日デイトレ・相関／逆相関／先行銘柄</h2>
<div id="correlation-meta" class="sub">日足20・60営業日と5分足の関係を更新中...</div>
<label style="display:inline-flex;gap:8px;align-items:center;margin:10px 0;color:#9db0bc">主役銘柄
<select id="correlation-anchor" style="min-width:240px;padding:8px;border:1px solid #2c5067;border-radius:7px;background:#0b1720;color:#eaf4fa"><option value="285A.T">キオクシアHD（285A）</option></select></label>
<table><thead><tr><th>主役銘柄</th><th>確認銘柄</th><th>関係</th><th>成立判定</th><th>信頼度</th><th>20日</th><th>60日</th><th>5分足</th><th>先行</th><th>主役の当日</th><th>確認銘柄の当日</th><th>売買判断</th></tr></thead>
<tbody id="correlation-rows"><tr><td colspan="12">相関データを取得中...</td></tr></tbody></table>
<div class="steps">
<div class="step"><b>1　米国先行</b>サンディスク・Micronの前日終値から、翌日のキオクシア反応を確認。</div>
<div class="step"><b>2　同方向確認</b>正相関銘柄がOR15・VWAP・EMA9/20で同方向なら信頼度を加点。</div>
<div class="step"><b>3　資金ローテーション</b>任天堂など逆相関候補が反対方向へ動いた場合だけ補強材料。</div>
<div class="step"><b>4　不一致は見送り</b>相関株が逆行、または条件3/5以下なら主役銘柄へ飛び乗らない。</div>
</div>
<p class="warning"><b>キオクシア―任天堂は固定ルールではありません。</b> 20日・60日・当日5分足の逆相関が安定した期間だけ有効。サンディスクは取引時間が重ならないため「米国前日→キオクシア翌日」で判定します。9:15までは方向を決めず、OR15・VWAP・EMA9/20・高安の4/5一致を優先します。</p></section>
<section id="kioxia-5m-calendar" class="card wide"><h2>キオクシアHD（285A）5分足カレンダー・類似日予測</h2>
<div id="kioxia-calendar-meta" class="sub">直近60日の5分足を照合中...</div>
<div id="kio-best-analog" class="kio-best-analog">
 <div class="kio-best-chart"><div class="kio-best-title"><div><span>本日最有力5分足</span><b id="kio-best-date">選定中</b></div><strong id="kio-best-score">—</strong></div><div id="kio-best-path" class="focus-empty">米国市場を照合中...</div></div>
 <div class="kio-best-detail"><span id="kio-selection-mode">選定方式を確認中</span><h3 id="kio-best-type">判定待ち</h3><div id="kio-us-context" class="kio-us-context"></div><p id="kio-best-plan">前夜の米国市場と信用需給を確認中です。</p></div>
</div>
<div id="kioxia-supply" class="kio-supply-panel">
 <div class="kio-supply-head"><div><span>信用需給（週次）</span><b id="kio-supply-phase">需給確認中</b></div><small id="kio-supply-date">基準日を確認中</small></div>
 <div class="kio-supply-grid">
  <div><span>信用買い残</span><b id="kio-margin-buy">—</b><small id="kio-margin-buy-change">前週比 —</small></div>
  <div><span>信用売り残</span><b id="kio-margin-sell">—</b><small id="kio-margin-sell-change">前週比 —</small></div>
  <div><span>信用倍率</span><b id="kio-credit-ratio">—</b><small>高倍率は戻り売り圧力</small></div>
  <div><span>機関空売り</span><b id="kio-short-flow">未取得</b><small>推定で埋めない</small></div>
  <div><span>実戦判定</span><b id="kio-supply-bias">判定保留</b><small id="kio-supply-note">公表日を分けて表示</small></div>
 </div>
</div>
<div class="kio-summary">
 <div class="kio-metric"><span>現在の型</span><b id="kio-current-type">判定待ち</b></div>
 <div class="kio-metric"><span>本日の方向</span><b id="kio-bias">判定保留</b></div>
 <div class="kio-metric"><span>類似日上昇確率</span><b id="kio-up-prob">—</b></div>
 <div class="kio-metric"><span>残り時間の平均</span><b id="kio-after-ret">—</b></div>
 <div class="kio-metric"><span>有効サンプル</span><b id="kio-sample">0日</b></div>
</div>
<h3>本日に最も近い過去チャート TOP5</h3>
<div id="kioxia-match-grid" class="kio-match-grid"><div class="focus-empty">類似日を計算中...</div></div>
<h3>直近25営業日・5分足カレンダー</h3>
<div id="kioxia-calendar-grid" class="kio-calendar"><div class="focus-empty">5分足を取得中...</div></div>
<p class="warning"><b>使い方：</b>寄り前は前夜のSanDisk・Micron・SOX・NASDAQと信用需給から最有力チャートを選定します。9:15以降は当日の5分足を65%へ引き上げて再計算。類似度60%以上が3日未満なら「見送り」です。OR15・VWAP・EMA9/20・出来高の4/5一致を最終条件とし、事前予測だけでは発注しません。</p></section>
<section id="world-market-live" class="card wide"><h2>世界市況リアルタイム・地合い確認</h2>
<div id="world-market-meta" class="sub">世界の株価リアルタイムチャートを検証中...</div>
<div class="rotation-grid" id="world-market-cards"><div class="focus-empty">市場データ取得待ち</div></div>
<table><thead><tr><th>市場</th><th>現在値</th><th>変化</th><th>更新時刻</th><th>検証</th></tr></thead>
<tbody id="world-market-rows"><tr><td colspan="5">取得中...</td></tr></tbody></table>
<p class="warning"><b>用途を分離：</b>世界市況・先物・為替・金利・リスク選好の確認専用です。日本の個別株価・ローソク足・発注価格には使用しません。</p></section>
<section class="card wide"><h2>市場環境・需給・ポジション 網羅判定</h2>
<div class="rotation-grid">
<div class="rotation-box"><b>25日騰落レシオ</b><strong id="breadth-25">走査待ち</strong><br><span id="breadth-regime">全市場終値から算出</span></div>
<div class="rotation-box"><b>当日騰落</b><strong id="breadth-daily">走査待ち</strong><br><span id="breadth-counts">上昇／下落／変わらず</span></div>
<div class="rotation-box"><b>新高値・新安値</b><strong id="breadth-highlow">走査待ち</strong><br>20日・52週の両方を確認</div>
<div class="rotation-box"><b>全市場売買代金</b><strong id="breadth-turnover">走査待ち</strong><br><span id="breadth-coverage">取得率を確認</span></div>
</div>
<table><thead><tr><th>分類</th><th>網羅項目</th><th>選定での役割</th><th>現在の扱い</th></tr></thead><tbody>
<tr><td>市場参加</td><td>騰落レシオ／新高値・新安値／売買代金／日本市況／テクニカル指標</td><td>上昇が一部銘柄だけか、市場全体へ広がっているか</td><td class="up">全市場走査で自動反映</td></tr>
<tr><td>需給</td><td>空売り比率／信用評価／裁定買い残／投資主体別</td><td>踏み上げ余地、戻り売り圧力、主体別の買い越し</td><td class="warning">公表日時付きデータのみ採点。未取得は判定保留</td></tr>
<tr><td>ポジション</td><td>先物手口／オプション手口／SQ値／NT倍率</td><td>指数の上値・下値バイアスとリバランス圧力</td><td class="warning">個別銘柄点ではなく地合いゲート</td></tr>
<tr><td>外部環境</td><td>米国市況／世界株価／先物CFD／ADR／為替／商品／仮想通貨／債券／恐怖指数</td><td>翌朝ギャップ、業種ローテーション、リスク選好</td><td>指数・為替・金利・業種相対で反映</td></tr>
<tr><td>評価・イベント</td><td>日経225 PER／米国株PER／ドル建て225／225寄与度／経済ニュース／スケジュール／5分足カレンダー</td><td>割高警戒、指数寄与の偏り、決算・指標回避</td><td>加点せず、過熱警戒と売買禁止条件に使用</td></tr>
</tbody></table>
<p class="warning"><b>重要：</b>空売り比率、信用残、先物・オプション手口など公表頻度が違う値を同日データとして混ぜません。未取得値を推定で埋めず、正式候補のデータ充足率に反映します。</p></section>
<section class="card"><h2>① 地合いサマリー</h2><table><tr><th>指標</th><th>現在値</th><th>前日比</th><th>方向</th></tr>{idx_rows}</table></section>
<section class="card"><h2>② 当日資金流入テーマ TOP5＋有力銘柄</h2><table><tr><th>順位</th><th>テーマ</th><th>強度</th><th>テーマ内有力銘柄 TOP3</th><th>根拠</th></tr>{theme_rows}</table></section>
<section id="policy-priority-overview" class="card wide"><h2>国策テーマ・実戦優先順位</h2><table><thead><tr><th>実戦優先</th><th>テーマ</th><th>正式候補数</th><th>最高総合点</th><th>現在判定</th><th>政策根拠</th></tr></thead><tbody>{policy_priority_rows}</tbody></table><p class="warning">順位は国の政策分野に勝手な序列を付けたものではありません。正式候補数→最高総合点で毎回入れ替えます。信用需給未取得時は全テーマを売買不可とします。</p></section>
{policy_theme_sections}
<section class="card wide"><h2>②-A 秋田AIデータセンター関連 監視TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>関連度</th><th>現在値</th><th>前日比</th><th>出来高比</th><th>想定役割</th><th>根拠・契約状況</th><th>資料</th></tr></thead><tbody>{akita_dc_rows}</tbody></table>
<p class="warning">秋田市の計画はエスツーとBitgritが主導し、2030年代前半の稼働、最大500MWを想定。現時点で上場各社の受注は確認できていません。関連度は事業領域と地域性の評価であり、受注確定度ではありません。正式なスイング候補への昇格には、会社IR・適時開示、信用需給30/55点以上、発動価格突破を必須とします。</p></section>
<section class="card wide"><h2>②-B 群馬・茂倉沢レアアース新鉱物 監視TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>関連度</th><th>現在値</th><th>前日比</th><th>出来高比</th><th>想定役割</th><th>根拠・参画状況</th><th>資料</th></tr></thead><tbody>{gunma_rare_earth_rows}</tbody></table>
<p class="warning">群馬県桐生市の茂倉沢鉱山でランタン・セリウムを含む新鉱物4種が承認された研究成果を監視します。現時点では資源量・採算性・採掘計画・企業参画のいずれも未確認で、商業鉱山案件ではありません。資源量調査、採掘権、自治体・JOGMEC・企業との共同研究、分離精製試験の公式発表が出るまでテーマ監視限定。正式なスイング候補への昇格には信用需給30/55点以上と発動価格突破も必須です。</p></section>
<section id="speculative-theme-monitor" class="card wide"><h2>②-C テーマ仕手化兆候・隔離監視 TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>段階</th><th>異常度</th><th>テーマ・確認状態</th><th>終値</th><th>1日</th><th>5日</th><th>20日</th><th>出来高比</th><th>ATR</th><th>20日線乖離</th><th>上ヒゲ</th><th>信用需給</th><th>監視行動</th></tr></thead>
<tbody id="speculative-theme-watch"><tr><td colspan="15">全市場の仕手化兆候を走査中...</td></tr></tbody></table>
<p class="warning"><b>監視専用・売買候補ではありません。</b> 出来高急増、5日／20日急騰、値幅拡大、加速率、上ヒゲで異常度を算出し、初動候補・資金流入・過熱・天井警戒に分類します。「仕手株」との断定はせず、会社IR・適時開示でテーマを確認し、信用買い残・信用倍率・機関空売り変化も確認。ここに入った銘柄は通常の持ち越しLONG／SHORT TOP5から隔離します。</p></section>
<section id="large-lot-accumulation" class="card wide"><h2>大口買い集め・吸収監視 TOP20</h2>
<div id="accumulation-meta" class="sub">全市場の価格・出来高痕跡を走査中...</div>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>段階</th><th>総合点</th><th>信用需給</th><th>終値</th><th>5日</th><th>20日</th><th>上昇日/下落日出来高</th><th>OBV</th><th>下落日出来高</th><th>安値切上げ</th><th>発動価格</th><th>損切り</th><th>根拠</th></tr></thead>
<tbody id="accumulation-signals"><tr><td colspan="15">全市場を走査中...</td></tr></tbody></table>
<div class="steps">
<div class="step"><b>1　吸収</b>下落日ほど出来高が減り、売られても安値を更新しない。</div>
<div class="step"><b>2　蓄積</b>株価横ばいでもOBV上昇、終値が日中レンジ上側へ偏る。</div>
<div class="step"><b>3　需給確認</b>信用買い残減少・倍率低下・機関空売り買い戻しで正式候補。</div>
<div class="step"><b>4　発動</b>レンジ高値＋1ティック突破だけ買い候補。途中では先回りしない。</div>
</div>
<p class="warning"><b>大口を断定する画面ではありません。</b> 板の大注文は取消可能なので採点しません。市場データの痕跡を抽出し、大量保有報告書・変更報告書・自己株買い・会社IRで裏付けます。信用需給未取得は「暫定」のままです。</p></section>
<section id="sector-rotation" class="card wide"><h2>②-R 機関投資家型 セクターローテーション</h2>
<div class="rotation-grid">
<div class="rotation-box"><b>市場レジーム</b><strong>{rotation['regime']}</strong><br>{rotation['regime_action']}</div>
<div class="rotation-box"><b>金利スイッチ</b><strong>{rotation['rate_view']}</strong><br>米10年金利 5日変化 {rotation['rate5']:+.2f}%</div>
<div class="rotation-box"><b>米国業種の広がり</b><strong>{rotation['breadth']}業種</strong><br>S&P500を5日で上回った業種数</div>
<div class="rotation-box"><b>判定順序</b><strong>資産 → 業種 → 個別株</strong><br>個別材料だけで逆風業種を買わない</div>
</div>
<h3>米国11業種：S&P500に対する相対強弱</h3>
<table><tr><th>順位</th><th>業種ETF</th><th>資金段階</th><th>点数</th><th>5日相対</th><th>20日相対</th><th>勢い変化</th><th>行動</th></tr>{us_rotation_rows}</table>
<h3>日本株：TOPIXに対する相対強弱</h3>
<table><tr><th>順位</th><th>業種群</th><th>資金段階</th><th>点数</th><th>5日相対</th><th>20日相対</th><th>勢い変化</th><th>20日線上比率</th><th>出来高比</th><th>先行銘柄</th><th>行動</th></tr>{jp_rotation_rows}</table>
<h3>セクター追い風＋流動性合格の個別株</h3>
<table><tr><th>順位</th><th>会社名＋コード</th><th>業種群</th><th>資金段階</th><th>期待値</th><th>発動価格</th><th>損切り</th><th>利確1／2</th><th>根拠</th></tr>{rotation_pick_rows}</table>
<h3>キオクシアHD（285A）セクター判定</h3>
<div class="rotation-box"><b>{phase_badge(kioxia_view['status'])}　{kioxia_view['action']}</b>{kioxia_view['detail']}</div>
<p class="warning">これは機関投資家の保有明細そのものではなく、{rotation['source_note']}です。流入初期でも発動価格を上抜かなければ見送り。参考：<a href="https://limo.media/articles/-/133222" target="_blank" rel="noopener">イズミダイズム「セクターローテーション」解説</a></p>
</section>
<section id="silicon-photonics-watch" class="card wide"><h2>②-P AI光通信・シリコンフォトニクス監視（朝刊IN／OUT価格）</h2>
<table><tr><th>順位</th><th>会社名＋コード／役割</th><th>期待値</th><th>基準値</th><th>IN発動／買い上限</th><th>OUT損切り</th><th>OUT利確1</th><th>OUT利確2</th><th>発動条件・リスク</th><th>根拠</th></tr>{photonics_rows}</table>
<p class="warning"><b>使い方：</b>INは前日高値＋1ティック。寄り成りでは買いません。9:15以降にVWAP上・5分足終値・出来高増加が揃った場合だけ発動し、買い上限を超えたら追わず取消。OUT損切りを約定後すぐ設定し、価格を下げて損切りを広げません。GFSの3億ドルは米商務省とのLOI（予定支援）であり、日本企業への直接受注確定ではありません。<a href="https://gf.com/news-and-events/news/globalfoundries-signs-letter-of-intent-with-the-us-department-of-commerce-for-a-300-million-award-to-accelerate-us-silicon-photonics-leadership/" target="_blank" rel="noopener">GFS公式発表</a></p>
</section>
<section id="day-ifo-orders" class="card wide"><h2>②-O 8:55当日勝負・短期資金TOP5（MS2 IFO注文票）</h2>
<div class="ifo-summary">
<div class="rotation-box"><b>合格銘柄</b><strong>{len(day_ifo_candidates)} / 5銘柄</strong><br>{ifo_count_note}</div>
<div class="rotation-box"><b>注文単位</b><strong>各100株</strong><br>分割注文なし／キオクシアは対象外</div>
<div class="rotation-box"><b>全候補が約定した場合</b><strong>建玉目安 {total_capital:,}円</strong><br>利確1合計 <span class="up">+{total_profit:,}円</span></div>
<div class="rotation-box"><b>損失上限の目安</b><strong class="down">−{total_loss:,}円</strong><br>5銘柄が全て損切りになった場合</div>
</div>
<p class="warning"><b>毎朝入替：</b>テーマ・マネーゲーム／IPO・グロースを2銘柄、SaaS・AIソフトを2銘柄、残る1枠を当日資金流入最上位から選定。出来高比・売買代金・値動き・信用需給・材料を更新し、固定大型株を使い回しません。</p>
<p class="warning"><b>8:55の手順：</b>気配、成行買い／売り、特別気配、信用規制・日計り空売り可否を最終確認。買い指値上限を超えた銘柄、特買い張り付き、材料不明の急騰は注文せず監視へ移します。価格を上げて追いかけません。</p>
<div class="ifo-grid">{ifo_cards}</div>
<p class="warning">IFOは利確1と損切りの1組を入力します。利確2は翌日以降へ持ち越す判断をした場合の参考値です。本日中の決済注文は失効するため、15:20時点で未決済なら当日手仕舞い、または翌営業日用の決済OCOを自分で再設定してください。</p>
</section>
<section class="card wide"><h2>③ 当日狙い目銘柄 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1／2</th><th>材料段階・発動条件</th></tr>{day_rows}</table><p class="warning">入口は指値の断定ではなく発動水準。材料出尽くし警戒は初押し反転まで飛び乗り禁止。VWAP・5分足・出来高を満たさなければ見送り。</p></section>
<section class="card wide"><h2>④ 朝8:00候補のザラバ答え合わせ</h2><table><tr><th>会社名＋コード</th><th>朝イン</th><th>朝損切り</th><th>朝利確1／2</th><th>結果</th><th>終値・VWAP検証</th></tr>{review_rows}</table></section>
<section class="card wide"><h2>⑤-A 安定上昇候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{stable_rows}</table></section>
<section class="card wide"><h2>⑤-B 短期急騰期待候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{momentum_rows}</table><p class="warning">上向き5日線へのタッチ反発を最優先。場中の一時割れではなく終値回復を確認。終値で5日線を明確に割った場合は候補から外します。</p></section>
<section class="card wide"><h2>⑤-C 52週新高値・ブレイク候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{high_rows}</table></section>
<section class="card wide"><h2>⑤-D 急騰後の過熱監視・押し目待ち TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>押し目目安</th><th>損切り</th><th>戻り目標</th><th>判定</th></tr>{overheat_rows}</table><p class="warning">ここは即飛び乗り禁止。5日線反発、前日高値更新、出来高再増加の3点を確認してから候補へ昇格。</p></section>
<section class="card wide"><h2>⑤-E 月足・週足反転＋信用需給 TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>足</th><th>判定</th><th>総合点</th><th>終値</th><th>反発線</th><th>需給点・局面</th><th>下ヒゲ／実体</th><th>出来高比</th><th>発動価格</th><th>損切り</th><th>利確1／2</th></tr></thead>
<tbody id="hammer-signals"><tr><td colspan="13">全市場を走査中...</td></tr></tbody></table>
<p class="warning">信用買い残1週・4週、信用倍率、機関空売り増減、買い戻し社数を55点で評価。未取得は需給未確認の暫定候補。高値＋1ティックを上抜いた場合だけ発動し、反転足安値割れで撤退します。</p></section>
<section id="long-term-ma-rebound" class="card wide"><h2>⑤-F 長期右肩上がり・50週線／200日線反発＋信用需給 TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>型</th><th>状態</th><th>総合点</th><th>需給点・局面</th><th>終値</th><th>支持線</th><th>線の傾斜</th><th>半年騰落</th><th>足型</th><th>出来高比</th><th>発動価格</th><th>損切り</th><th>利確1／2</th></tr></thead>
<tbody id="long-term-ma-signals"><tr><td colspan="15">全市場を走査中...</td></tr></tbody></table>
<p class="warning"><b>必須条件：</b>信用需給を確認済みかつ30/55点以上。信用買い残1週・4週、信用倍率、機関空売り増減、買い戻し社数を確認します。50週線・200日線反発だけでは正式候補にしません。反転足高値＋1ティックを上抜いた場合だけ発動し、反転足安値割れで撤退。</p></section>
<section id="dividend-rights-watch" class="card wide"><h2>配当権利前・上昇／権利落ち監視 TOP10</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>推定権利日</th><th>直近配当</th><th>需給改善</th><th>現在判定</th><th>上抜け発動</th><th>撤退</th><th>権利落ち注意</th></tr></thead><tbody>{dividend_rows}</tbody></table>
<p class="warning">権利日は過去の配当実績間隔による推定です。会社IR・取引所の権利確定日を必ず確認。権利取り目的で無条件に買わず、需給改善＋発動価格上抜けだけを監視します。</p></section>
<section id="buyback-watch" class="card wide"><h2>自社株買い実施中・需給インパクト TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>取得上限／発行済株式</th><th>進捗率</th><th>残り余力</th><th>1日出来高への影響</th><th>取得期間</th><th>消却・注意</th></tr></thead>
<tbody>{buyback_rows}</tbody></table>
<p class="warning">会社IR・適時開示で取得期間中と確認できる案件だけを表示。発表済みでも取得終了、上限到達、取得実績ゼロ、出来高への影響が小さい案件は減点します。自社株買いだけで買わず、信用買い残の整理・機関空売り買い戻し・週足／月足反転と重なる銘柄を優先します。更新：{buybacks_updated_at}</p></section>
<section id="tv-watchlist-export" class="card wide"><h2>TradingView監視リスト出力</h2>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin:12px 0">
<button id="tv-day" type="button" style="padding:12px 18px;border:0;border-radius:9px;background:#00b894;color:#fff;font-weight:700;cursor:pointer">当日IN・準備を保存</button>
<button id="tv-swing" type="button" style="padding:12px 18px;border:0;border-radius:9px;background:#3867d6;color:#fff;font-weight:700;cursor:pointer">スイング・持越しを保存</button>
<button id="tv-longterm" type="button" style="padding:12px 18px;border:0;border-radius:9px;background:#8e44ad;color:#fff;font-weight:700;cursor:pointer">50週線／200日線を保存</button>
<button id="tv-speculative" type="button" style="padding:12px 18px;border:0;border-radius:9px;background:#e84393;color:#fff;font-weight:700;cursor:pointer">仕手化監視TOP5を保存</button>
<button id="tv-all" type="button" style="padding:12px 18px;border:0;border-radius:9px;background:#f39c12;color:#111;font-weight:700;cursor:pointer">全候補をまとめて保存</button>
</div>
<p id="tv-export-status" class="sub">ボタンを押すとTradingView取込用TXTをダウンロードします。</p>
<p class="warning">TradingView右側の監視リスト名を押す →「リストをインポート」→ ダウンロードしたTXTを選択。日本株はTSE:銘柄コード形式で出力し、重複は自動削除します。</p></section>
<section id="lower-wick-reversal" class="card wide"><h2>最優先・下ヒゲ吸収反転（次足確認）</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>段階</th><th>反転形</th><th>期待値</th><th>終値</th><th>10日下落</th><th>出来高急増</th><th>発動価格</th><th>損切り</th><th>利確1／2</th><th>根拠</th></tr></thead>
<tbody id="daily-reversal-signals"><tr><td colspan="12">全市場を走査中...</td></tr></tbody></table>
<p class="warning">最も入りたい型。①長い下ヒゲで売りを吸収、②終値がレンジ上側へ回復、③次足が反転足の実体上端または高値＋1ティックを上抜く、の3条件で発動。候補足安値割れで撤退し、ナンピンしません。</p></section>
<section class="card wide"><h2>⑥-A 決算勝負候補 TOP15（7日以内・決算期待値順）</h2><table><tr><th>会社名＋コード</th><th>調整後期待値</th><th>コンセンサス警戒</th><th>テクニカル点</th><th>決算予定日</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1</th><th>採点根拠・注意</th></tr>{earning_rows}</table><p class="warning">高すぎるEPS・売上予想、予想幅の大きさ、下方修正、過去の上振れ不足、決算前の株価上昇を警戒度として減点。好決算でもコンセンサス未達や材料出尽くしになる危険を反映します。</p></section>
<section class="card wide"><h2>⑥-B BB上方エクスパンション期待 TOP7</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>現在値</th><th>BB幅</th><th>5日比</th><th>幅順位</th><th>出来高比</th><th>イン</th><th>損切り</th><th>判定</th></tr>{bb_rows}</table><p class="warning">BB幅順位は過去120日の細さ。数値が低いほどスクイーズ状態。上限突破＋BB幅拡大＋出来高増加を最優先します。</p></section>
<section class="card wide"><h2>⑦ AIスイングサインの使い方</h2>
<div class="steps">
<div class="step"><b>1　<span class="pill prep">準備</span>を探す</b>大引け後に一覧を確認。準備は「まだ買わない」の意味です。</div>
<div class="step"><b>2　IN価格をメモ</b>準備足の高値＋1ティック。翌日からこの価格を監視します。</div>
<div class="step"><b>3　上抜けたら<span class="pill in">IN</span></b>翌日以降にIN価格を上抜いた場合だけ買います。大幅GUは飛び乗りません。</div>
<div class="step"><b>4　損切りを固定</b>赤字の損切り価格を下げません。利確1で半分、利確2で残りを決済します。</div>
</div>
<p class="warning">重要：準備が出た翌日に無条件で買いません。IN価格を超えない、終値で5日線を割る、2営業日たっても発動しない場合は見送りです。</p>
</section>
<section class="card wide"><h2>⑧ 本日<span class="pill in">IN</span>点灯銘柄</h2>
<div id="signal-meta" class="sub">全銘柄データを読み込み中...</div>
<table><thead><tr><th>会社名＋コード</th><th>種類</th><th>期待値</th><th>IN価格</th><th>損切り</th><th>利確1／2</th><th>判定</th></tr></thead>
<tbody id="entered-signals"><tr><td colspan="7">読み込み中...</td></tr></tbody></table></section>
<section class="card wide"><h2>⑨ 本日<span class="pill prep">準備</span>点灯銘柄 上位30</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>種類</th><th>期待値</th><th>終値</th><th>IN価格</th><th>損切り</th><th>利確1／2</th><th>出来高比</th><th>20日騰落</th></tr></thead>
<tbody id="prepared-signals"><tr><td colspan="10">読み込み中...</td></tr></tbody></table>
<p class="warning">全市場の日足を自動走査し、60点以上を抽出。画面は期待値上位30銘柄、データには上位100銘柄を保存します。</p></section>
<section class="card wide"><h2>⑩ 信用需給優先・持ち越し<span class="pill long">LONG</span>候補 TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>翌日LONG発動</th><th>損切り</th><th>利確1／2</th><th>予約IFO入力例</th><th>選定理由</th><th>決算・イベントリスク</th></tr></thead>
<tbody id="overnight-long"><tr><td colspan="9">読み込み中...</td></tr></tbody></table>
<p class="warning">15:00版で候補を確認します。引け成りで無条件に買わず、発動条件を満たした銘柄だけ予約IFOを設定します。新規買いが発動した場合だけ利確・損切りを自動管理。大幅GUは約定させない価格条件にし、朝一はキオクシア等の値嵩株スキャルへ集中します。すでに保有済みならIFOではなく決済OCOを使用。</p></section>
<section class="card wide"><h2>⑪ 信用需給優先・持ち越し<span class="pill short">SHORT</span>候補 TOP5</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>翌日SHORT発動</th><th>損切り</th><th>利確1／2</th><th>選定理由</th><th>決算・イベント／空売り注意</th></tr></thead>
<tbody id="overnight-short"><tr><td colspan="8">読み込み中...</td></tr></tbody></table>
<p class="warning">翌日寄りで無条件に売りません。準備足安値を割った場合だけSHORT。楽天MS2で貸借区分・在庫・逆日歩・空売り規制を必ず確認。大幅GDは追いかけません。</p></section>
<section class="card"><h2>⑫ 運用ルール</h2><p>最大損失を先に固定／同テーマ集中を避ける／持ち越しは通常の半分の株数／損切りを広げない。</p></section>
<section class="card"><h2>⑬ 選定ロジック</h2><p>信用需給を最優先。信用買い残の1週・4週減少、低い信用倍率、機関空売りの買い戻し、複数社買い戻しを評価し、週足・月足反転と重なる銘柄を上位表示。需給未取得は暫定候補です。</p></section>
{hindenburg_html}{fortune_html}
</main><footer><span>情報提供目的。最終判断は板・歩み値・会社IRで確認。</span><span>{data['updated_at']}</span></footer>
<script>
const yen = v => Number(v).toLocaleString("ja-JP");
const signedPct = (v, digits = 1) => Number.isFinite(Number(v))
  ? (Number(v) >= 0 ? "+" : "") + Number(v).toFixed(digits) + "%"
  : "未取得";
const supplyText = x => x.supply_verified
  ? "<b>" + x.supply_score + "/55 " + x.supply_phase + "</b><br><small>買残1週 " +
    signedPct(x.margin_buy_change_1w_pct) + "／倍率 " + Number(x.credit_ratio).toFixed(2) +
    "倍／機関空売り " + signedPct(x.institutional_short_change_pct) + "</small>"
  : "<span class='warning'>需給未確認</span><br><small>正式候補へ昇格不可</small>";
const tvRows = items => (items || []).map(x => x && x.code ? "TSE:" + String(x.code).toUpperCase() : "").filter(Boolean);
const uniqueTv = items => [...new Set(items)];
const saveTvList = (items, filename) => {{
  const symbols = uniqueTv(items);
  const status = document.getElementById("tv-export-status");
  if (!symbols.length) {{
    status.textContent = "該当銘柄がありません。空のリストは保存しませんでした。";
    return;
  }}
  const blob = new Blob([symbols.join(",")], {{type: "text/plain;charset=utf-8"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  status.textContent = symbols.length + "銘柄を保存しました：" + filename;
}};
fetch("signals.json?t=" + Date.now()).then(r => r.json()).then(d => {{
  document.getElementById("signal-meta").textContent =
    d.source + "／走査 " + d.scanned_count.toLocaleString() + "銘柄／準備 " +
    d.signal_count + "銘柄／更新 " + d.updated_at;
  const entered = (d.entered || []).map(x =>
    "<tr><td>" + x.name + "</td><td>" + x.setup + "</td><td><b class='up'>" +
    x.score + "/100</b></td><td>" + yen(x.trigger) + "</td><td class='down'>" +
    yen(x.stop) + "</td><td>" + yen(x.target1) + "／" + yen(x.target2) +
    "</td><td><span class='pill in'>IN</span></td></tr>").join("");
  document.getElementById("entered-signals").innerHTML =
    entered || "<tr><td colspan='7'>本日のIN点灯銘柄なし。無理に選定しません。</td></tr>";
  const prepared = (d.prepared || []).slice(0, 30).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td>" + x.setup +
    "</td><td><b class='up'>" + x.score + "/100</b></td><td>" + yen(x.close) +
    "</td><td><b>" + yen(x.trigger) + "</b></td><td class='down'>" + yen(x.stop) +
    "</td><td>" + yen(x.target1) + "／" + yen(x.target2) + "</td><td>" +
    x.rvol.toFixed(2) + "倍</td><td>" + (x.ret20 >= 0 ? "+" : "") +
    x.ret20.toFixed(2) + "%</td></tr>").join("");
  document.getElementById("prepared-signals").innerHTML =
    prepared || "<tr><td colspan='10'>本日の準備点灯銘柄なし。</td></tr>";
  const speculative = (d.speculative_theme_watch || []).slice(0, 5).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td><b class='" +
    (x.phase === "初動候補" ? "up" : x.phase === "資金流入" ? "warning" : "down") +
    "'>" + x.phase + "</b></td><td><b class='down'>" + x.score +
    "/100</b></td><td>" + x.theme + "<br><small>" + x.theme_status +
    "</small></td><td>" + yen(x.close) + "</td><td class='" +
    (x.ret1 >= 0 ? "up" : "down") + "'>" + signedPct(x.ret1, 2) +
    "</td><td class='" + (x.ret5 >= 0 ? "up" : "down") + "'>" +
    signedPct(x.ret5, 1) + "</td><td class='" + (x.ret20 >= 0 ? "up" : "down") +
    "'>" + signedPct(x.ret20, 1) + "</td><td>" + Number(x.rvol).toFixed(2) +
    "倍</td><td>" + Number(x.atr_pct).toFixed(1) + "%</td><td>" +
    signedPct(x.ma20_dist, 1) + "</td><td>" + Number(x.upper_wick_pct).toFixed(1) +
    "%</td><td>" + supplyText(x) + "</td><td>" + x.action + "</td></tr>").join("");
  document.getElementById("speculative-theme-watch").innerHTML =
    speculative || "<tr><td colspan='15'>本日の仕手化兆候合格銘柄なし。無理に抽出しません。</td></tr>";
  const accumulation = (d.large_lot_accumulation || []).slice(0, 20).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td><b class='" +
    (x.phase.includes("上放れ") ? "up" : "warning") + "'>" + x.phase +
    "</b></td><td><b class='up'>" + x.score + "/100</b></td><td>" +
    supplyText(x) + "</td><td>" + yen(x.close) + "</td><td class='" +
    (x.ret5 >= 0 ? "up" : "down") + "'>" + signedPct(x.ret5, 1) +
    "</td><td class='" + (x.ret20 >= 0 ? "up" : "down") + "'>" +
    signedPct(x.ret20, 1) + "</td><td><b>" +
    Number(x.up_down_volume_ratio).toFixed(2) + "倍</b></td><td class='" +
    (x.obv_impulse > 0 ? "up" : "down") + "'>" +
    Number(x.obv_impulse).toFixed(2) + "</td><td>" +
    Number(x.down_volume_ratio).toFixed(2) + "倍</td><td class='" +
    (x.higher_low_pct >= 0 ? "up" : "down") + "'>" +
    signedPct(x.higher_low_pct, 1) + "</td><td><b>" + yen(x.trigger) +
    "</b></td><td class='down'>" + yen(x.stop) + "</td><td>" +
    x.reason + "</td></tr>").join("");
  document.getElementById("accumulation-signals").innerHTML =
    accumulation || "<tr><td colspan='15'>本日の大口買い集め痕跡の合格銘柄なし。</td></tr>";
  document.getElementById("accumulation-meta").textContent =
    (d.large_lot_accumulation_note || "価格・出来高痕跡による推定") +
    "／信用需給更新 " + (d.credit_supply_updated_at || "未取得");
  const hammers = (d.monthly_weekly_hammers || []).slice(0, 5).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td>" + x.timeframe +
    "</td><td>" + x.status + "</td><td><b class='up'>" + x.score +
    "/100</b></td><td>" + yen(x.close) + "</td><td>" + x.ma_rebound +
    "</td><td>" + (x.supply_verified ? x.supply_score + "/55 " + x.supply_phase : "未取得") +
    "</td><td>" + x.lower_wick_ratio.toFixed(1) + "倍</td><td>" +
    x.volume_ratio.toFixed(2) + "倍</td><td><b>" + yen(x.trigger) +
    "</b></td><td class='down'>" + yen(x.stop) + "</td><td>" +
    yen(x.target1) + "／" + yen(x.target2) + "</td></tr>").join("");
  document.getElementById("hammer-signals").innerHTML =
    hammers || "<tr><td colspan='13'>厳格条件に合格した月足・週足反転銘柄なし。</td></tr>";
  const longTerm = (d.long_term_ma_rebounds || []).slice(0, 5).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td>" + x.setup +
    "</td><td>" + x.status + "</td><td><b class='up'>" + x.score +
    "/100</b></td><td>" + x.supply_score + "/55 " + x.supply_phase +
    "</td><td>" + yen(x.close) + "</td><td>" + x.ma_label + " " +
    yen(x.ma_value) + "</td><td class='" + (x.ma_slope >= 0 ? "up" : "down") +
    "'>" + (x.ma_slope >= 0 ? "+" : "") + x.ma_slope.toFixed(2) +
    "%</td><td class='" + (x.trend_return >= 0 ? "up" : "down") + "'>" +
    (x.trend_return >= 0 ? "+" : "") + x.trend_return.toFixed(2) +
    "%</td><td>" + x.candle + "</td><td>" + x.volume_ratio.toFixed(2) +
    "倍</td><td><b>" + yen(x.trigger) + "</b></td><td class='down'>" +
    yen(x.stop) + "</td><td>" + yen(x.target1) + "／" + yen(x.target2) +
    "</td></tr>").join("");
  document.getElementById("long-term-ma-signals").innerHTML =
    longTerm || "<tr><td colspan='15'>信用需給必須条件に合格した50週線／200日線反発銘柄なし。</td></tr>";
  const dailyReversals = (d.daily_capitulation_reversals || []).slice(0, 20).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td>" + x.phase +
    "</td><td>" + x.setup + "</td><td><b class='up'>" + x.score +
    "/100</b></td><td>" + yen(x.close) + "</td><td>−" +
    x.fall_from_10d.toFixed(1) + "%</td><td>" + x.volume_ratio.toFixed(2) +
    "倍</td><td><b>" + yen(x.trigger) + "</b></td><td class='down'>" +
    yen(x.stop) + "</td><td>" + yen(x.target1) + "／" + yen(x.target2) +
    "</td><td>" + x.reason + "</td></tr>").join("");
  document.getElementById("daily-reversal-signals").innerHTML =
    dailyReversals || "<tr><td colspan='12'>本日のセリクラ反転合格銘柄なし。</td></tr>";
  const carryRows = (items, side) => (items || []).slice(0, 5).map((x, i) => {{
    const risk100 = Math.abs(x.trigger - x.stop) * 100;
    const tick = x.trigger < 1000 && Math.abs(x.trigger - Math.round(x.trigger)) >= .05
      ? .1 : x.trigger < 3000 ? 1 : x.trigger < 5000 ? 5
      : x.trigger < 30000 ? 10 : x.trigger < 50000 ? 50 : 100;
    const entryLimit = side === "LONG" ? x.trigger + tick * 2 : x.trigger - tick * 2;
    const ifo = side === "LONG"
      ? "<b>IFO（利益確定＋損切り）</b><br>" +
        "① 買建・100株・特定<br>" +
        "② 市場価格 " + yen(x.trigger) + "円以上<br>" +
        "③ 買い指値 " + yen(entryLimit) + "円<br>" +
        "④ 利益確定：売埋指値 " + yen(x.target1) + "円<br>" +
        "⑤ 損切り：市場価格 " + yen(x.stop) + "円以下<br>" +
        "⑥ 執行期限：当日中<br>" +
        "<small>最大損失目安 " + yen(risk100) + "円。利確2 " +
        yen(x.target2) + "円は100株注文では未入力の参考値。</small>"
      : "新規売り逆指値 " + yen(x.trigger) + "<br>利確 " +
        yen(x.target1) + "／損切 " + yen(x.stop);
    return (
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td><b class='" +
    (side === "LONG" ? "up" : "down") + "'>" + x.score + "/100</b></td><td><b>" +
    yen(x.trigger) + "</b></td><td class='down'>" + yen(x.stop) + "</td><td>" +
    yen(x.target1) + "／" + yen(x.target2) + "</td><td>" + ifo +
    "</td><td>" + x.reason + "</td><td>" + x.event_risk +
    "<br><small>" + x.caution + "</small></td></tr>");
  }}).join("");
  document.getElementById("overnight-long").innerHTML =
    carryRows(d.overnight_long, "LONG") || "<tr><td colspan='9'>本日の持ち越しLONG合格銘柄なし。</td></tr>";
  document.getElementById("overnight-short").innerHTML =
    carryRows(d.overnight_short, "SHORT") || "<tr><td colspan='8'>本日の持ち越しSHORT合格銘柄なし。</td></tr>";

  const daySymbols = uniqueTv([
    ...tvRows(d.entered), ...tvRows((d.prepared || []).slice(0, 30))
  ]);
  const swingSymbols = uniqueTv([
    ...tvRows(d.monthly_weekly_hammers), ...tvRows(d.overnight_long), ...tvRows(d.overnight_short)
  ]);
  const longTermSymbols = uniqueTv(tvRows(d.long_term_ma_rebounds));
  const speculativeSymbols = uniqueTv(tvRows(d.speculative_theme_watch));
  const accumulationSymbols = uniqueTv(tvRows(d.large_lot_accumulation));
  const allSymbols = uniqueTv([...daySymbols, ...swingSymbols, ...longTermSymbols, ...speculativeSymbols, ...accumulationSymbols]);
  const dateTag = String(d.updated_at || "").slice(0, 10).replaceAll("-", "");
  document.getElementById("tv-day").onclick = () => saveTvList(daySymbols, "AIコクピット_当日_" + dateTag + ".txt");
  document.getElementById("tv-swing").onclick = () => saveTvList(swingSymbols, "AIコクピット_スイング_" + dateTag + ".txt");
  document.getElementById("tv-longterm").onclick = () => saveTvList(longTermSymbols, "AIコクピット_長期反発_" + dateTag + ".txt");
  document.getElementById("tv-speculative").onclick = () => saveTvList(speculativeSymbols, "AIコクピット_仕手化監視_" + dateTag + ".txt");
  document.getElementById("tv-all").onclick = () => saveTvList(allSymbols, "AIコクピット_全候補_" + dateTag + ".txt");
}}).catch(() => {{
  document.getElementById("signal-meta").textContent = "全銘柄シグナルデータを取得できませんでした。次回自動更新で再試行します。";
  document.getElementById("entered-signals").innerHTML = "<tr><td colspan='7'>データ取得待ち</td></tr>";
  document.getElementById("prepared-signals").innerHTML = "<tr><td colspan='10'>データ取得待ち</td></tr>";
  document.getElementById("speculative-theme-watch").innerHTML = "<tr><td colspan='15'>データ取得待ち</td></tr>";
  document.getElementById("accumulation-signals").innerHTML = "<tr><td colspan='15'>データ取得待ち</td></tr>";
  document.getElementById("hammer-signals").innerHTML = "<tr><td colspan='13'>データ取得待ち</td></tr>";
  document.getElementById("long-term-ma-signals").innerHTML = "<tr><td colspan='15'>データ取得待ち</td></tr>";
  document.getElementById("daily-reversal-signals").innerHTML = "<tr><td colspan='12'>データ取得待ち</td></tr>";
  document.getElementById("overnight-long").innerHTML = "<tr><td colspan='9'>データ取得待ち</td></tr>";
  document.getElementById("overnight-short").innerHTML = "<tr><td colspan='8'>データ取得待ち</td></tr>";
}});
const worldEsc = v => String(v ?? "—").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
fetch("world_market.json?t=" + Date.now()).then(r => r.json()).then(d => {{
  const rows = Object.values(d.rows || {{}});
  document.getElementById("world-market-meta").textContent = d.source + "／更新 " + d.updated_at + "／検証 " + d.verified_count + "/" + d.expected_count;
  document.getElementById("world-market-cards").innerHTML = rows.filter(x=>x.verified).slice(0,8).map(x =>
    "<div class='rotation-box'><b>"+worldEsc(x.name)+"</b><strong>"+Number(x.value).toLocaleString("ja-JP")+"</strong><br><span class='"+(Number(x.change_pct)>=0?"up":"down")+"'>"+(x.change_pct==null?"—":(Number(x.change_pct)>=0?"+":"")+Number(x.change_pct).toFixed(2)+"%")+"</span><br><small>"+worldEsc(x.source_stamp)+"</small></div>"
  ).join("") || "<div class='focus-empty'>鮮度確認済みデータなし</div>";
  document.getElementById("world-market-rows").innerHTML = rows.map(x =>
    "<tr><td><b>"+worldEsc(x.name)+"</b></td><td>"+(x.value==null?"—":Number(x.value).toLocaleString("ja-JP"))+"</td><td class='"+(Number(x.change_pct)>=0?"up":"down")+"'>"+(x.change_pct==null?"—":(Number(x.change_pct)>=0?"+":"")+Number(x.change_pct).toFixed(2)+"%")+"</td><td>"+worldEsc(x.source_stamp)+"</td><td class='"+(x.verified?"up":"down")+"'>"+worldEsc(x.status)+"</td></tr>"
  ).join("");
}}).catch(() => {{
  document.getElementById("world-market-meta").textContent = "世界市況データ取得失敗・地合い判定に使用しません";
  document.getElementById("world-market-rows").innerHTML = "<tr><td colspan='5'>取得失敗・売買利用禁止</td></tr>";
}});
const eventEsc = v => String(v ?? "—").replace(/[&<>"']/g,c=>({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
fetch("event_calendar.json?t=" + Date.now()).then(r => r.json()).then(d => {{
  document.getElementById("event-meta").textContent = d.source_policy + "／更新 " + d.updated_at;
  const guard = document.getElementById("event-guard");
  document.getElementById("event-level").textContent = d.today_level;
  document.getElementById("event-rule").textContent = d.today_rule;
  if (d.today_level === "高警戒") guard.classList.add("high");
  const todayEvents = d.today_events || [];
  const limit = new Date(d.today + "T00:00:00+09:00"); limit.setDate(limit.getDate()+7);
  const weekHigh = (d.upcoming || []).filter(x => x.impact === "高" && new Date(x.date+"T00:00:00+09:00") <= limit).length;
  document.getElementById("event-today-count").textContent = todayEvents.length + "件";
  document.getElementById("event-week-high").textContent = weekHigh + "件";
  document.getElementById("event-blocked-count").textContent = (d.unverified || []).length + "件";
  const end = new Date(d.today + "T00:00:00+09:00"); end.setDate(end.getDate()+30);
  const rows = (d.upcoming || []).filter(x => new Date(x.date+"T00:00:00+09:00") <= end).map(x =>
    "<tr><td><b>"+eventEsc(x.date)+"</b></td><td>"+eventEsc(x.time_jst)+"</td><td>"+eventEsc(x.title)+
    "</td><td>"+eventEsc(x.category)+"</td><td class='"+(x.impact==="高"?"down":"warning")+"'>"+eventEsc(x.impact)+
    "</td><td>"+eventEsc(x.expected_flow)+"</td><td><b>"+eventEsc(x.action)+"</b><br><small>"+eventEsc(x.note)+
    "</small></td><td>"+eventEsc(x.announcement_date)+"</td><td>"+eventEsc(x.base_date)+"</td><td>"+eventEsc(x.flow_date)+
    "</td><td>"+eventEsc(x.effective_date)+"</td><td><span class='event-status "+(x.trade_block?"block":"")+"'>"+eventEsc(x.status)+
    "</span></td><td><a class='event-source' href='"+eventEsc(x.source_url)+"' target='_blank' rel='noopener'>"+eventEsc(x.source_name)+"</a></td></tr>"
  ).join("");
  document.getElementById("event-upcoming").innerHTML = rows || "<tr><td colspan='13'>今後30日の登録イベントなし</td></tr>";
  const grouped = {{}};
  (d.events || []).filter(x=>x.date).forEach(x=>{{const k=x.date.slice(0,7);(grouped[k] ||= []).push(x);}});
  const monthKeys = Object.keys(grouped).filter(k=>k>=d.today.slice(0,7)).slice(0,4);
  document.getElementById("event-months").innerHTML = monthKeys.map(key=>{{
    const [year,month]=key.split("-").map(Number), first=new Date(year,month-1,1), count=new Date(year,month,0).getDate();
    const mondayFirst=(first.getDay()+6)%7, cells=Array(mondayFirst).fill("<div class='event-day empty'></div>");
    for(let day=1;day<=count;day++){{
      const iso=key+"-"+String(day).padStart(2,"0"), items=grouped[key].filter(x=>x.date===iso);
      const chips=items.map(x=>"<span class='event-chip "+(x.trade_block?"block":x.impact==="高"?"high":"")+"' title='"+eventEsc(x.action)+"'>"+eventEsc(x.time_jst)+" "+eventEsc(x.title)+"</span>").join("");
      cells.push("<div class='event-day "+(iso===d.today?"today":"")+"'><strong>"+day+"</strong>"+chips+"</div>");
    }}
    return "<div class='event-month'><h4>"+year+"年"+month+"月</h4><div class='event-weekdays'><span>月</span><span>火</span><span>水</span><span>木</span><span>金</span><span>土</span><span>日</span></div><div class='event-days'>"+cells.join("")+"</div></div>";
  }}).join("") || "<div class='focus-empty'>カレンダー対象なし</div>";
  document.getElementById("event-unverified").innerHTML = (d.unverified || []).map(x=>
    "<div class='event-block'><b>"+eventEsc(x.title)+"</b><span>"+eventEsc(x.effective_date)+"</span><small>売買禁止："+eventEsc(x.note)+"</small><a href='"+eventEsc(x.source_url)+"' target='_blank' rel='noopener'>公式確認先</a></div>"
  ).join("") || "<div class='up'>未確定イベントなし</div>";
}}).catch(() => {{
  document.getElementById("event-level").textContent = "取得失敗";
  document.getElementById("event-rule").textContent = "イベントを確認できないため、イベント需給を根拠に売買しません。";
  document.getElementById("event-upcoming").innerHTML = "<tr><td colspan='13'>データ取得待ち</td></tr>";
}});
const corrText = v => v == null ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2);
const todayText = x => {{
  if (!x || x.ret == null) return "未取得";
  return signedPct(x.ret, 2) + "／OR15 " + x.or15 + "／VWAP" + x.vwap + "／EMA " + x.ema;
}};
fetch("correlations.json?t=" + Date.now()).then(r => r.json()).then(d => {{
  document.getElementById("correlation-meta").textContent = d.method + "／更新 " + d.updated_at;
  const allRelations = d.relationships || [];
  const select = document.getElementById("correlation-anchor");
  const anchors = [...new Map(allRelations.map(x => [x.anchor_ticker, x.anchor])).entries()];
  select.innerHTML = anchors.map(([ticker,name]) => "<option value='" + ticker + "'>" + name + "</option>").join("") || "<option>候補なし</option>";
  if (anchors.some(x => x[0] === "285A.T")) select.value = "285A.T";
  const renderRelations = () => {{
   const rows = allRelations.filter(x => x.anchor_ticker === select.value).map(x => {{
    const lead = x.relation.includes("米国前日") ? "米国前日" :
      x.lead_bars == null ? "—" : x.lead_bars > 0 ? "確認銘柄が" + (x.lead_bars * 5) + "分先行" :
      x.lead_bars < 0 ? "主役が" + (-x.lead_bars * 5) + "分先行" : "同時";
    return "<tr><td><b>" + x.anchor + "</b></td><td>" + x.peer + "</td><td>" +
      x.relation + "<br><small>" + x.expected + "</small></td><td><b class='" +
      (x.state === "確認" ? "up" : x.state === "不成立" ? "down" : "warning") + "'>" +
      x.state + "</b></td><td>" + x.confidence + "/100</td><td>" + corrText(x.corr20) +
      "</td><td>" + corrText(x.corr60) + "</td><td>" + corrText(x.intraday_corr) +
      "</td><td>" + lead + "</td><td>" + todayText(x.anchor_today) + "</td><td>" +
      todayText(x.peer_today) + "</td><td><b>" + x.decision + "</b><br><small>" + x.reason +
      "</small></td></tr>";
   }}).join("");
   document.getElementById("correlation-rows").innerHTML = rows ||
    "<tr><td colspan='12'>安定した相関・逆相関はありません。相関を売買根拠にしません。</td></tr>";
  }};
  select.onchange = renderRelations;
  renderRelations();
}}).catch(() => {{
  document.getElementById("correlation-meta").textContent = "相関データ未取得。推定で埋めません。";
  document.getElementById("correlation-rows").innerHTML = "<tr><td colspan='12'>データ取得待ち</td></tr>";
}});
const miniPath = (points, stroke="#58d9b4") => {{
  if (!points || points.length < 2) return "<div class='focus-empty'>データなし</div>";
  const lo = Math.min(...points), hi = Math.max(...points), span = Math.max(hi - lo, .01);
  const coords = points.map((v,i) => (i/(points.length-1)*116+2).toFixed(1) + "," + (66-(v-lo)/span*60).toFixed(1)).join(" ");
  const zero = (66-(0-lo)/span*60).toFixed(1);
  return "<svg viewBox='0 0 120 70' preserveAspectRatio='none'><line x1='2' y1='" + zero + "' x2='118' y2='" + zero + "' stroke='#38505e' stroke-dasharray='3 3'/><polyline points='" + coords + "' fill='none' stroke='" + stroke + "' stroke-width='2'/></svg>";
}};
Promise.all([
 fetch("kioxia_5m_calendar.json?t=" + Date.now()).then(r => r.json()),
 fetch("credit_supply.json?t=" + Date.now()).then(r => r.json()).catch(() => ({{stocks:{{}}}}))
]).then(([d,credit]) => {{
  const p = d.prediction || {{}};
  const supply = (credit.stocks || {{}})["285A"] || null;
  const fmtShares = v => v == null ? "—" : Number(v).toLocaleString("ja-JP") + "株";
  const fmtSignedShares = v => v == null ? "—" : (Number(v) >= 0 ? "+" : "") + Number(v).toLocaleString("ja-JP") + "株";
  if (supply && supply.verified) {{
    const phase = document.getElementById("kio-supply-phase");
    phase.textContent = supply.supply_phase || "判定保留";
    phase.className = supply.supply_phase === "改善" ? "kio-supply-good" : supply.supply_phase === "悪化" ? "kio-supply-bad" : "";
    document.getElementById("kio-supply-date").textContent = "基準 " + supply.margin_date + "／取得 " + (supply.retrieved_date || "—") + "／週次";
    document.getElementById("kio-margin-buy").textContent = fmtShares(supply.margin_buy_balance);
    document.getElementById("kio-margin-buy-change").textContent = "前週比 " + fmtSignedShares(supply.margin_buy_change_1w) + "（" + signedPct(supply.margin_buy_change_1w_pct,1) + "）";
    document.getElementById("kio-margin-sell").textContent = fmtShares(supply.margin_sell_balance);
    document.getElementById("kio-margin-sell-change").textContent = "前週比 " + fmtSignedShares(supply.margin_sell_change_1w) + "（" + signedPct(supply.margin_sell_change_1w_pct,2) + "）";
    document.getElementById("kio-credit-ratio").textContent = Number(supply.credit_ratio).toFixed(2) + "倍";
    document.getElementById("kio-short-flow").textContent = supply.institutional_short_change_pct == null ? "未取得" : signedPct(supply.institutional_short_change_pct,1);
    document.getElementById("kio-supply-bias").textContent = supply.trade_bias || "判定保留";
    document.getElementById("kio-supply-note").textContent = supply.note || "";
  }} else {{
    document.getElementById("kio-supply-phase").textContent = "需給未確認・売買利用禁止";
    document.getElementById("kio-supply-date").textContent = "週次信用残を取得できていません";
  }}
  document.getElementById("kioxia-calendar-meta").textContent = (d.source || "5分足") + "／更新 " + d.updated_at + "／" + (d.current_is_today ? "本日観測 " + (d.observed_bars || 0) + "本" : (d.selection_mode || "寄り前選定"));
  document.getElementById("kio-current-type").textContent = d.current_is_today && d.current ? d.current.type + " " + signedPct(d.current.ret, 2) : "本日開始待ち";
  const riskOverlay = d.risk_overlay || {{}};
  document.getElementById("kio-bias").textContent = riskOverlay.status ? riskOverlay.status + "｜" + (p.bias || "判定保留") : (p.bias || "判定保留");
  document.getElementById("kio-up-prob").textContent = p.up_probability == null ? "—" : Number(p.up_probability).toFixed(1) + "%";
  document.getElementById("kio-after-ret").textContent = p.expected_after_ret == null ? "—" : signedPct(p.expected_after_ret, 2);
  document.getElementById("kio-sample").textContent = (p.sample || 0) + "日";
  const best = d.best_match || (d.matches || [])[0] || null;
  const context = d.market_context || null;
  const usLabels = {{sndk:"SanDisk",mu:"Micron",sox:"SOX",nasdaq:"NASDAQ"}};
  document.getElementById("kio-selection-mode").textContent = d.selection_mode || "類似日選定";
  if (best) {{
    document.getElementById("kio-best-date").textContent = best.date;
    document.getElementById("kio-best-score").textContent = Number(best.similarity).toFixed(1) + "%";
    document.getElementById("kio-best-path").innerHTML = miniPath(best.path, best.ret >= 0 ? "#58ddb5" : "#ff777e");
    document.getElementById("kio-best-type").textContent = best.type + "／全日 " + signedPct(best.ret,2);
    document.getElementById("kio-best-plan").textContent = "類似日の照合後 " + signedPct(best.after_ret,2) + "、最大上振れ " + signedPct(best.max_up_after,2) + "、最大下振れ " + signedPct(best.max_down_after,2) + "。" + (riskOverlay.action || (p.sample < 3 ? "サンプル不足のため売買利用禁止。" : "9:15以降のローソク足確認が必須。" ));
  }} else {{
    document.getElementById("kio-best-date").textContent = "選定不能";
    document.getElementById("kio-best-plan").textContent = "米国市場または5分足データ不足。推定で埋めません。";
  }}
  document.getElementById("kio-us-context").innerHTML = context && context.values ? Object.entries(context.values).map(([k,v]) => "<div><span>" + (usLabels[k] || k) + "</span><b class='" + (v >= 0 ? "kio-up" : "kio-down") + "'>" + signedPct(v,2) + "</b></div>").join("") : "<div><span>米国市場</span><b>未取得</b></div>";
  const matches = (d.matches || []).map((x,i) => {{ const c=x.score_components||{{}}; return "<div class='kio-match'><div class='kio-day-head'><b>#" + (i+1) + " " + x.date + "</b><strong>" + x.similarity.toFixed(1) + "%</strong></div>" + miniPath(x.path, x.ret >= 0 ? "#58ddb5" : "#ff777e") + "<div>全日 <b class='" + (x.ret >= 0 ? "kio-up" : "kio-down") + "'>" + signedPct(x.ret,2) + "</b>／照合後 " + signedPct(x.after_ret,2) + "</div><small>5分 " + (c.five_minute == null ? "寄り前" : c.five_minute + "%") + "／米国 " + (c.us_market == null ? "—" : c.us_market + "%") + "／需給 " + (c.credit_supply == null ? "—" : c.credit_supply + "%") + "</small></div>"; }}).join("");
  document.getElementById("kioxia-match-grid").innerHTML = matches || "<div class='focus-empty'>類似度60%以上の比較候補なし</div>";
  const supplyHistory = supply && Array.isArray(supply.history) ? [...supply.history].sort((a,b) => a.date.localeCompare(b.date)) : [];
  const supplyAt = date => supplyHistory.filter(s => s.date <= date).at(-1) || null;
  const days = (d.calendar || []).map(x => {{ const cs=supplyAt(x.date), badge=cs ? "<span class='kio-supply-tag " + (cs.phase === "改善" ? "good" : cs.phase === "悪化" ? "bad" : "") + "'>信用" + cs.date.slice(5).replace("-","/") + " " + cs.phase + " " + Number(cs.ratio).toFixed(1) + "倍</span>" : "<span class='kio-supply-tag'>需給履歴未取得</span>"; return "<div class='kio-day'><div class='kio-day-head'><b>" + x.date.slice(5).replace("-","/") + "</b><span class='" + (x.ret >= 0 ? "kio-up" : "kio-down") + "'>" + signedPct(x.ret,2) + "</span></div>" + miniPath(x.path, x.ret >= 0 ? "#58ddb5" : "#ff777e") + "<small>" + x.type + "　高安 " + signedPct(x.high,1) + "／" + signedPct(x.low,1) + "</small>" + badge + "</div>"; }}).join("");
  document.getElementById("kioxia-calendar-grid").innerHTML = days || "<div class='focus-empty'>5分足データ待ち</div>";
}}).catch(() => {{
  document.getElementById("kioxia-calendar-meta").textContent = "5分足または信用需給データ未取得。推定で埋めません。";
  document.getElementById("kioxia-match-grid").innerHTML = "<div class='focus-empty'>データ取得待ち</div>";
  document.getElementById("kioxia-calendar-grid").innerHTML = "<div class='focus-empty'>データ取得待ち</div>";
}});
</script>{trade_drawer}</body></html>"""
    (ROOT / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
