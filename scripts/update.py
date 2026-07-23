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
            ticker, period="6mo", interval="1d", auto_adjust=False,
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
        ret5 = (close / float(df["Close"].iloc[-6]) - 1) * 100 if len(df) >= 6 else 0
        ret20 = (close / float(df["Close"].iloc[-21]) - 1) * 100 if len(df) >= 21 else 0
        change = (close / prev - 1) * 100 if prev else 0
        rvol = vol / avg_vol if avg_vol else 0
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
        return {
            "ok": True, "price": round(close, 2), "open": round(open_, 2),
            "high": round(high, 2), "low": round(low, 2),
            "prev_close": round(prev, 2), "change_pct": round(change, 2),
            "ret5": round(ret5, 2), "ret20": round(ret20, 2),
            "rvol": round(rvol, 2), "turnover": round(turnover),
            "atr14": round(atr, 2), "ma5": round(ma5, 2), "ma20": round(ma20, 2),
            "day_score": round(day_score, 2), "swing_score": round(swing_score, 2)
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
    swing_rank = sorted(
        [(n, r) for n, r in valid if r["style"] in ("swing", "both") and 1500 <= r["price"] <= 15000],
        key=lambda x: x[1]["swing_score"], reverse=True
    )[:7]

    sector_scores = {}
    for _, r in valid:
        sector_scores.setdefault(r["sector"], []).append(r["day_score"])
    themes = sorted(
        ((k, sum(v) / len(v), len(v)) for k, v in sector_scores.items()),
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
    earnings = []
    for name, r in valid:
        code = r["ticker"].split(".")[0]
        official = official_earnings.get(code)
        dt = official["date"] if official else earnings_date(r["ticker"], now)
        if dt:
            p = trade_plan(r, r.get("intraday"))
            earnings.append({
                "name": name, "date": dt, "price": r["price"], "plan": p,
                "source": official["source"] if official else "Yahoo予想"
            })
    earnings.sort(key=lambda x: x["date"])
    earnings = earnings[:7]

    data = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "phase": "大引け検証15:00版" if afternoon else "寄り付き前8:30版",
        "indices": indices, "stocks": stocks,
        "day_candidates": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in day_rank],
        "swing_candidates": [{"name": n, **r, "plan": trade_plan(r, r.get("intraday"))} for n, r in swing_rank],
        "earnings_candidates": earnings, "themes": themes,
        "morning_snapshot": morning, "morning_reviews": reviews
    }
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    idx_rows = "".join(
        f"<tr><td>{n}</td><td>{money(r.get('price'))}</td><td class='{css(r.get('change_pct'))}'>{pct(r.get('change_pct'))}</td>"
        f"<td>{'上向き' if r.get('change_pct',0)>.3 else '下向き' if r.get('change_pct',0)<-.3 else '横ばい'}</td></tr>"
        for n, r in indices.items()
    )
    theme_rows = "".join(
        f"<tr><td>{i}</td><td>{name}</td><td class='{css(score)}'>{score:+.1f}</td><td>{count}銘柄の実測平均</td></tr>"
        for i, (name, score, count) in enumerate(themes, 1)
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
    swing_rows = "".join(
        f"<tr><td>{i}</td><td>{name}</td><td>{money(r['price'])}</td><td>{pct(r['ret5'])}</td>"
        f"<td>{pct(r['ret20'])}</td><td>{money(trade_plan(r, r.get('intraday'))['entry'])}</td>"
        f"<td>{money(trade_plan(r, r.get('intraday'))['stop'])}</td><td>{money(trade_plan(r, r.get('intraday'))['target2'])}</td></tr>"
        for i, (name, r) in enumerate(swing_rank, 1)
    )
    earning_rows = "".join(
        f"<tr><td>{x['name']}</td><td>{x['date']}</td><td>{money(x['price'])}</td>"
        f"<td>{money(x['plan']['entry'])}</td><td>{money(x['plan']['stop'])}</td>"
        f"<td>{money(x['plan']['target1'])}</td><td>{x['source']}／発表時刻は会社IR確認</td></tr>"
        for x in earnings
    ) or "<tr><td colspan='7'>今後7日以内で取得確認できた決算候補なし</td></tr>"
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
<header><div><h1>AIトレードコクピット Ver.3.0</h1><div class="sub">8:30候補保存 → 15:00ザラバ実績検証／候補は30銘柄から動的選定</div></div><div><span class="tag">{phase}</span><div class="sub">{data['updated_at']}／日経想定 {day_range}</div></div></header><main>
<section class="card"><h2>① 地合いサマリー</h2><table><tr><th>指標</th><th>現在値</th><th>前日比</th><th>方向</th></tr>{idx_rows}</table></section>
<section class="card"><h2>② 当日資金流入テーマ TOP5</h2><table><tr><th>順位</th><th>テーマ</th><th>強度</th><th>根拠</th></tr>{theme_rows}</table></section>
<section class="card wide"><h2>③ 当日狙い目銘柄 TOP7</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1／2</th><th>発動条件・リスク</th></tr>{day_rows}</table><p class="warning">入口は指値の断定ではなく発動水準。VWAP・5分足・出来高を満たさなければ見送り。</p></section>
<section class="card wide"><h2>④ 朝8:30候補のザラバ答え合わせ</h2><table><tr><th>会社名＋コード</th><th>朝イン</th><th>朝損切り</th><th>朝利確1／2</th><th>結果</th><th>終値・VWAP検証</th></tr>{review_rows}</table></section>
<section class="card wide"><h2>⑤ スイング候補 TOP7</h2><table><tr><th>順位</th><th>会社名＋コード</th><th>現在値</th><th>5日</th><th>20日</th><th>押し目イン</th><th>損切り</th><th>利確目安</th></tr>{swing_rows}</table></section>
<section class="card wide"><h2>⑥ 決算勝負候補（7日以内・確認できた銘柄のみ）</h2><table><tr><th>会社名＋コード</th><th>決算予定日</th><th>現在値</th><th>イン</th><th>損切り</th><th>利確1</th><th>注意</th></tr>{earning_rows}</table><p class="warning">決算跨ぎは通常の逆指値が効かないギャップリスクあり。発表日・時刻は必ず会社IRで最終確認。</p></section>
<section class="card"><h2>⑦ 運用ルール</h2><p>最大損失を先に固定／同テーマ集中を避ける／デイトレは15:25までに手仕舞い／損切りを広げない。</p></section>
<section class="card"><h2>⑧ 次回への学習</h2><p>15:00版は朝候補の未約定・利確・損切り・VWAP位置を保存。固定銘柄の繰り返しを避け、出来高・売買代金・5日/20日モメンタムを次回順位へ反映。</p></section>
</main><footer><span>情報提供目的。最終判断は板・歩み値・会社IRで確認。</span><span>{data['updated_at']}</span></footer></body></html>"""
    (ROOT / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
