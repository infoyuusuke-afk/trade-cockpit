"""OWNER 2026-11-08 「ザラバ中にゾーンに入った場合も音声でしりたい」→ 2026-11-10 「B 場中はナスダック100の先物で目安を出す」
OWNER 2026-11-10 「SOXの目安の計算と音声のスクリプトをGitHubに上げて監査に回して。監査が通って承認するまで、5分おきの定時からは外して音声は出さない」

The logic of the PC job that writes RuntimeDir/sox_proxy_v1.json (read by the SOX tab through /sox_proxy.json) and decides what to say.
No paths, no network, no voice call here: the PC wrapper fetches the prices, reads/writes the files and speaks. Display and voice only;
nothing here can place an order (the file always says real_submit_allowed=false and trade_instruction=false).

SOX does not trade during the Tokyo session; Nasdaq-100 futures do. The gauge is
    estimate = SOX close × (1 + beta × Nasdaq-100 futures change since that SOX close)
beta = the slope of SOX daily % on futures daily % over about a year (with the spread of the daily error and the correlation).
It is not SOX itself, and the futures prices the PC uses are about 10 minutes late.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone

SCHEMA = "100b-v10-sox-proxy-v1"
NEAR = 0.02                  # within 2 % below the zone counts as near
SESSION = ("09:00", "15:30")
MIN_FIT_DAYS = 120
SAY_IN = "SOXの目安が注意ゾーンに入りました。ナスダック100先物からの目安で、SOXそのものではありません。"
SAY_NEAR = "SOXの目安が注意ゾーンに近づいています。ナスダック100先物からの目安で、SOXそのものではありません。"


def fit_beta(sox: dict, nq: dict) -> dict:
    """sox / nq: {date: close}. Day-to-day % changes on the dates both have; slope, error spread (%), correlation, number of days."""
    keys = sorted(k for k in set(sox) & set(nq) if _pos(sox[k]) and _pos(nq[k]))
    xs, ys = [], []
    for a, b in zip(keys, keys[1:]):
        xs.append(nq[b] / nq[a] - 1)
        ys.append(sox[b] / sox[a] - 1)
    if len(xs) < MIN_FIT_DAYS:
        raise ValueError("FIT_TOO_SHORT")
    mx, my = statistics.mean(xs), statistics.mean(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    if vx <= 0:
        raise ValueError("FIT_FLAT")
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx
    err = statistics.pstdev([y - slope * x for x, y in zip(xs, ys)])
    return {"beta": round(slope, 3), "err_pct": round(err * 100, 2), "corr": round(statistics.correlation(xs, ys), 3), "days": len(xs)}


def us_close_ts(as_of: str) -> float:
    """16:00 New York on the US date as_of: UTC−4 from the second Sunday of March to the first Sunday of November, else UTC−5."""
    d = date.fromisoformat(as_of)
    mar = date(d.year, 3, 8) + timedelta(days=(6 - date(d.year, 3, 8).weekday()) % 7)
    nov = date(d.year, 11, 1) + timedelta(days=(6 - date(d.year, 11, 1).weekday()) % 7)
    off = -4 if mar <= d < nov else -5
    return datetime(d.year, d.month, d.day, 16, 0, tzinfo=timezone(timedelta(hours=off))).timestamp()


def base_price(bars: list, close_ts: float):
    """bars: [(start timestamp, close)], oldest first. The last bar that starts before the SOX close (a bar is stamped at its start,
    so the one starting at 16:00 is already after the close)."""
    base = [c for t, c in bars if t < close_ts and _pos(c)]
    return base[-1] if base else None


def state_of(est: float, lo: float, hi: float) -> str:
    if lo <= est <= hi:
        return "IN"
    if lo * (1 - NEAR) <= est < lo:
        return "NEAR"
    return "ABOVE" if est > hi else "BELOW"


def in_session(hm: str) -> bool:
    return SESSION[0] <= hm <= SESSION[1]


def make_doc(day: str, hm: str, scenario: dict, fit: dict, bars: list, jst=timezone(timedelta(hours=9))) -> dict:
    """scenario: the morning file (close, as_of, zone.from/to, flags false). bars: the futures 5-minute bars."""
    if scenario.get("real_submit_allowed") is not False or scenario.get("trade_instruction") is not False:
        raise ValueError("SCENARIO_FLAGS")
    z = scenario.get("zone") or {}
    close, lo, hi = float(scenario["close"]), float(z["from"]), float(z["to"])
    if not (_pos(close) and _pos(lo) and _pos(hi) and lo < hi):
        raise ValueError("SCENARIO_NUMBERS")
    as_of = str(scenario["as_of"])
    nq0 = base_price(bars, us_close_ts(as_of))
    if nq0 is None:
        raise ValueError("NQ_BASE_MISSING")
    good = [(t, c) for t, c in bars if _pos(c)]
    t1, nq1 = good[-1]
    if t1 < us_close_ts(as_of):
        raise ValueError("NQ_NOT_AFTER_CLOSE")
    chg = nq1 / nq0 - 1
    est = close * (1 + fit["beta"] * chg)
    return {"schema_version": SCHEMA, "real_submit_allowed": False, "trade_instruction": False,
            "date": day, "made_at": hm, "sox_close": round(close, 1), "sox_as_of": as_of,
            "nq_base": round(nq0, 2), "nq_now": round(nq1, 2), "nq_time": datetime.fromtimestamp(t1, jst).strftime("%H:%M"),
            "nq_change_pct": round(chg * 100, 2), "beta": fit["beta"], "err_pct": fit["err_pct"], "corr": fit["corr"], "fit_days": fit["days"],
            "estimate": round(est), "zone_from": round(lo), "zone_to": round(hi), "to_zone_pct": round((lo / est - 1) * 100, 2),
            "state": state_of(est, lo, hi), "note": "ナスダック100先物（約10分遅れ）からの目安。SOXそのものではない。表示と音声だけ・注文なし"}


def what_to_say(state: str, said: dict, hm: str):
    """(text or None, the record to keep once it was said). IN once a day (it also covers NEAR), NEAR once a day."""
    said = dict(said or {})
    if state == "IN" and not said.get("IN"):
        said["IN"] = hm
        said.setdefault("NEAR", hm)
        return SAY_IN, said
    if state == "NEAR" and not said.get("NEAR"):
        said["NEAR"] = hm
        return SAY_NEAR, said
    return None, said


def _pos(v) -> bool:
    try:
        return math.isfinite(float(v)) and float(v) > 0
    except (TypeError, ValueError):
        return False
