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
    failed = 0
    batch_size = 120
    for start in range(0, len(universe), batch_size):
        batch = universe[start:start + batch_size]
        tickers = [x["ticker"] for x in batch]
        try:
            downloaded = yf.download(
                tickers, period="1y", interval="1d", auto_adjust=False,
                group_by="ticker", progress=False, threads=True, timeout=30
            )
        except Exception:
            downloaded = pd.DataFrame()
        for item in batch:
            row = analyse(item, one_frame(downloaded, item["ticker"], len(batch) == 1))
            if row:
                results.append(row)
            elif one_frame(downloaded, item["ticker"], len(batch) == 1) is None:
                failed += 1
        time.sleep(.2)

    results.sort(key=lambda x: (x["score"], x["rvol"], x["ret20"]), reverse=True)
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
        "note": "日足終値ベース。準備足高値を翌日以降に上抜いた場合のみIN。最終判断は板・出来高・会社IRで確認。"
    }
    old_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
