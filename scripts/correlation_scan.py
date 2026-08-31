"""Build evidence-based correlation and lead/lag views for day-trade confirmation."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
OUT = ROOT / "correlations.json"

SPECIAL = [
    ("285A.T", "SNDK", "米国前日→日本翌日", "正相関", "NAND・SSD価格と米国メモリ株の先行確認"),
    ("285A.T", "MU", "米国前日→日本翌日", "正相関", "DRAM/NANDを含む米国メモリ地合い"),
    ("285A.T", "7974.T", "日本同時", "逆相関仮説", "大型グロース内の資金ローテーション仮説"),
]


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except Exception:
        return None


def frame_for(downloaded, ticker):
    try:
        if isinstance(downloaded.columns, pd.MultiIndex):
            if ticker in downloaded.columns.get_level_values(0):
                frame = downloaded[ticker].copy()
            else:
                frame = downloaded.xs(ticker, axis=1, level=1).copy()
        else:
            frame = downloaded.copy()
        frame.columns = [str(x).title() for x in frame.columns]
        return frame.dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()


def corr(a, b, count):
    joined = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna().tail(count)
    if len(joined) < min(12, count):
        return None, len(joined)
    return finite(joined["a"].corr(joined["b"])), len(joined)


def previous_us_to_japan(jp_close, us_close):
    jp = jp_close.copy()
    us = us_close.copy()
    jp.index = pd.to_datetime(jp.index).tz_localize(None).normalize()
    us.index = pd.to_datetime(us.index).tz_localize(None).normalize()
    us_ret = us.pct_change().dropna().sort_index()
    jp_ret = jp.pct_change().dropna().sort_index()
    rows = []
    for dt, value in jp_ret.items():
        prior = us_ret[us_ret.index < dt]
        if not prior.empty:
            rows.append((dt, float(value), float(prior.iloc[-1])))
    if not rows:
        return pd.Series(dtype=float), pd.Series(dtype=float)
    frame = pd.DataFrame(rows, columns=["date", "jp", "us"]).set_index("date")
    return frame["jp"], frame["us"]


def intraday_metrics(a, b):
    if a.empty or b.empty:
        return {"intraday_corr": None, "lead_bars": None, "bars": 0}
    ar = a["Close"].astype(float).pct_change()
    br = b["Close"].astype(float).pct_change()
    same = pd.concat([ar.rename("a"), br.rename("b")], axis=1).dropna().tail(300)
    if len(same) < 30:
        return {"intraday_corr": None, "lead_bars": None, "bars": len(same)}
    best = (None, -1.0, None)
    for lag in range(-3, 4):
        value = finite(same["a"].corr(same["b"].shift(lag)))
        if value is not None and abs(value) > best[1]:
            best = (value, abs(value), lag)
    # positive lag: peer's earlier return best explains anchor later.
    return {
        "intraday_corr": round(best[0], 2) if best[0] is not None else None,
        "lead_bars": best[2], "bars": len(same),
    }


def today_view(frame):
    if frame.empty:
        return {"ret": None, "or15": "未取得", "vwap": "未取得", "ema": "未取得"}
    work = frame.copy()
    idx = pd.to_datetime(work.index)
    if idx.tz is not None:
        idx = idx.tz_convert(JST)
    work.index = idx
    latest_day = work.index[-1].date()
    day = work[work.index.date == latest_day]
    if day.empty:
        return {"ret": None, "or15": "未取得", "vwap": "未取得", "ema": "未取得"}
    close = float(day["Close"].iloc[-1])
    open_ = float(day["Open"].iloc[0])
    ret = (close / open_ - 1) * 100 if open_ else None
    or15 = day.between_time("09:00", "09:15")
    or_state = "形成中"
    if not or15.empty and day.index[-1].time() >= pd.Timestamp("09:15").time():
        hi, lo = float(or15["High"].max()), float(or15["Low"].min())
        or_state = "上抜け" if close > hi else "下抜け" if close < lo else "レンジ内"
    vol = day["Volume"].fillna(0).astype(float)
    typical = (day["High"] + day["Low"] + day["Close"]) / 3
    vwap = float((typical * vol).sum() / vol.sum()) if vol.sum() else None
    ema9 = float(day["Close"].ewm(span=9, adjust=False).mean().iloc[-1])
    ema20 = float(day["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
    return {
        "ret": round(ret, 2) if ret is not None else None,
        "or15": or_state,
        "vwap": "上" if vwap is not None and close > vwap else "下" if vwap is not None else "未取得",
        "ema": "上向き" if ema9 > ema20 else "下向き",
    }


def strength(c20, c60, intraday, expected):
    vals = [x for x in (c20, c60, intraday) if x is not None]
    if not vals:
        return "未判定", 0
    sign = -1 if expected == "逆相関仮説" else 1
    aligned = [sign * x for x in vals]
    score = round(max(0, min(100, (sum(aligned) / len(aligned) + 1) * 50)))
    stable = len(aligned) >= 2 and all(x >= .25 for x in aligned)
    return ("確認" if stable else "不安定" if max(aligned) >= .25 else "不成立"), score


def main():
    cfg = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    names = {meta["ticker"]: name for name, meta in cfg["stocks"].items()}
    jp_day = [meta["ticker"] for meta in cfg["stocks"].values() if meta.get("style") in ("day", "both")]
    tickers = list(dict.fromkeys(jp_day + ["SNDK", "MU"]))
    daily_raw = yf.download(tickers, period="6mo", interval="1d", auto_adjust=False,
                            group_by="ticker", progress=False, threads=True, timeout=45)
    intra_raw = yf.download(jp_day, period="5d", interval="5m", auto_adjust=False,
                            group_by="ticker", progress=False, threads=True, timeout=45)
    daily = {t: frame_for(daily_raw, t) for t in tickers}
    intra = {t: frame_for(intra_raw, t) for t in jp_day}
    returns = {t: f["Close"].astype(float).pct_change() for t, f in daily.items() if not f.empty}

    rows = []
    used = set()
    for anchor, peer, relation, expected, reason in SPECIAL:
        if anchor not in daily or peer not in daily or daily[anchor].empty or daily[peer].empty:
            continue
        if relation.startswith("米国"):
            a, b = previous_us_to_japan(daily[anchor]["Close"], daily[peer]["Close"])
            intra_view = {"intraday_corr": None, "lead_bars": None, "bars": 0}
        else:
            a, b = returns[anchor], returns[peer]
            intra_view = intraday_metrics(intra.get(anchor, pd.DataFrame()), intra.get(peer, pd.DataFrame()))
        c20, n20 = corr(a, b, 20)
        c60, n60 = corr(a, b, 60)
        c20 = round(c20, 2) if c20 is not None else None
        c60 = round(c60, 2) if c60 is not None else None
        state, score = strength(c20, c60, intra_view["intraday_corr"], expected)
        rows.append({
            "anchor": names.get(anchor, "キオクシアHD（285A）"),
            "anchor_ticker": anchor, "peer": names.get(peer, peer), "peer_ticker": peer,
            "relation": relation, "expected": expected, "reason": reason,
            "corr20": c20, "corr60": c60, "sample20": n20, "sample60": n60,
            **intra_view, "state": state, "confidence": score,
            "anchor_today": today_view(intra.get(anchor, pd.DataFrame())),
            "peer_today": today_view(intra.get(peer, pd.DataFrame())),
            "decision": "売買の確認材料に使用" if state == "確認" else "この関係を売買根拠にしない",
        })
        used.add((anchor, peer))

    # Discover the strongest same-session positive and negative peer for each day-trade name.
    for anchor in jp_day:
        if anchor not in returns:
            continue
        candidates = []
        for peer in jp_day:
            if peer == anchor or peer not in returns or (anchor, peer) in used:
                continue
            c20, n20 = corr(returns[anchor], returns[peer], 20)
            c60, n60 = corr(returns[anchor], returns[peer], 60)
            if c20 is None or c60 is None:
                continue
            stable = c20 * c60 > 0
            candidates.append((c20, c60, n20, n60, peer, stable))
        if not candidates:
            continue
        positive = max(candidates, key=lambda x: (x[0] + x[1]) if x[5] else -9)
        negative = min(candidates, key=lambda x: (x[0] + x[1]) if x[5] else 9)
        for label, found in (("自動検出・正相関", positive), ("自動検出・逆相関", negative)):
            c20, c60, n20, n60, peer, stable = found
            if (label.endswith("正相関") and (c20 + c60) / 2 < .35) or (label.endswith("逆相関") and (c20 + c60) / 2 > -.35):
                continue
            iv = intraday_metrics(intra.get(anchor, pd.DataFrame()), intra.get(peer, pd.DataFrame()))
            expected = "逆相関仮説" if label.endswith("逆相関") else "正相関"
            state, score = strength(round(c20, 2), round(c60, 2), iv["intraday_corr"], expected)
            rows.append({
                "anchor": names.get(anchor, anchor), "anchor_ticker": anchor,
                "peer": names.get(peer, peer), "peer_ticker": peer,
                "relation": label, "expected": expected,
                "reason": "直近20日・60日から同時方向を自動検出",
                "corr20": round(c20, 2), "corr60": round(c60, 2),
                "sample20": n20, "sample60": n60, **iv,
                "state": state, "confidence": score,
                "anchor_today": today_view(intra.get(anchor, pd.DataFrame())),
                "peer_today": today_view(intra.get(peer, pd.DataFrame())),
                "decision": "売買の確認材料に使用" if state == "確認" else "この関係を売買根拠にしない",
            })

    rows.sort(key=lambda x: (x["anchor_ticker"] != "285A.T", -x["confidence"]))
    output = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "relationships": rows,
        "method": "日足20/60営業日＋日本株5分足5日。米国株は前営業日から日本翌営業日への先行相関。",
        "rule": "OR15・VWAP・EMA9/20を含む4/5一致が前提。相関だけで発注せず、3/5以下は見送り。",
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
