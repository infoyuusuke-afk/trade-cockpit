import json
import re
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


def flat_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def daily_snapshot(ticker):
    try:
        df = flat_columns(yf.download(
            ticker, period="1y", interval="1d", auto_adjust=False,
            progress=False, threads=False
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
            "high_score": round(high_score, 2)
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
        return {
            "ok": True, "open": round(float(df["Open"].iloc[0]), 2),
            "high": round(float(df["High"].max()), 2),
            "low": round(float(df["Low"].min()), 2),
            "close": round(float(df["Close"].iloc[-1]), 2),
            "vwap": round(vwap, 2), "volume": round(float(vol.sum()))
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
    tick = 5 if p >= 3000 else 1
    rounded = lambda x: round(x / tick) * tick
    return {
        "entry": rounded(entry), "stop": rounded(stop),
        "target1": rounded(target1), "target2": rounded(target2),
        "risk": rounded(risk)
    }


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
    t1, t2 = plan["target1"], plan["target2"]
    entered = intra["low"] <= entry <= intra["high"]
    if not entered:
        return {"result": "未約定", "detail": f"安値{intra['low']:,.0f}／高値{intra['high']:,.0f}"}
    if intra["high"] >= t2:
        result = "利確2到達"
    elif intra["high"] >= t1:
        result = "利確1到達"
    elif intra["low"] <= stop:
        result = "損切り到達"
    else:
        result = "継続・未決済"
    pnl = intra["close"] - entry
    return {
        "result": result,
        "detail": f"終値差 {pnl:+,.0f}円／VWAP {intra['vwap']:,.0f}円"
    }


def money(v):
    return "—" if v is None else f"{v:,.0f}"


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
    for sector, ticker in US_SECTOR_ETFS.items():
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
        score = clamp(
            group_row["score"] * .55
            + 35
            + clamp(stock_rel5, -8, 8) * 1.8
            + clamp(row.get("rvol", 1) - 1, -1, 2) * 3
        )
        picks.append({
            "name": name, "sector": group, "phase": group_row["phase"],
            "score": round(score),
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


def main():
    now = datetime.now(JST)
    afternoon = now.hour >= 12
    config = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    previous = {}
    data_path = ROOT / "data.json"
    if data_path.exists():
        try:
            previous = json.loads(data_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}

    indices = {name: daily_snapshot(ticker) for name, ticker in config["indices"].items()}
    stocks = {}
    for name, meta in config["stocks"].items():
        row = daily_snapshot(meta["ticker"])
        row.update({"ticker": meta["ticker"], "sector": meta["sector"], "style": meta["style"]})
        if afternoon and row.get("ok"):
            row["intraday"] = intraday_snapshot(meta["ticker"])
        stocks[name] = row

    valid = [(n, r) for n, r in stocks.items() if r.get("ok")]
    rotation = build_sector_rotation(indices, valid)
    day_rank = sorted(
        [(n, r) for n, r in valid if r["style"] in ("day", "both") and r["turnover"] >= 2_000_000_000],
        key=lambda x: x[1]["day_score"], reverse=True
    )[:7]
    swing_pool = [
        (n, r) for n, r in valid
        if r["style"] in ("swing", "both") and 500 <= r["price"] <= 30000
        and r["turnover"] >= 500_000_000
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

    morning = previous.get("morning_snapshot")
    if not afternoon:
        morning = {
            "date": now.strftime("%Y-%m-%d"),
            "candidates": [
                {"name": n, "plan": trade_plan(r), "price": r["price"]}
                for n, r in day_rank
            ]
        }

    reviews = []
    if afternoon and morning and morning.get("date") == now.strftime("%Y-%m-%d"):
        for item in morning.get("candidates", []):
            r = stocks.get(item["name"], {})
            reviews.append({
                "name": item["name"], "plan": item["plan"],
                **review_trade(item["plan"], r.get("intraday"))
            })

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

    data = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "phase": "大引け検証15:00版" if afternoon else "寄り付き前8:30版",
        "indices": indices, "stocks": stocks,
        "day_candidates": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in day_rank],
        "swing_candidates": {
            "stable": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in stable_rank],
            "momentum": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in momentum_rank],
            "new_high": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in high_rank],
            "overheated_watch": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in overheated_rank]
        },
        "earnings_candidates": earnings, "themes": themes,
        "sector_rotation": rotation,
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
        f"<td>{row['reason']}</td></tr>"
        for i, row in enumerate(rotation["picks"], 1)
    ) or "<tr><td colspan='9'>流入初期・拡大かつ流動性条件を満たす候補なし。見送りです。</td></tr>"
    kioxia_view = rotation["kioxia"]
    day_rows = ""
    for i, (name, r) in enumerate(day_rank, 1):
        p = trade_plan(r, r.get("intraday"))
        shares = 10 if p["entry"] >= 10000 else 100
        max_loss = abs(p["entry"] - p["stop"]) * shares
        intra = r.get("intraday") or {}
        trigger = "VWAP上維持" if intra.get("close", 0) >= intra.get("vwap", float("inf")) else "VWAP回復待ち"
        if not afternoon:
            trigger = "寄り後5分足＋VWAP確認"
        day_rows += (
            f"<tr><td>{i}</td><td>{name}</td><td>{money(r['price'])}</td><td>{money(p['entry'])}</td>"
            f"<td>{money(p['stop'])}</td><td>{money(p['target1'])}／{money(p['target2'])}</td>"
            f"<td>{trigger}<br><small>{shares}株・最大損失 約{max_loss:,.0f}円</small></td></tr>"
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
                f"<td>{money(p['target2'])}</td><td>{action}</td></tr>"
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
            f"<td>{r['rvol']:.2f}倍</td><td>{money(p['entry'])}</td><td>{money(p['stop'])}</td><td>{state}</td></tr>"
        )
    bb_rows = bb_rows or "<tr><td colspan='11'>条件合格銘柄なし</td></tr>"
    review_rows = "".join(
        f"<tr><td>{x['name']}</td><td>{money(x['plan']['entry'])}</td><td>{money(x['plan']['stop'])}</td>"
        f"<td>{money(x['plan']['target1'])}／{money(x['plan']['target2'])}</td>"
        f"<td class='{'up' if '利確' in x['result'] else 'down' if '損切り' in x['result'] else ''}'>{x['result']}</td>"
        f"<td>{x.get('detail','—')}</td></tr>" for x in reviews
    ) or "<tr><td colspan='6'>朝版の同日スナップショットなし。次回8:30版から自動検証します。</td></tr>"

    nikkei = indices.get("日経平均", {}).get("price")
    atr_n = indices.get("日経平均", {}).get("atr14")
    day_range = "取得不能" if not nikkei else f"{nikkei-(atr_n or nikkei*.015):,.0f} ～ {nikkei+(atr_n or nikkei*.015):,.0f}円"
    phase = data["phase"]
    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="900"><title>AIトレードコクピット</title>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#05070a;color:#f4f7fa;font-family:"Segoe UI","Yu Gothic",sans-serif;font-size:13px}}header{{padding:10px 12px;border-bottom:2px solid #526274;background:#030405;display:flex;justify-content:space-between;gap:12px;align-items:center}}h1{{margin:0;font-size:25px}}h2{{font-size:17px;margin:0 0 7px;color:#d9e8ff;border-bottom:1px solid #405064;padding-bottom:5px}}h3{{color:#9fc8ff;margin:15px 0 7px}}a{{color:#70c7ff}}.sub{{color:#aebdcb;margin-top:4px}}.tag{{background:#ffe86b;color:#111;padding:7px 11px;border-radius:6px;font-weight:900}}main{{padding:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px}}.card{{background:linear-gradient(180deg,#151d27,#0e141c);border:1px solid #73808c;border-radius:6px;padding:7px;overflow:auto}}.wide{{grid-column:1/-1}}table{{width:100%;border-collapse:collapse}}th{{background:#1b2a39}}th,td{{border:1px solid #485664;padding:6px 5px;text-align:right;vertical-align:middle}}th:nth-child(-n+2),td:nth-child(-n+2){{text-align:left}}tr:nth-child(even) td{{background:#111923}}.up{{color:#52e46f;font-weight:900}}.down{{color:#ff6262;font-weight:900}}small{{color:#bac6d2}}.warning{{color:#ffe66d}}.steps,.rotation-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px}}.step,.rotation-box{{background:#0b1118;border:1px solid #526274;border-radius:7px;padding:10px;line-height:1.65}}.step b,.rotation-box b{{display:block;color:#ffe66d;font-size:15px}}.rotation-box strong{{font-size:17px;color:#f4f7fa}}.pill{{display:inline-block;padding:3px 8px;border-radius:12px;font-weight:900}}.prep{{background:#f2a900;color:#111}}.in{{background:#52e46f;color:#071009}}.long{{background:#2f80ed;color:white}}.short{{background:#e23b3b;color:white}}footer{{padding:8px 12px;color:#aeb8c2;border-top:1px solid #33404b;display:flex;justify-content:space-between}}@media(max-width:800px){{header{{align-items:flex-start;flex-direction:column}}main{{grid-template-columns:1fr}}.wide{{grid-column:1}}table{{min-width:700px}}.steps,.rotation-grid{{grid-template-columns:1fr}}}}</style></head><body>
