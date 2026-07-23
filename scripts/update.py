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
            "ret5": round(ret5, 2), "ret20": round(ret20, 2),
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
            earnings.append({
                "name": name, "date": dt, "price": r["price"], "plan": p,
                "source": official["source"] if official else "Yahoo予想",
                "expectation_score": expectation_score(r, earnings=True)
            })
    earnings.sort(key=lambda x: (-x["expectation_score"], x["date"]))
    earnings = earnings[:7]

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
        f"<tr><td>{x['name']}</td><td><b class='{'up' if x['expectation_score']>=80 else ''}'>{x['expectation_score']}/100</b></td>"
        f"<td>{x['date']}</td><td>{money(x['price'])}</td>"
        f"<td>{money(x['plan']['entry'])}</td><td>{money(x['plan']['stop'])}</td>"
        f"<td>{money(x['plan']['target1'])}</td><td>{x['source']}／発表時刻は会社IR確認</td></tr>"
        for x in earnings
    ) or "<tr><td colspan='8'>今後7日以内で取得確認できた決算候補なし</td></tr>"
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
<style>*{{box-sizing:border-box}}body{{margin:0;background:#05070a;color:#f4f7fa;font-family:"Segoe UI","Yu Gothic",sans-serif;font-size:13px}}header{{padding:10px 12px;border-bottom:2px solid #526274;background:#030405;display:flex;justify-content:space-between;gap:12px;align-items:center}}h1{{margin:0;font-size:25px}}h2{{font-size:17px;margin:0 0 7px;color:#d9e8ff;border-bottom:1px solid #405064;padding-bottom:5px}}.sub{{color:#aebdcb;margin-top:4px}}.tag{{background:#ffe86b;color:#111;padding:7px 11px;border-radius:6px;font-weight:900}}main{{padding:6px;display:grid;grid-template-columns:1fr 1fr;gap:6px}}.card{{background:linear-gradient(180deg,#151d27,#0e141c);border:1px solid #73808c;border-radius:6px;padding:7px;overflow:auto}}.wide{{grid-column:1/-1}}table{{width:100%;border-collapse:collapse}}th{{background:#1b2a39}}th,td{{border:1px solid #485664;padding:6px 5px;text-align:right;vertical-align:middle}}th:nth-child(-n+2),td:nth-child(-n+2){{text-align:left}}tr:nth-child(even) td{{background:#111923}}.up{{color:#52e46f;font-weight:900}}.down{{color:#ff6262;font-weight:900}}small{{color:#bac6d2}}.warning{{color:#ffe66d}}footer{{padding:8px 12px;color:#aeb8c2;border-top:1px solid #33404b;display:flex;justify-content:space-between}}@media(max-width:800px){{header{{align-items:flex-start;flex-direction:column}}main{{grid-template-columns:1fr}}.wide{{grid-column:1}}table{{min-width:700px}}}}</style></head><body>
<header><div><h1>AIトレードコクピット Ver.3.1</h1><div class="sub">安定上昇・短期急騰・新高値更新を分離／過熱銘柄は押し目待ち判定</div></div><div><span class="tag">{phase}</span><div class="sub">{data['updated_at']}／日経想定 {day_range}</div></div></header><main>
<section class="card"><h2>① 地合いサマリー</h2><table><tr><th>指標</th><th>現在値</th><th>前日比</th><th>方向</th></tr>{idx_rows}</table></section>
<section class="card"><h2>② 当日資金流入テーマ TOP5＋有力銘柄</h2><table><tr><th>順位</th><th>テーマ</th><th>強度</th><th>テーマ内有力銘柄 TOP3</th><th>根拠</th></tr>{theme_rows}</table></section>
<section class="card wide"><h2>③ 当日狙い目銘柄 TOP7</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1／2</th><th>発動条件・リスク</th></tr>{day_rows}</table><p class="warning">入口は指値の断定ではなく発動水準。VWAP・5分足・出来高を満たさなければ見送り。</p></section>
<section class="card wide"><h2>④ 朝8:30候補のザラバ答え合わせ</h2><table><tr><th>会社名＋コード</th><th>朝イン</th><th>朝損切り</th><th>朝利確1／2</th><th>結果</th><th>終値・VWAP検証</th></tr>{review_rows}</table></section>
<section class="card wide"><h2>⑤-A 安定上昇候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{stable_rows}</table></section>
<section class="card wide"><h2>⑤-B 短期急騰期待候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{momentum_rows}</table><p class="warning">上向き5日線へのタッチ反発を最優先。場中の一時割れではなく終値回復を確認。終値で5日線を明確に割った場合は候補から外します。</p></section>
<section class="card wide"><h2>⑤-C 52週新高値・ブレイク候補 TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>イン</th><th>損切り</th><th>利確</th><th>発動条件</th></tr>{high_rows}</table></section>
<section class="card wide"><h2>⑤-D 急騰後の過熱監視・押し目待ち TOP5</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>52週高値差</th><th>出来高比</th><th>押し目目安</th><th>損切り</th><th>戻り目標</th><th>判定</th></tr>{overheat_rows}</table><p class="warning">ここは即飛び乗り禁止。5日線反発、前日高値更新、出来高再増加の3点を確認してから候補へ昇格。</p></section>
<section class="card wide"><h2>⑥-A 決算勝負候補（7日以内・期待値順）</h2><table><tr><th>会社名＋コード</th><th>期待値</th><th>決算予定日</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1</th><th>注意</th></tr>{earning_rows}</table><p class="warning">期待値はテクニカル・出来高・流動性・高値位置の評価であり、決算内容やギャップを保証する点数ではありません。</p></section>
<section class="card wide"><h2>⑥-B BB上方エクスパンション期待 TOP7</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>期待値</th><th>現在値</th><th>BB幅</th><th>5日比</th><th>幅順位</th><th>出来高比</th><th>イン</th><th>損切り</th><th>判定</th></tr>{bb_rows}</table><p class="warning">BB幅順位は過去120日の細さ。数値が低いほどスクイーズ状態。上限突破＋BB幅拡大＋出来高増加を最優先します。</p></section>
<section class="card"><h2>⑦ 運用ルール</h2><p>最大損失を先に固定／同テーマ集中を避ける／デイトレは15:25までに手仕舞い／損切りを広げない。</p></section>
<section class="card"><h2>⑧ 選定ロジック</h2><p>安定＝20日線＞60日線・低ATR・高流動性。急騰＝上向き5日線タッチ反発・終値で5日線維持・出来高再増加。新高値＝52週高値5％以内・20日高値突破・出来高確認。過熱株は別枠監視。</p></section>
</main><footer><span>情報提供目的。最終判断は板・歩み値・会社IRで確認。</span><span>{data['updated_at']}</span></footer></body></html>"""
    (ROOT / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
