"""Methods on trial (試験中): virtual trades per method from the Collector's own ticks. Display only.

OWNER 2026-10-28 「コクピットの仮想売買は、今の①〜⑤も残したまま、デイトレ①②・EP・AIの採用手法を全部足して、手法ごとに
別々に記録して。−3万円の止めも手法ごと。画面には『試験中』として成績だけ出して、合図にはしない。毎日手法ごとの成績を集計して」

Inputs (both written on the PC, never part of the repo):
  RuntimeDir/trial_inputs_v1.json  for_date, per ticker prev_close / ma25 / dev_pct, and the AI's adopted methods
  RuntimeDir/records/<day>/ticks.csv  the Collector's prints of the watched issues (exchange_time, price)
Methods (100 shares, cost as the research: buy 0.10 %, interest 2.8 %/year per night):
  DT1  デイトレ① 10:00  prev close <= 25-day line -20 % and the open is -0.5..-2 % under the prev close -> buy the 10:00
       price, stop -2 %, sell the last print
  DT2  デイトレ② 11:30  at 11:30 down 3 %+ on the day and +0.5..+2 % above the open -> buy, stop -2 %, sell the last print
  EP   open 10 %+ above the prev close (under 20 %) -> buy the open, stop -8 %, sell the 10th session's last print
  AI:* the AI's adopted methods that can be run here (EP variants); others are listed as not runnable
Per method and day: once the closed trades of the day reach -30,000 yen, no new entries that day and the method's
open day trades are closed at that moment's price. Nothing here is a signal: no voice, no attention list, no Brain
input, no order. Multi-day positions persist in RuntimeDir/trial_positions_v1.json.
Output: RuntimeDir/trial_methods_v1.json (today + per-method totals of the recorded days) and
        RuntimeDir/records/<day>/trial_methods.json (the day's trades).
"""
from __future__ import annotations

import csv
import io
import json
import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "100b-v10-trial-methods-v1"
INPUT_SCHEMA = "100b-v10-trial-inputs-v1"
JST = timezone(timedelta(hours=9))
INPUT_FILE = "trial_inputs_v1.json"
POS_FILE = "trial_positions_v1.json"
OUT_FILE = "trial_methods_v1.json"
DAY_FILE = "trial_methods.json"
TICKS_FILE = "ticks.csv"
PREOPEN_FILE = "preopen.csv"
SHARES = 100
DAILY_LIMIT_YEN = -30000
COST_PCT = 0.10
RATE_DAY_PCT = 2.8 / 365
MAX_READ_BYTES = 64 * 1024 * 1024
HISTORY_DAYS = 60
# AI's adopted method names (研究スクリプト condition_bruteforce.py) that this module can run: (hold days, stop)
AI_RUNNABLE = {
    "勝ち型_EP 10%以上GUを寄りで買い→5日後の引け": (5, None),
    "勝ち型_EP 10%以上GUを寄りで買い→損切り−8%・10日後の引け": (10, 0.08),
}
LABELS = {"DT1": "デイトレ① 10:00 下げすぎの小さな窓下げ買い", "DT2": "デイトレ② 11:30 前日比−3%以下から戻した買い",
          "EP": "EP 10%以上GUを寄りで買い（損切り−8%・最長10日）"}


def _num(v):
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if x == x and x not in (float("inf"), float("-inf")) else None


def read_ticks(path: Path, state: dict) -> dict:
    """ticker -> [(exchange_time, price)] for the day, read incrementally (state keeps the offset)."""
    if state.get("path") != str(path):
        state.update(path=str(path), offset=0, header=None, ticks={})
    try:
        size = path.stat().st_size
    except OSError:
        return state["ticks"]
    if size < state["offset"]:
        state.update(offset=0, header=None, ticks={})
    if size == state["offset"]:
        return state["ticks"]
    with open(path, "rb") as f:
        f.seek(state["offset"])
        raw = f.read(min(size - state["offset"], MAX_READ_BYTES))
    end = raw.rfind(b"\n")
    if end < 0:
        return state["ticks"]
    chunk = raw[:end + 1]
    state["offset"] += len(chunk)
    lines = chunk.decode("utf-8-sig", errors="replace").splitlines()
    if state["header"] is None and lines:
        state["header"] = next(csv.reader([lines[0]]))
        lines = lines[1:]
    header = state["header"]
    for rec in csv.reader(io.StringIO("\n".join(lines))):
        if len(rec) != len(header):
            continue
        row = dict(zip(header, rec))
        t, p = (row.get("exchange_time") or "").strip(), _num(row.get("price"))
        if p and p > 0 and len(t) == 8 and "09:00:00" <= t <= "15:30:00":
            state["ticks"].setdefault(row.get("ticker", ""), []).append((t, p))
    return state["ticks"]


