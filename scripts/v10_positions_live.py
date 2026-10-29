"""Virtual holdings during the session (display and voice only; no orders).

OWNER 2026-10-23:
- 「仮想売買するならその銘柄は次の朝まで表示」: the carry-over candidates fixed at 15:25
  (records/<day>/overnight_hold_final.csv) are held from 15:25 until the next trading
  day's 15:30 scoring, and are listed until then.
- 「保有中は枠青」: each rule ①②④⑤ signal of today (records/<day>/brain_rule_signals.csv)
  is replayed on today's recorded ticks with the rule Shadow's own replay (fill window,
  stop, target, longest hold, 15:20 exit): WAITING (not yet filled, fill window open),
  OPEN (filled, not yet stopped, targeted or timed out) or CLOSED / NOT_FILLED.
- 8:50 and 15:30 voice: the Collector reads the counts written here.

Swing and value have no holdings record yet (their tabs list candidates only), so they
are reported as None, never as zero holdings.

Ticks are read incrementally from records/<day>/ticks.csv (the byte offset is kept in
the caller's state), only for issues that have a rule signal today. The replay function
is the pinned v10_signal_ev_table module passed in by the observer. Virtual only:
real_submit_allowed is always false.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path

SCHEMA = "100b-v10-positions-live-v1"
JST = timezone(timedelta(hours=9))
OUT_FILE = "positions_live_v1.json"
RULE_SIGNALS_FILE = "brain_rule_signals.csv"
OVERNIGHT_FILE = "overnight_hold_final.csv"
TICKS_FILE = "ticks.csv"
OVERNIGHT_SCORED_AT = "15:30"
MAX_READ_BYTES = 64 * 1024 * 1024
# OWNER 2026-10-27 「1回の損切り、1日の負けの上限3万円、6146・6920・285Aは仮想だけ、の決まりをブレインの仮想売買に入れて、
# おれの実際の成績と毎日並べて」: the OWNER's rules are applied to today's rule trades as a second, virtual tally
# (100 shares each, cost included). A trade without a stop is not counted; after the closed loss of the day reaches
# 30,000 yen no new trade is counted; 6146 / 6920 / 285A are tallied apart as virtual only. Kept per day in
# records/<day>/owner_rules_virtual.json. The real account side is added on the screen only (never read here).
OWNER_RULES_FILE = "owner_rules_virtual.json"
OWNER_SHARES = 100
OWNER_DAILY_LIMIT_YEN = -30000
OWNER_VIRTUAL_ONLY = ("6146", "6920", "285A")
OWNER_HISTORY_DAYS = 20
# OWNER 2026-10-27 「ショートリバの初動検知（大きく下げた銘柄で、大きい買いの約定・売り板が薄くなる・安値を割らない）を記録と
# 表示と声だけで作って、その後の戻りを毎日集計して」「あがりきったところで、ショートINする」: read from
# records/<day>/market_snapshots.csv (every ~12 s, 100 stocks). A first move is a snapshot where
#   - the price is 4 % or more under the day's high and under VWAP           (大きく下げた)
#   - the volume traded since the last snapshot is 5x the median of the previous 20 and the price is at or
#     above the previous ask                                                  (大きい買いの約定, estimated)
#   - the best ask quantity is half or less of its previous 10-snapshot average, or the total ask (OVER) is
#     20 % or more lower than 10 snapshots before                             (売り板が薄くなる)
#   - the day's low is 3 minutes old or more and not broken                   (安値を割らない)
# One per stock per 60 minutes, 09:30-15:00. Each is followed until 15:20: the highest price (the top of the
# rebound and when), the lowest, and the fall from the top to 15:20 (what a short at the top would have got).
# OWNER 2026-10-27 「ショートリバの2段の合図（初動＝まだ売るな、上がり切り＝ショート候補と損切りの目安）」: the first move says
# "not yet"; the second, 上がり切り, comes when the rebound has risen TOP_MIN_RISE_PCT or more from the first move, has
# made no new high for TOP_STALL_MIN minutes, and the price is TOP_PULLBACK_PCT under that high (before 15:00). Its
# stop guide is the rebound high. Each 上がり切り is followed as a virtual short to 15:20 or the stop.
# Record, screen and voice only; no order.
REBOUND_SIGNALS_FILE = "short_rebound_signals.csv"
REBOUND_OUTCOMES_FILE = "short_rebound_outcomes.json"
REBOUND_TOPS_FILE = "short_rebound_tops.csv"
SNAPSHOTS_FILE = "market_snapshots.csv"
REBOUND_FIELDS = ["detected_at", "ticker", "name", "price", "day_high", "day_low", "drop_from_high_pct", "vwap",
                  "volume_x", "ask_qty_ratio", "over_ratio", "low_age_min"]
TOP_FIELDS = ["top_at", "ticker", "name", "price", "stop", "first_move_at", "first_move_price", "rise_pct", "stall_min"]


def _rows(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _read_new_ticks(path: Path, state: dict, wanted: set) -> None:
    """Append new rows of the wanted tickers to state['ticks'] (ticker -> [(time, seq, price)])."""
    if state.get("wanted") != sorted(wanted) or state.get("path") != str(path):
        state.update(path=str(path), wanted=sorted(wanted), offset=0, header=None, seq=0, ticks={})
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size < state["offset"]:  # a new or truncated file: start over
        state.update(offset=0, header=None, seq=0, ticks={})
    if size == state["offset"] or not wanted:
        return
    with open(path, "rb") as f:
        f.seek(state["offset"])
        raw = f.read(min(size - state["offset"], MAX_READ_BYTES))
    end = raw.rfind(b"\n")
    if end < 0:
        return
    chunk = raw[:end + 1]
    state["offset"] += len(chunk)
    text = chunk.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    if state["header"] is None and lines:
        state["header"] = next(csv.reader([lines[0]]))
        lines = lines[1:]
    header = state["header"]
    for rec in csv.reader(io.StringIO("\n".join(lines))):
        state["seq"] += 1
        if len(rec) != len(header):
            continue
        row = dict(zip(header, rec))
        ticker = row.get("ticker", "")
        if ticker not in wanted:
            continue
        try:
            price = float(str(row.get("price", "")).replace(",", ""))
        except ValueError:
            continue
        t = (row.get("exchange_time") or "").strip()
        if price <= 0 or len(t) != 8:
            continue
        state["ticks"].setdefault(ticker, []).append((t, state["seq"], price))


def _previous_day_dir(records: Path, today: str):
    try:
        days = sorted(p.name for p in Path(records).iterdir() if p.is_dir() and p.name < today and len(p.name) == 10)
    except OSError:
        return None
    # OWNER 2026-10-26 「持ち越しは、空のファイルを飛ばすのではなく、土日の日付のフォルダだけ飛ばして」:
    # Saturday 00:00 wrote a header-only file into the Saturday folder; Saturday and Sunday folders are never
    # the previous trading day. A weekday file with no rows still means "no holds that day".
    for name in reversed(days):
        try:
            if datetime.strptime(name, "%Y-%m-%d").weekday() >= 5:
                continue
        except ValueError:
            continue
        if (Path(records) / name / OVERNIGHT_FILE).is_file():
            return Path(records) / name
    return None


def _overnight(day_dir: Path, *, valid_until: str) -> list[dict]:
    out = []
    for r in _rows(day_dir / OVERNIGHT_FILE):
        label = str(r.get("hold_signal") or "")
        side = "LONG" if "ロング" in label else "SHORT" if "ショート" in label else None
        if side is None:
            continue
        out.append({"ticker": r.get("ticker"), "name": r.get("name"), "side": side,
                    "decided_at": r.get("finalized_at"), "reference_price": r.get("reference_price_1525"),
                    "valid_until": valid_until})
    return out


def _num(v):
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _hms_sec(t) -> int:
    try:
        h, m, sec = str(t).split(":")
        return int(h) * 3600 + int(m) * 60 + int(float(sec))
    except ValueError:
        return -1


class ReboundDetector:
    """Per-stock state over the day's snapshots (fed oldest first); pure, so research can replay past days."""

    DROP_PCT = -4.0       # under the day's high
    VOLUME_X = 5.0        # traded since the last snapshot vs the median of the previous 20
    ASK_RATIO = 0.5       # best ask quantity vs its previous 10-snapshot average
    OVER_RATIO = 0.8      # total ask (OVER) vs 10 snapshots before
    LOW_AGE_MIN = 3.0
    TOP_MIN_RISE_PCT = 0.8   # the rebound from the first move's price
    TOP_STALL_MIN = 3.0      # minutes without a new rebound high
    TOP_PULLBACK_PCT = 0.3   # the price under the rebound high

    def __init__(self, **kw):
        self.s = {}
        self.signals = []
        self.tops = []
        for k, v in kw.items():
            setattr(self, k, v)

    def feed(self, row: dict):
        ticker = row.get("ticker") or ""
        t = str(row.get("captured_at") or "")[11:19]
        price, vol, vwap = _num(row.get("price")), _num(row.get("volume")), _num(row.get("vwap"))
        ask, ask_qty, over = _num(row.get("ask")), _num(row.get("ask_qty")), _num(row.get("over"))
        if not ticker or len(t) != 8 or not price or price <= 0 or t < "09:00:00" or t > "15:30:00":
            return None
        st = self.s.setdefault(ticker, {"hist": [], "high": price, "low": price, "low_t": t, "last_sig": -10 ** 9,
                                        "name": row.get("name") or "", "follow": []})
        if price > st["high"]:
            st["high"] = price
        if price < st["low"]:
            st["low"], st["low_t"] = price, t
        if t <= "15:20:00":
            for f in st["follow"]:
                if price > f["peak"]:
                    f["peak"], f["peak_at"] = price, t
                f["trough"] = min(f["trough"], price)
                f["last"], f["last_at"] = price, t
                top = f.get("top")
                if top is None:
                    p0 = f["sig"]["price"]
                    stall = (_hms_sec(t) - _hms_sec(f["peak_at"])) / 60
                    if (t <= "15:00:00" and (f["peak"] / p0 - 1) * 100 >= self.TOP_MIN_RISE_PCT and stall >= self.TOP_STALL_MIN
                            and price <= f["peak"] * (1 - self.TOP_PULLBACK_PCT / 100)):
                        f["top"] = top = {"top_at": str(row.get("captured_at"))[:19], "ticker": ticker, "name": st["name"],
                                          "price": price, "stop": f["peak"], "first_move_at": f["sig"]["detected_at"],
                                          "first_move_price": p0, "rise_pct": round((f["peak"] / p0 - 1) * 100, 2),
                                          "stall_min": round(stall, 1)}
                        f["short"] = {"best": price, "last": price, "last_at": t, "stopped_at": None}
                        self.tops.append(top)
                elif f["short"]["stopped_at"] is None:
                    sh = f["short"]
                    if price >= top["stop"]:
                        sh["stopped_at"], sh["last"] = t, top["stop"]
                    else:
                        sh["best"] = min(sh["best"], price)
                        sh["last"] = price
                    sh["last_at"] = t
        hist = st["hist"]
        prev = hist[-1] if hist else None
        dvol = (vol - prev["vol"]) if (prev and vol is not None and prev["vol"] is not None) else None
        sig = None
        # 11:30-12:35 is skipped: the first afternoon snapshot carries the whole lunch-break volume
        if (prev and len(hist) >= 20 and dvol is not None and dvol > 0 and "09:30:00" <= t <= "15:00:00"
                and not ("11:30:00" <= t <= "12:35:00")):
            past = sorted(h["dvol"] for h in hist[-20:] if h["dvol"] is not None and h["dvol"] >= 0)
            med = past[len(past) // 2] if past else None
            asks = [h["ask_qty"] for h in hist[-10:] if h["ask_qty"]]
            avg_ask = sum(asks) / len(asks) if asks else None
            over10 = hist[-10]["over"]
            drop = (price / st["high"] - 1) * 100
            vol_x = dvol / med if med else None
            ask_ratio = ask_qty / avg_ask if (ask_qty is not None and avg_ask) else None
            over_ratio = over / over10 if (over is not None and over10) else None
            low_age = (_hms_sec(t) - _hms_sec(st["low_t"])) / 60
            if (drop <= self.DROP_PCT and vwap and price < vwap
                    and vol_x is not None and vol_x >= self.VOLUME_X and prev["ask"] and price >= prev["ask"]
                    and ((ask_ratio is not None and ask_ratio <= self.ASK_RATIO)
                         or (over_ratio is not None and over_ratio <= self.OVER_RATIO))
                    and low_age >= self.LOW_AGE_MIN and _hms_sec(t) - st["last_sig"] >= 3600):
                st["last_sig"] = _hms_sec(t)
                sig = {"detected_at": str(row.get("captured_at"))[:19], "ticker": ticker, "name": st["name"],
                       "price": price, "day_high": st["high"], "day_low": st["low"], "drop_from_high_pct": round(drop, 2),
                       "vwap": round(vwap, 2), "volume_x": round(vol_x, 1),
                       "ask_qty_ratio": None if ask_ratio is None else round(ask_ratio, 2),
                       "over_ratio": None if over_ratio is None else round(over_ratio, 2), "low_age_min": round(low_age, 1)}
                st["follow"].append({"sig": sig, "peak": price, "peak_at": t, "trough": price, "last": price, "last_at": t})
                self.signals.append(sig)
        hist.append({"vol": vol, "dvol": dvol, "ask": ask, "ask_qty": ask_qty, "over": over})
        if len(hist) > 40:
            del hist[0]
        return sig

    def outcomes(self) -> list:
        out = []
        for st in self.s.values():
            for f in st["follow"]:
                p0 = f["sig"]["price"]
                out.append({"detected_at": f["sig"]["detected_at"], "ticker": f["sig"]["ticker"], "name": f["sig"]["name"],
                            "price": p0, "peak": f["peak"], "peak_at": f["peak_at"],
                            "rebound_pct": round((f["peak"] / p0 - 1) * 100, 3),
                            "minutes_to_peak": round((_hms_sec(f["peak_at"]) - _hms_sec(f["sig"]["detected_at"][11:19])) / 60, 1),
                            "worst_pct": round((f["trough"] / p0 - 1) * 100, 3),
                            "low_broken": f["trough"] < f["sig"]["day_low"],
                            "last_at": f["last_at"], "end_pct": round((f["last"] / p0 - 1) * 100, 3),
                            "fall_from_peak_pct": round((f["last"] / f["peak"] - 1) * 100, 3),
                            "final": f["last_at"] >= "15:19:00", "top": self._top_outcome(f)})
        return sorted(out, key=lambda x: x["detected_at"])

    @staticmethod
    def _top_outcome(f):
        top = f.get("top")
        if not top:
            return None
        sh, e = f["short"], top["price"]
        return dict(top, short_pct=round((1 - sh["last"] / e) * 100, 3), best_pct=round((1 - sh["best"] / e) * 100, 3),
                    stopped_at=sh["stopped_at"], last_at=sh["last_at"],
                    minutes_from_first_move=round((_hms_sec(top["top_at"][11:19]) - _hms_sec(top["first_move_at"][11:19])) / 60, 1),
                    final=sh["stopped_at"] is not None or f["last_at"] >= "15:19:00")


def rebound_summary(rows: list) -> dict:
    done = [r for r in rows if r.get("final")]
    if not done:
        return {"n": 0}

    def avg(k):
        return round(sum(float(r[k]) for r in done) / len(done), 3)
    out = {"n": len(done), "avg_rebound_pct": avg("rebound_pct"), "avg_minutes_to_peak": avg("minutes_to_peak"),
           "avg_fall_from_peak_pct": avg("fall_from_peak_pct"), "avg_end_pct": avg("end_pct"),
           "low_broken_pct": round(sum(1 for r in done if r["low_broken"]) / len(done) * 100, 1),
           "rebound_1pct_or_more": sum(1 for r in done if r["rebound_pct"] >= 1)}
    tops = [r["top"] for r in done if r.get("top") and r["top"].get("final")]
    if tops:
        wins = [x["short_pct"] for x in tops if x["short_pct"] > 0]
        loss = -sum(x["short_pct"] for x in tops if x["short_pct"] < 0)
        out["tops"] = {"n": len(tops), "avg_short_pct": round(sum(x["short_pct"] for x in tops) / len(tops), 3),
                       "win_pct": round(len(wins) / len(tops) * 100, 1),
                       "pf": round(sum(wins) / loss, 2) if loss else None,
                       "stopped_pct": round(sum(1 for x in tops if x["stopped_at"]) / len(tops) * 100, 1),
                       "avg_best_pct": round(sum(x["best_pct"] for x in tops) / len(tops), 3),
                       "avg_minutes_from_first_move": round(sum(x["minutes_from_first_move"] for x in tops) / len(tops), 1)}
    else:
        out["tops"] = {"n": 0}
    return out


def _short_rebound(day_dir: Path, records: Path, today: str, state: dict) -> dict:
    """Feed new snapshot rows, append new first moves to the day's CSV, write the outcomes and the history."""
    path = day_dir / SNAPSHOTS_FILE
    if state.get("day") != today:
        state.clear()
        state.update(day=today, offset=0, header=None, det=ReboundDetector())
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size < state["offset"]:
        state.update(offset=0, header=None, det=ReboundDetector())
    if size > state["offset"]:
        with open(path, "rb") as f:
            f.seek(state["offset"])
            raw = f.read(min(size - state["offset"], MAX_READ_BYTES))
        end = raw.rfind(b"\n")
        if end >= 0:
            state["offset"] += end + 1
            lines = raw[:end + 1].decode("utf-8-sig", errors="replace").splitlines()
            if state["header"] is None and lines:
                state["header"] = next(csv.reader([lines[0]]))
                lines = lines[1:]
            for rec in csv.reader(io.StringIO("\n".join(lines))):
                if len(rec) == len(state["header"]):
                    state["det"].feed(dict(zip(state["header"], rec)))
    det = state["det"]
    today_out = det.outcomes()
    if day_dir.is_dir():
        sig_path = day_dir / REBOUND_SIGNALS_FILE
        have = {(r.get("ticker"), r.get("detected_at")) for r in _rows(sig_path)}
        new = [x for x in det.signals if (x["ticker"], x["detected_at"]) not in have]
        if new:
            first = not sig_path.is_file()
            with open(sig_path, "a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
                w = csv.DictWriter(f, fieldnames=REBOUND_FIELDS)
                if first:
                    w.writeheader()
                w.writerows(new)
        top_path = day_dir / REBOUND_TOPS_FILE
        have_tops = {(r.get("ticker"), r.get("top_at")) for r in _rows(top_path)}
        new_tops = [x for x in det.tops if (x["ticker"], x["top_at"]) not in have_tops]
        if new_tops:
            first = not top_path.is_file()
            with open(top_path, "a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
                w = csv.DictWriter(f, fieldnames=TOP_FIELDS)
                if first:
                    w.writeheader()
                w.writerows(new_tops)
        tmp = day_dir / (REBOUND_OUTCOMES_FILE + ".tmp")
        tmp.write_text(json.dumps({"date": today, "outcomes": today_out}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, day_dir / REBOUND_OUTCOMES_FILE)
    past = []
    try:
        names = sorted((p.name for p in Path(records).iterdir() if p.is_dir() and len(p.name) == 10 and p.name < today),
                       reverse=True)
    except OSError:
        names = []
    for name in names[:60]:
        try:
            past.extend(json.loads((Path(records) / name / REBOUND_OUTCOMES_FILE).read_text(encoding="utf-8")).get("outcomes") or [])
        except (OSError, ValueError):
            continue
    return {"date": today, "today": today_out[-12:], "today_count": len(today_out),
            "tops_today": [r["top"] for r in today_out if r.get("top")][-8:],
            "summary_today": rebound_summary(today_out), "summary_past": rebound_summary(past),
            "past_days": len({str(r.get("detected_at"))[:10] for r in past})}


def owner_rules(rule_positions: list[dict], day: str) -> dict:
    """Today's rule trades under the OWNER's rules (virtual, 100 shares, yen after the replay's cost)."""
    filled = sorted((p for p in rule_positions if p.get("status") in ("OPEN", "CLOSED") and p.get("fill_time")),
                    key=lambda p: str(p.get("fill_time")))
    counted, apart = [], []
    no_stop = skipped = 0
    limit_hit_at = None
    for p in filled:
        code = str(p.get("ticker") or "").replace(".T", "")
        stop, fill = _num(p.get("stop")), _num(p.get("fill_price"))
        yen = None
        if p.get("status") == "CLOSED" and p.get("return_pct") is not None and fill:
            yen = round(float(p["return_pct"]) / 100 * fill * OWNER_SHARES)
        row = {"ticker": p.get("ticker"), "name": p.get("name"), "rule": p.get("rule"), "fill_time": p.get("fill_time"),
               "exit_time": p.get("exit_time"), "status": p.get("status"), "yen": yen}
        if stop is None or stop <= 0:
            no_stop += 1
            continue
        if code in OWNER_VIRTUAL_ONLY:
            apart.append(row)
            continue
        closed_before = sum(r["yen"] for r in counted if r["yen"] is not None and r["exit_time"]
                            and str(r["exit_time"]) <= str(p.get("fill_time")))
        if closed_before <= OWNER_DAILY_LIMIT_YEN:
            skipped += 1
            limit_hit_at = limit_hit_at or str(p.get("fill_time"))
            continue
        counted.append(row)

    def tally(rows):
        closed = [r["yen"] for r in rows if r["yen"] is not None]
        return {"n": len(rows), "closed": len(closed), "open": sum(1 for r in rows if r["status"] == "OPEN"),
                "wins": sum(1 for y in closed if y > 0), "losses": sum(1 for y in closed if y < 0), "yen": sum(closed)}
    return {"date": day, "shares": OWNER_SHARES, "daily_limit_yen": OWNER_DAILY_LIMIT_YEN,
            "virtual_only_codes": list(OWNER_VIRTUAL_ONLY), "counted": tally(counted), "virtual_only": tally(apart),
            "no_stop": no_stop, "skipped_after_limit": skipped, "limit_hit_at": limit_hit_at,
            "trades": counted + [dict(r, virtual_only=True) for r in apart]}


def _owner_history(records: Path, today: str) -> list[dict]:
    out = []
    try:
        days = sorted((p.name for p in Path(records).iterdir() if p.is_dir() and len(p.name) == 10 and p.name < today),
                      reverse=True)
    except OSError:
        return out
    for name in days:
        try:
            v = json.loads((Path(records) / name / OWNER_RULES_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({k: v.get(k) for k in ("date", "counted", "virtual_only", "skipped_after_limit", "limit_hit_at")})
        if len(out) >= OWNER_HISTORY_DAYS:
            break
    return out


def build(runtime: Path, *, now: datetime, ev, rules: dict, state: dict) -> dict:
    """Write RuntimeDir/positions_live_v1.json and return it."""
    runtime = Path(runtime)
    local = now.astimezone(JST)
    today = local.date().isoformat()
    hm = local.strftime("%H:%M")
    records = runtime / "records"
    day_dir = records / today
    signals = _rows(day_dir / RULE_SIGNALS_FILE)
    wanted = {s.get("ticker", "") for s in signals}
    _read_new_ticks(day_dir / TICKS_FILE, state.setdefault("ticks_state", {}), wanted)
    ticks = state["ticks_state"].get("ticks", {})
    now_t = local.strftime("%H:%M:%S")
    rule_positions = []
    traded = set()   # OWNER 2026-10-26 「1銘柄1日1回」: (rule, ticker) already filled today
    for s in signals:
        rule = rules.get(s.get("rule") or "") or {}
        if rule.get("once_per_ticker_day") and (s.get("rule"), s.get("ticker")) in traded:
            continue
        sig = {"signal": s.get("signal"), "entry": s.get("entry"), "stop": s.get("stop"), "target1": s.get("target"),
               "captured_at": s.get("captured_at"), "signal_bar": s.get("signal_bar")}
        got = ev.replay(sig, ticks.get(s.get("ticker", ""), []), max_hold_minutes=rule.get("max_hold_minutes")) or {}
        status = "INVALID"
        if got.get("state") == "NOT_FILLED":
            try:
                at = datetime.strptime(str(s.get("captured_at")), "%Y-%m-%d %H:%M:%S")
                status = "WAITING" if now_t <= (at + ev.FILL_WINDOW).strftime("%H:%M:%S") and now_t <= ev.EXIT_TIME else "NOT_FILLED"
            except ValueError:
                status = "INVALID"
        elif got.get("state") == "FILLED":
            limit = ev.EXIT_TIME
            if rule.get("max_hold_minutes"):
                limit = min(limit, (datetime.strptime(got["fill_time"], "%H:%M:%S")
                                    + timedelta(minutes=rule["max_hold_minutes"])).strftime("%H:%M:%S"))
            status = "OPEN" if got.get("exit") == "TIME_EXIT" and now_t < limit else "CLOSED"
            traded.add((s.get("rule"), s.get("ticker")))
        rule_positions.append({"ticker": s.get("ticker"), "name": s.get("name"), "rule": s.get("rule"),
                               "signal": s.get("signal"), "signal_at": s.get("captured_at"), "entry": s.get("entry"),
                               "target": s.get("target"), "stop": s.get("stop"), "status": status,
                               "fill_price": got.get("fill_price"), "fill_time": got.get("fill_time"),
                               "exit": got.get("exit") if status == "CLOSED" else None,
                               "exit_price": got.get("exit_price") if status == "CLOSED" else None,
                               "exit_time": got.get("exit_time") if status == "CLOSED" else None,
                               "return_pct": round(got["return_pct"], 3) if status == "CLOSED" and got.get("return_pct") is not None else None})
    overnight = []
    prev = _previous_day_dir(records, today)
    # OWNER 2026-10-24 「持ち越しているはず」: on Saturday and Sunday Friday's holds are still held; they are
    # scored at Monday's close (exchange holidays are not known here).
    weekend = local.weekday() >= 5
    if prev is not None and (hm < OVERNIGHT_SCORED_AT or weekend):   # carry-over, scored at the next session's close
        scored_on = today if not weekend else (local.date() + timedelta(days=7 - local.weekday())).isoformat()
        overnight = _overnight(prev, valid_until=scored_on + " " + OVERNIGHT_SCORED_AT)
    if (day_dir / OVERNIGHT_FILE).is_file():               # fixed at 15:25 today, held into the next day
        overnight = overnight + _overnight(day_dir, valid_until="next trading day " + OVERNIGHT_SCORED_AT)
    try:
        rebound = _short_rebound(day_dir, records, today, state.setdefault("rebound_state", {}))
    except Exception as exc:   # the recorder never stops the holdings view
        rebound = {"date": today, "status": "UNAVAILABLE", "reason": type(exc).__name__}
    owner = owner_rules(rule_positions, today)
    if day_dir.is_dir():
        tmp = day_dir / (OWNER_RULES_FILE + ".tmp")
        tmp.write_text(json.dumps(owner, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, day_dir / OWNER_RULES_FILE)
    owner = dict(owner, history=_owner_history(records, today))
    view = {"schema_version": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(), "date": today,
            "rule_positions": rule_positions, "overnight": overnight, "swing": None, "value": None,
            "owner_rules": owner, "short_rebound": rebound,
            "counts": {"rule_open": sum(1 for p in rule_positions if p["status"] == "OPEN"),
                       "overnight": len(overnight)},
            "status": "VIRTUAL_DISPLAY_ONLY", "real_submit_allowed": False, "trade_instruction": False}
    target = runtime / OUT_FILE
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp, target)
    return view
