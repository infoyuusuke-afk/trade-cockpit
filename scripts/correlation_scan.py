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

# OWNER 2026-10-24 「相関の仕組みの直し」 (PC check 2026-10-24, Claudeブレイン\correlation_check.py):
# - the US previous day explains the Tokyo OPENING GAP (SNDK r=+0.60, MU r=+0.53 for Kioxia, both halves),
#   not the move after the open (r about 0) -> the US relations are measured on the gap only;
# - Korea's "previous day" is not a lead (Seoul trades at the same hours as Tokyo; r +0.08) -> removed;
# - pairs picked automatically from 20/60-day correlations appear by chance (56% of random pairs pass) -> removed.
# Each relation is now judged on its whole history, both halves separately and its big-move days.
US_LEAD = [
    ("285A.T", "SNDK", "NAND・SSD価格と米国メモリ株"),
    ("285A.T", "MU", "DRAM/NANDを含む米国メモリ地合い"),
    ("8035.T", "SOXX", "米国半導体株の地合い（SOX連動ETF）"),
    ("6857.T", "SOXX", "米国半導体株の地合い（SOX連動ETF）"),
    ("6920.T", "SOXX", "米国半導体株の地合い（SOX連動ETF）"),
    ("6146.T", "SOXX", "米国半導体株の地合い（SOX連動ETF）"),
    ("7735.T", "SOXX", "米国半導体株の地合い（SOX連動ETF）"),
]
REMOVED = [
    {"relation": "韓国前日→日本翌日（SKハイニックス・サムスン電子→キオクシア）",
     "reason": "韓国は東京と同じ時間に取引しているため「前日」は先行にならない（相関+0.08、同じ向き51%）"},
    {"relation": "任天堂(7974)とキオクシアの逆相関仮説",
     "reason": "検証の裏付けがない仮説"},
    {"relation": "20日・60日の相関から自動で選んだ正相関・逆相関",
     "reason": "無関係な100系列から選んでも56%で『確認』になる（偶然で出る）"},
]
BIG_MOVE_PCT = 2.0      # US previous-day move counted as a big day (|ret| >= 2%)
MIN_DAYS = 120          # whole-history days needed before any verdict
MIN_BIG_DAYS = 30       # big days needed before any verdict


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


def previous_day_to_japan(jp_close, peer_close):
    """Prior-session peer return vs next-session Japan return.

    Originally US-only (SNDK/MU); reused as-is for Korean peers (000660.KS/
    005930.KS) since the lag relationship is identical, just a different
    prior market.
    """
    jp = jp_close.copy()
    us = peer_close.copy()
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


def gap_test(jp_daily, peer_close):
    """Tokyo opening gap (open / previous close) against the US previous-day return, on the whole
    history, its two halves, and the big US days; the move after the open is reported too."""
    jp = jp_daily.copy()
    jp.index = pd.to_datetime(jp.index).tz_localize(None).normalize()
    us = peer_close.copy()
    us.index = pd.to_datetime(us.index).tz_localize(None).normalize()
    us_ret = us.astype(float).pct_change().dropna().sort_index()
    close = jp["Close"].astype(float)
    gap = (jp["Open"].astype(float) / close.shift(1) - 1).dropna()
    after = (close / jp["Open"].astype(float) - 1).reindex(gap.index)
    rows = []
    for dt, g in gap.items():
        prior = us_ret[us_ret.index < dt]
        if not prior.empty:
            rows.append((dt, float(g) * 100, float(after.get(dt, float("nan"))) * 100, float(prior.iloc[-1]) * 100))
    f = pd.DataFrame(rows, columns=["date", "gap", "after", "us"]).set_index("date").dropna()
    out = {"days": len(f), "corr_all": None, "corr_first_half": None, "corr_second_half": None,
           "corr_after_open": None, "big_days": 0, "big_same_dir_pct": None, "corr20": None, "corr60": None,
           "since": str(f.index[0].date()) if len(f) else None}
    if len(f) < 12:
        return out
    half = len(f) // 2
    out.update({
        "corr_all": round(f.gap.corr(f.us), 2),
        "corr_first_half": round(f.gap.iloc[:half].corr(f.us.iloc[:half]), 2),
        "corr_second_half": round(f.gap.iloc[half:].corr(f.us.iloc[half:]), 2),
        "corr_after_open": round(f.after.corr(f.us), 2),
        "corr20": round(f.gap.tail(20).corr(f.us.tail(20)), 2) if len(f) >= 20 else None,
        "corr60": round(f.gap.tail(60).corr(f.us.tail(60)), 2) if len(f) >= 60 else None,
    })
    big = f[f.us.abs() >= BIG_MOVE_PCT]
    out["big_days"] = len(big)
    if len(big):
        out["big_same_dir_pct"] = round(float(((big.gap > 0) == (big.us > 0)).mean() * 100), 1)
    return out