<header><div><h1>AIトレードコクピット Ver.3.3</h1><div class="sub">日本株全市場／持ち越しLONG・SHORT発動価格</div></div><div><span class="tag">{phase}</span><div class="sub">{data['updated_at']}／日経想定 {day_range}</div></div></header><main>
<section class="card"><h2>① 地合いサマリー</h2><table><tr><th>指標</th><th>現在値</th><th>前日比</th><th>方向</th></tr>{idx_rows}</table></section>
<section class="card"><h2>② 当日資金流入テーマ TOP5＋有力銘柄</h2><table><tr><th>順位</th><th>テーマ</th><th>強度</th><th>テーマ内有力銘柄 TOP3</th><th>根拠</th></tr>{theme_rows}</table></section>
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
<section class="card wide"><h2>③ 当日狙い目銘柄 TOP7</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1／2</th><th>発動条件・リスク</th></tr>{day_rows}</table><p class="warning">入口は指値の断定ではなく発動水準。VWAP・5分足・出来高を満たさなければ見送り。</p></section>
<section class="card wide"><h2>④ 朝8:30候補のザラバ答え合わせ</h2><table><tr><th>会社名＋コード</th><th>朝イン</th><th>朝損切り</th><th>朝利確1／2</th><th>結果</th><th>終値・VWAP検証</th></tr>{review_rows}</table></section>
<section class="card wide"><h2>⑤-A 安定上昇候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{stable_rows}</table></section>
<section class="card wide"><h2>⑤-B 短期急騰期待候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{momentum_rows}</table><p class="warning">上向き5日線へのタッチ反発を最優先。場中の一時割れではなく終値回復を確認。終値で5日線を明確に割った場合は候補から外します。</p></section>
<section class="card wide"><h2>⑤-C 52週新高値・ブレイク候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{high_rows}</table></section>
<section class="card wide"><h2>⑤-D 急騰後の過熱監視・押し目待ち TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>押し目目安</th><th>損切り</th><th>戻り目標</th><th>判定</th></tr>{overheat_rows}</table><p class="warning">ここは即飛び乗り禁止。5日線反発、前日高値更新、出来高再増加の3点を確認してから候補へ昇格。</p></section>
<section class="card wide"><h2>⑤-E 月足・週足 陽線ハンマー＋移動平均線反発</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>足</th><th>判定</th><th>期待値</th><th>終値</th><th>反発線</th><th>下ヒゲ／実体</th><th>出来高比</th><th>発動価格</th><th>損切り</th><th>利確1／2</th></tr></thead>
<tbody id="hammer-signals"><tr><td colspan="12">全市場を走査中...</td></tr></tbody></table>
<p class="warning">7月月足は月末まで暫定。高値＋1ティックを翌日以降に上抜いた場合だけ発動し、ハンマーの安値割れで撤退します。</p></section>
<section class="card wide"><h2>⑤-F 日足セリングクライマックス反転監視</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>段階</th><th>反転形</th><th>期待値</th><th>終値</th><th>10日下落</th><th>出来高急増</th><th>発動価格</th><th>損切り</th><th>利確1／2</th><th>根拠</th></tr></thead>
<tbody id="daily-reversal-signals"><tr><td colspan="12">全市場を走査中...</td></tr></tbody></table>
<p class="warning">画像のような「急落→大出来高→安値固め→陽線確認」を検出。逆張りなので、反転足高値＋1ティックを上抜くまで買いません。</p></section>
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
<section class="card wide"><h2>⑩ 持ち越し<span class="pill long">LONG</span>候補 TOP10</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>翌日LONG発動</th><th>損切り</th><th>利確1／2</th><th>予約IFO入力例</th><th>選定理由</th><th>決算・イベントリスク</th></tr></thead>
<tbody id="overnight-long"><tr><td colspan="9">読み込み中...</td></tr></tbody></table>
<p class="warning">大引け後に予約IFOを設定し、朝は注文を変更しません。新規買いが発動した場合だけ利確・損切りを自動管理。大幅GUは約定させない価格条件にし、朝一はキオクシア等の値嵩株スキャルへ集中します。すでに保有済みならIFOではなく決済OCOを使用。</p></section>
<section class="card wide"><h2>⑪ 持ち越し<span class="pill short">SHORT</span>候補 TOP10</h2>
<table><thead><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>翌日SHORT発動</th><th>損切り</th><th>利確1／2</th><th>選定理由</th><th>決算・イベント／空売り注意</th></tr></thead>
<tbody id="overnight-short"><tr><td colspan="8">読み込み中...</td></tr></tbody></table>
<p class="warning">翌日寄りで無条件に売りません。準備足安値を割った場合だけSHORT。楽天MS2で貸借区分・在庫・逆日歩・空売り規制を必ず確認。大幅GDは追いかけません。</p></section>
<section class="card"><h2>⑫ 運用ルール</h2><p>最大損失を先に固定／同テーマ集中を避ける／持ち越しは通常の半分の株数／損切りを広げない。</p></section>
<section class="card"><h2>⑬ 選定ロジック</h2><p>LONG＝上昇トレンド・高値突破。SHORT＝終値＜5日線＜20日線・戻り失敗・安値割れ。低流動性、売られすぎ、踏み上げ危険は除外。</p></section>
</main><footer><span>情報提供目的。最終判断は板・歩み値・会社IRで確認。</span><span>{data['updated_at']}</span></footer>
<script>
const yen = v => Number(v).toLocaleString("ja-JP");
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
  const hammers = (d.monthly_weekly_hammers || []).slice(0, 20).map((x, i) =>
    "<tr><td>" + (i + 1) + "</td><td>" + x.name + "</td><td>" + x.timeframe +
    "</td><td>" + x.status + "</td><td><b class='up'>" + x.score +
    "/100</b></td><td>" + yen(x.close) + "</td><td>" + x.ma_rebound +
    "</td><td>" + x.lower_wick_ratio.toFixed(1) + "倍</td><td>" +
    x.volume_ratio.toFixed(2) + "倍</td><td><b>" + yen(x.trigger) +
    "</b></td><td class='down'>" + yen(x.stop) + "</td><td>" +
    yen(x.target1) + "／" + yen(x.target2) + "</td></tr>").join("");
  document.getElementById("hammer-signals").innerHTML =
    hammers || "<tr><td colspan='12'>厳格条件に合格した陽線ハンマー銘柄なし。</td></tr>";
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
  const carryRows = (items, side) => (items || []).slice(0, 10).map((x, i) => {{
    const risk100 = Math.abs(x.trigger - x.stop) * 100;
    const tick = x.trigger < 3000 ? 1 : 5;
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
        yen(x.target2) + "円は200株時の2本目。</small>"
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
}}).catch(() => {{
  document.getElementById("signal-meta").textContent = "全銘柄シグナルデータを取得できませんでした。次回自動更新で再試行します。";
  document.getElementById("entered-signals").innerHTML = "<tr><td colspan='7'>データ取得待ち</td></tr>";
  document.getElementById("prepared-signals").innerHTML = "<tr><td colspan='10'>データ取得待ち</td></tr>";
  document.getElementById("hammer-signals").innerHTML = "<tr><td colspan='12'>データ取得待ち</td></tr>";
  document.getElementById("daily-reversal-signals").innerHTML = "<tr><td colspan='12'>データ取得待ち</td></tr>";
  document.getElementById("overnight-long").innerHTML = "<tr><td colspan='9'>データ取得待ち</td></tr>";
  document.getElementById("overnight-short").innerHTML = "<tr><td colspan='8'>データ取得待ち</td></tr>";
}});
</script></body></html>"""
    (ROOT / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