def load_inputs(runtime: Path, today: str):
    try:
        v = json.loads((runtime / INPUT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (not isinstance(v, dict) or v.get("schema_version") != INPUT_SCHEMA or v.get("real_submit_allowed") is not False
            or v.get("for_date") != today):
        return None
    return v


def price_at(ticks: list, hms: str):
    """Last print at or before hms (None when there is none)."""
    out = None
    for t, p in ticks:
        if t <= hms:
            out = p
        else:
            break
    return out


def run_day_trade(ticks: list, entry_hms: str, entry: float, stop_pct: float, until_hms: str):
    """(exit_time, exit_price, how) after an entry at entry_hms: the stop, else the last print up to until_hms."""
    stop = entry * (1 - stop_pct)
    last = None
    for t, p in ticks:
        if t <= entry_hms:
            continue
        if t > until_hms:
            break
        if p <= stop:
            return t, p, "損切り"
        last = (t, p)
    return (last[0], last[1], "引け") if last else (entry_hms, entry, "引け")


def _yen(entry, exit_, nights=0):
    pct = (exit_ / entry - 1) * 100 - COST_PCT - RATE_DAY_PCT * nights
    return round(pct, 3), round(pct / 100 * entry * SHARES)


def day_trades(ticks: dict, inputs: dict, preopen_ref: dict, now_hms: str) -> dict:
    """Candidates and trades of DT1 / DT2 for today (only closed trades count once the session is over)."""
    out = {"DT1": [], "DT2": []}
    for ticker, tk in ticks.items():
        tk = sorted(tk)
        if not tk:
            continue
        code = ticker.replace(".T", "")
        info = (inputs.get("tickers") or {}).get(code) or {}
        prev = preopen_ref.get(ticker) or _num(info.get("prev_close"))
        if not prev:
            continue
        open_ = tk[0][1]
        gap = (open_ / prev - 1) * 100
        dev = _num(info.get("dev_pct"))
        if dev is not None and dev <= -20 and -2.0 < gap <= -0.5 and now_hms >= "10:00:00":
            e = price_at(tk, "10:00:00")
            if e:
                out["DT1"].append({"ticker": ticker, "entry_time": "10:00:00", "entry": e, "gap_pct": round(gap, 2),
                                   "dev_pct": dev, "stop_pct": 0.02})
        if now_hms >= "11:30:00":
            e = price_at(tk, "11:30:00")
            if e:
                day_chg, from_open = (e / prev - 1) * 100, (e / open_ - 1) * 100
                if day_chg <= -3 and 0.5 < from_open <= 2.0:
                    out["DT2"].append({"ticker": ticker, "entry_time": "11:30:00", "entry": e,
                                       "day_chg_pct": round(day_chg, 2), "from_open_pct": round(from_open, 2), "stop_pct": 0.02})
    return out


def settle_day(method: str, cands: list, ticks: dict, now_hms: str) -> dict:
    """Run a method's day trades in entry order under the -30,000 yen per method and day."""
    trades, realized, limit_at = [], 0, None
    events = []
    for c in sorted(cands, key=lambda x: (x["entry_time"], x["ticker"])):
        tk = sorted(ticks.get(c["ticker"], []))
        if limit_at and c["entry_time"] >= limit_at:
            trades.append(dict(c, status="止め（−3万円）"))
            continue
        t, p, how = run_day_trade(tk, c["entry_time"], c["entry"], c["stop_pct"], min(now_hms, "15:30:00"))
        closed = how == "損切り" or now_hms >= "15:30:00"
        pct, yen = _yen(c["entry"], p)
        row = dict(c, exit_time=t, exit=p, how=how if closed else "持ち中", pct=pct, yen=yen,
                   status="CLOSED" if closed else "OPEN")
        trades.append(row)
        if closed:
            events.append((t, yen))
    for t, yen in sorted(events):
        realized += yen
        if realized <= DAILY_LIMIT_YEN and not limit_at:
            limit_at = t
    if limit_at:   # entries after the limit are dropped; open ones are closed at that moment
        for r in trades:
            still_open = r.get("status") == "OPEN" or (r.get("status") == "CLOSED" and r["entry_time"] <= limit_at
                                                      and str(r.get("exit_time")) > limit_at)
            if still_open:
                p = price_at(sorted(ticks.get(r["ticker"], [])), limit_at) or r["entry"]
                r.update(exit_time=limit_at, exit=p, how="止め（−3万円）", status="CLOSED")
                r["pct"], r["yen"] = _yen(r["entry"], p)
            elif r.get("status") == "CLOSED" and r["entry_time"] > limit_at:
                r.update(status="止め（−3万円）", pct=None, yen=None)
    return {"method": method, "label": LABELS.get(method, method), "trades": trades, "limit_hit_at": limit_at}


def multi_day(positions: list, ticks: dict, inputs: dict, preopen_ref: dict, today: str, now_hms: str, methods: dict) -> list:
    """Advance the open multi-day positions and add today's EP entries. methods: name -> (hold, stop)."""
    out = []
    for pos in positions:
        if pos.get("status") != "OPEN":
            continue
        if pos.get("last_day") != today:
            pos["sessions"] = int(pos.get("sessions", 0)) + 1
            pos["last_day"] = today
        tk = sorted(ticks.get(pos["ticker"], []))
        hold, stop = methods.get(pos["method"], (pos.get("hold", 10), pos.get("stop")))
        stop_px = pos["entry"] * (1 - stop) if stop else None
        for t, p in tk:
            if pos["sessions"] == 1 and t <= pos.get("entry_time", "09:00:00"):
                continue
            if stop_px and p <= stop_px:
                pos.update(status="CLOSED", exit_day=today, exit_time=t, exit=p, how="損切り")
                break
        if pos["status"] == "OPEN" and pos["sessions"] >= hold and now_hms >= "15:30:00" and tk:
            pos.update(status="CLOSED", exit_day=today, exit_time=tk[-1][0], exit=tk[-1][1], how=f"{hold}日目の引け")
        last = tk[-1][1] if tk else pos.get("mark")
        pos["mark"] = last
        nights = max(0, pos["sessions"] - 1)
        pos["pct"], pos["yen"] = _yen(pos["entry"], pos.get("exit") or last or pos["entry"], nights)
        out.append(pos)
    # today's entries: open 10 %+ above the prev close (under 20 %)
    have = {(p["method"], p["ticker"], p["entry_day"]) for p in positions}
    for ticker, tk in ticks.items():
        tk = sorted(tk)
        code = ticker.replace(".T", "")
        prev = preopen_ref.get(ticker) or _num(((inputs.get("tickers") or {}).get(code) or {}).get("prev_close"))
        if not tk or not prev:
            continue
        gap = (tk[0][1] / prev - 1) * 100
        if not (10 <= gap < 20):
            continue
        for m, (hold, stop) in methods.items():
            if (m, ticker, today) in have:
                continue
            positions.append({"method": m, "ticker": ticker, "entry_day": today, "entry_time": tk[0][0], "entry": tk[0][1],
                              "gap_pct": round(gap, 2), "hold": hold, "stop": stop, "sessions": 1, "last_day": today,
                              "status": "OPEN"})
            have.add((m, ticker, today))
    return positions


def _preopen_ref(day_dir: Path) -> dict:
    out = {}
    try:
        with open(day_dir / PREOPEN_FILE, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                p = _num(r.get("reference_price"))
                if p and str(r.get("captured_at", ""))[11:19] < "09:00:00":
                    out[r.get("ticker", "")] = p
    except OSError:
        pass
    return out


def _history(records: Path, today: str) -> dict:
    """Per method over the recorded days (closed trades): days, trades, mean %, PF, yen."""
    acc = {}
    try:
        days = sorted((p.name for p in records.iterdir() if p.is_dir() and len(p.name) == 10 and p.name <= today),
                      reverse=True)[:HISTORY_DAYS]
    except OSError:
        days = []
    for d in days:
        try:
            v = json.loads((records / d / DAY_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for m in v.get("methods", []):
            a = acc.setdefault(m["method"], {"label": m.get("label"), "days": set(), "pct": [], "yen": 0})
            for t in m.get("trades", []):
                if t.get("status") == "CLOSED" and t.get("pct") is not None and t.get("exit_day", d) == d:
                    a["days"].add(d)
                    a["pct"].append(t["pct"])
                    a["yen"] += t.get("yen") or 0
    out = {}
    for m, a in acc.items():
        v = a["pct"]
        g, l = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
        out[m] = {"label": a["label"], "days": len(a["days"]), "n": len(v), "mean_pct": round(statistics.mean(v), 3) if v else None,
                  "pf": round(g / l, 2) if l else None, "yen": a["yen"]}
    return out


def build(runtime: Path, *, now: datetime, state: dict) -> dict:
    runtime = Path(runtime)
    local = now.astimezone(JST)
    today, now_hms = local.date().isoformat(), local.strftime("%H:%M:%S")
    records = runtime / "records"
    day_dir = records / today
    inputs = load_inputs(runtime, today)
    ticks = read_ticks(day_dir / TICKS_FILE, state.setdefault("ticks", {})) if day_dir.is_dir() else {}
    pre = _preopen_ref(day_dir)
    methods_out, notes = [], []
    if inputs is None:
        notes.append("PCの入力（trial_inputs_v1.json）が今日の分ではない：デイトレ①は25日線の離れが分からないので止める")
    cands = day_trades(ticks, inputs or {}, pre, now_hms)
    if inputs is None:
        cands["DT1"] = []
    for m in ("DT1", "DT2"):
        methods_out.append(settle_day(m, cands[m], ticks, now_hms))
    ai = [n for n in ((inputs or {}).get("ai_methods") or [])]
    runnable = {"EP": (10, 0.08)}
    runnable.update({"AI:" + n: AI_RUNNABLE[n] for n in ai if n in AI_RUNNABLE})
    not_runnable = [n for n in ai if n not in AI_RUNNABLE]
    try:
        held = json.loads((runtime / POS_FILE).read_text(encoding="utf-8")).get("positions", [])
    except (OSError, ValueError):
        held = []
    held = multi_day(held, ticks, inputs or {}, pre, today, now_hms, runnable) if day_dir.is_dir() else held
    for m in runnable:
        mine = [p for p in held if p["method"] == m and (p["status"] == "OPEN" or p.get("exit_day") == today
                                                         or p.get("entry_day") == today)]
        methods_out.append({"method": m, "label": LABELS.get(m, m.replace("AI:", "AIの採用：")), "trades": [
            dict(p, entry_time=p.get("entry_time"), status=p["status"]) for p in mine], "limit_hit_at": None})
    kept = [p for p in held if p["status"] == "OPEN" or p.get("exit_day", "") >= (local.date() - timedelta(days=30)).isoformat()]
    tmp = runtime / (POS_FILE + ".tmp")
    tmp.write_text(json.dumps({"positions": kept, "real_submit_allowed": False}, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, runtime / POS_FILE)
    day = {"date": today, "methods": methods_out, "notes": notes, "ai_not_runnable": not_runnable,
           "real_submit_allowed": False, "trade_instruction": False}
    if day_dir.is_dir():
        tmp = day_dir / (DAY_FILE + ".tmp")
        tmp.write_text(json.dumps(day, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, day_dir / DAY_FILE)
    view = {"schema_version": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(), "date": today,
            "status": "TRIAL_RECORD_ONLY", "today": methods_out, "notes": notes, "ai_not_runnable": not_runnable,
            "history": _history(records, today), "shares": SHARES, "daily_limit_yen": DAILY_LIMIT_YEN,
            "real_submit_allowed": False, "trade_instruction": False}
    target = runtime / OUT_FILE
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)
    return view