def gap_verdict(r):
    """確認: enough history, both halves agree, the big US days usually set the gap's direction."""
    halves = [r.get("corr_first_half"), r.get("corr_second_half")]
    hit = r.get("big_same_dir_pct")
    if r["days"] < MIN_DAYS or r["big_days"] < MIN_BIG_DAYS or None in halves or hit is None:
        return "根拠不足", 0
    if min(halves) >= .30 and hit >= 65:
        return "確認", round(hit)
    if min(halves) >= .20 and hit >= 60:
        return "不安定", round(hit)
    return "不成立", round(hit)


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
    anchors = list(dict.fromkeys(x[0] for x in US_LEAD))
    peers = list(dict.fromkeys(x[1] for x in US_LEAD))
    daily_raw = yf.download(anchors + peers, period="2y", interval="1d", auto_adjust=False,
                            group_by="ticker", progress=False, threads=True, timeout=45)
    intra_raw = yf.download(anchors, period="5d", interval="5m", auto_adjust=False,
                            group_by="ticker", progress=False, threads=True, timeout=45)
    daily = {x: frame_for(daily_raw, x) for x in anchors + peers}
    intra = {x: frame_for(intra_raw, x) for x in anchors}

    rows = []
    for anchor, peer, reason in US_LEAD:
        if daily[anchor].empty or daily[peer].empty:
            continue
        r = gap_test(daily[anchor], daily[peer]["Close"])
        state, score = gap_verdict(r)
        rows.append({
            "anchor": names.get(anchor, anchor), "anchor_ticker": anchor, "peer": peer, "peer_ticker": peer,
            "relation": "米国前日→日本の寄り（窓）", "expected": "正相関", "reason": reason,
            "corr20": r["corr20"], "corr60": r["corr60"], "sample20": min(20, r["days"]), "sample60": min(60, r["days"]),
            "intraday_corr": None, "lead_bars": None, "bars": 0,
            "gap_test": r, "state": state, "confidence": score,
            "anchor_today": today_view(intra.get(anchor, pd.DataFrame())),
            "peer_today": {"ret": None, "or15": "—", "vwap": "—", "ema": "—"},
            "decision": ("寄りの窓の向きの確認に使う（寄った後の方向には使わない）" if state == "確認"
                         else "この関係を売買根拠にしない"),
        })

    rows.sort(key=lambda x: (x["state"] != "確認", x["anchor_ticker"] != "285A.T", -x["confidence"]))
    output = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "relationships": rows,
        "removed": REMOVED,
        "method": ("米国の前日の騰落と、東京の寄り付きの窓（始値÷前日終値）の関係だけを見る。全期間・前半・後半の相関と、"
                   "米国が±%.0f%%以上動いた日に窓が同じ向きだった割合。%d日以上・大きな日%d日以上で、前半・後半とも"
                   "相関0.30以上かつ同じ向き65%%以上なら『確認』。" % (BIG_MOVE_PCT, MIN_DAYS, MIN_BIG_DAYS)),
        "rule": "相関は寄りの窓の向きの確認だけに使う。寄った後の方向・発注の根拠にしない。OR15・VWAP・EMA9/20を含む4/5一致が前提。",
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
