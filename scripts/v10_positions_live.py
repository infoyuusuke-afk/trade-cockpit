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
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path

SCHEMA = "100b-v10-positions-live-v1"
JST = timezone(timedelta(hours=9))
OUT_FILE = "positions_live_v1.json"
RULE_SIGNALS_FILE = "brain_rule_signals.csv"
OVERNIGHT_FILE = "overnight_hold_final.csv"
TICKS_FILE = "ticks.csv"
OVERNIGHT_SCORED_AT = "14:00"   # OWNER 2026-11-05 「13時から14時とし一番良い時間を記録し続ける」 (was 15:30)
OVERNIGHT_EXIT_FILE = "overnight_hold_1400.json"   # the Collector's 14:00 prices
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


def _tick_from_today(exchange_time: str, captured_at: str) -> bool:
    """OWNER 2026-11-10 「OR15とサインにきのうの値の繰り返しを使わない」 / later 「ー678355なのか 意味がよくわからない」:
    on 11/10 MS2 stopped until about 09:30 and the file began with yesterday's 15:24:59 trades captured at 09:00; price_at() stops at
    the first later time, so the overnight line found no price all day. A trade before 08:00, or later than its capture clock plus
    two minutes, is not today's (the same rule as the Collector's Test-QuoteFromToday). No capture time: kept as before."""
    clock = captured_at[11:19]
    parts = clock.split(":")
    if len(clock) != 8 or len(parts) != 3 or not all(x.isdigit() for x in parts):
        return True
    if exchange_time < "08:00:00":
        return False
    h, m, s = (int(x) for x in parts)
    sec = min(h * 3600 + m * 60 + s + 120, 24 * 3600 - 1)
    return exchange_time <= "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


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
        if not _tick_from_today(t, str(row.get("captured_at") or "")):
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


def _overnight_closed(day_dir: Path, holds: list[dict]) -> list[dict]:
    """OWNER 2026-11-05 「持ち越しは翌日14:00の値段を仮想の手じまいとして確定に入れて」: the previous day's holds at the Collector's 14:00 price (100 shares, no cost). Virtual only."""
    try:
        prices = json.loads((day_dir / OVERNIGHT_EXIT_FILE).read_text(encoding="utf-8-sig")).get("prices") or {}
    except (OSError, ValueError):
        return []
    out = []
    for h in holds:
        entry, leave = _num(h.get("reference_price")), _num(prices.get(h.get("ticker")))
        if not entry or not leave:
            continue
        sign = 1 if h.get("side") == "LONG" else -1
        out.append(dict(h, exit_price=leave, exit_time="14:00", pct=round(sign * (leave / entry - 1) * 100, 2), yen=round(sign * (leave - entry) * OWNER_SHARES)))
    return out


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


def _first_hit(rows: list[dict], limit: float, upto: str | None = None) -> str | None:
    """The exit time at which the closed trades of rows first add up to limit or less (trades closing in the same second count together)."""
    total, last = 0, None
    done = sorted((str(r["exit_time"]), r["yen"]) for r in rows if r.get("yen") is not None and r.get("exit_time"))
    for i, (t, y) in enumerate(done):
        if upto is not None and t > upto:
            return None
        total += y
        if (i + 1 == len(done) or done[i + 1][0] != t) and total <= limit:
            return t
    return last


def owner_rules(rule_positions: list[dict], day: str) -> dict:
    """Today's rule trades under the OWNER's rules (virtual, 100 shares, yen after the replay's cost).
    OWNER 2026-11-05 「仮想売買の−3万で新規を見送る仕組みは外して、制限なしで記録する」: every trade is counted. limit_reference is what the day would have
    been if nothing was entered after the first time the closed loss reached the limit (the same count as the 対決 / diary material). Virtual only."""
    filled = sorted((p for p in rule_positions if p.get("status") in ("OPEN", "CLOSED") and p.get("fill_time")),
                    key=lambda p: str(p.get("fill_time")))
    counted, apart = [], []
    no_stop = 0
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
        counted.append(row)

    def tally(rows):
        closed = [r["yen"] for r in rows if r["yen"] is not None]
        return {"n": len(rows), "closed": len(closed), "open": sum(1 for r in rows if r["status"] == "OPEN"),
                "wins": sum(1 for y in closed if y > 0), "losses": sum(1 for y in closed if y < 0), "yen": sum(closed)}
    kept, skipped = [], 0
    for r in counted:
        if _first_hit(kept, OWNER_DAILY_LIMIT_YEN, str(r.get("fill_time"))) is not None:
            skipped += 1
        else:
            kept.append(r)
    limit_hit_at = _first_hit(kept, OWNER_DAILY_LIMIT_YEN)
    return {"date": day, "shares": OWNER_SHARES, "daily_limit_yen": OWNER_DAILY_LIMIT_YEN,
            "virtual_only_codes": list(OWNER_VIRTUAL_ONLY), "counted": tally(counted), "virtual_only": tally(apart),
            "limit_reference": dict(tally(kept), hit_at=limit_hit_at, skipped=skipped),
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
        out.append({k: v.get(k) for k in ("date", "counted", "virtual_only", "skipped_after_limit", "limit_hit_at", "limit_reference")})
        if len(out) >= OWNER_HISTORY_DAYS:
            break
    return out


# ---- capital sizes and earnings marks ----------------------------------------
# Virtual trades of the day at three sizes, and the earnings marks for the overnight cards (display only; no orders).
# 
# OWNER 2026-11-09:
# - 「メルの仮想トレードだけど、資金５００万、３００万のパターンも別につくって、信用取引つける設定で」
#   「資金別の仮想は、1回に資金と同じ額まで入る形で作って」「オーバーナイト銘柄に入る場合も資金別作成」
#   The same virtual trades as the 100-share line (rule ①②④⑤ trades and the overnight holds) are sized three ways:
#   100 shares each (as today), and capital 3,000,000 / 5,000,000 yen on margin. With capital, one trade buys at most
#   the capital's worth (floored to 100 shares); positions open at the same time (day trades and overnight holds) may
#   not exceed MARGIN_MULT x capital (制度信用, 委託保証金率30%). A trade that does not fit is not entered and counted.
# - 「1日の損益の線グラフ（9:00〜15:30、確定と含み）」「オーバーナイト銘柄の１４時まで（決済するまでの）の損益チャート」:
#   5-minute points of closed and closed + open yen for each size.
# - 「決算またぎは…Bと研究にする」: overnight candidates whose earnings fall between today's close and the next trading
#   day's 14:00 exit get a mark (今夜決算 / 明日決算, 時刻未確認 when the time is not known). Dates come from the file this PC
#   writes from JPX's schedule (earnings_dates_pc_v1.json), never from the cloud copy. Results are counted apart.
# 
# Costs: day trades use the replay's return after cost (it already holds one day of margin interest). Overnight holds pay
# margin interest (long 2.80 %/year, short lending fee 1.10 %/year) for the calendar days held. Open positions are shown
# before cost. Virtual only: real_submit_allowed is always false.
SIZES = (("100株", None), ("300万", 3_000_000), ("500万", 5_000_000))
MARGIN_MULT = 3.3
LONG_RATE, SHORT_RATE = 0.028, 0.011
DAILY_LIMIT_YEN = -30000
DAY_FILE = "capital_sim_v1.json"
EARN_FILE = "earnings_dates_pc_v1.json"
EARN_MARK_FILE = "overnight_earnings_v1.json"
HISTORY_FILE = "overnight_hold_history.csv"
DECIDE_AT = "15:25"
EXIT_AT = "14:00"


def marks(start="09:00", end="15:30", step=5):
    t = datetime.strptime(start, "%H:%M")
    out = []
    while t.strftime("%H:%M") <= end:
        out.append(t.strftime("%H:%M"))
        t += timedelta(minutes=step)
    return out


def _pnum(v):
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def price_at(ticks: list, hm: str):
    """The last tick price at or before hm:59 (ticks: [(HH:MM:SS, seq, price)] in time order)."""
    lim, last = hm + ":59", None
    for t, _, p in ticks:
        if t > lim:
            break
        last = p
    return last


def _shares(price, capital):
    if capital is None:
        return 100
    return int(capital // (price * 100)) * 100


def _days_between(a: str, b: str) -> int:
    try:
        return max(1, (date.fromisoformat(b) - date.fromisoformat(a)).days)
    except ValueError:
        return 1


def trades_of(rule_positions: list, carry: list, closed_overnight: list, today: str, ticks: dict, now_hm: str) -> list:
    """One list of virtual trades for the sizing: day trades filled today and the overnight holds that end today at 14:00.
    The 14:00 price is the Collector's (overnight_hold_1400.json) or, when that file is missing, the last recorded tick at 14:00."""
    out = []
    for p in rule_positions:
        if p.get("status") not in ("OPEN", "CLOSED") or not p.get("fill_time"):
            continue
        fill = _pnum(p.get("fill_price"))
        if fill is None:
            continue
        side = -1 if "空売り" in str(p.get("signal") or "") else 1
        tk = ticks.get(p.get("ticker", ""), [])
        out.append({"kind": "day", "rule": p.get("rule"), "ticker": p.get("ticker"), "name": p.get("name"), "side": side, "fill": fill,
                    "in": str(p.get("fill_time"))[:5], "out": str(p.get("exit_time") or "")[:5] or None,
                    "ret": None if p.get("return_pct") is None else float(p["return_pct"]),
                    "exit": _pnum(p.get("exit_price")), "last": tk[-1][2] if tk else None, "ticks": tk})
    closed = {c.get("ticker"): c for c in closed_overnight}
    for h in carry:
        decided = str(h.get("decided_at") or "")[:10]
        fill = _pnum(h.get("reference_price"))
        if len(decided) != 10 or decided >= today or fill is None:   # today's 15:25 picks start tomorrow's chart
            continue
        side = 1 if h.get("side") == "LONG" else -1
        tk = ticks.get(h.get("ticker", ""), [])
        leave = _pnum((closed.get(h.get("ticker")) or {}).get("exit_price"))
        if leave is None and now_hm >= EXIT_AT:
            leave = price_at(tk, EXIT_AT)
        out.append({"kind": "overnight", "rule": "ON_LONG" if side > 0 else "ON_SHORT", "ticker": h.get("ticker"), "name": h.get("name"), "side": side, "fill": fill,
                    "in": "09:00", "out": EXIT_AT if leave is not None else None, "ret": None, "exit": leave,
                    "last": price_at(tk, min(now_hm, EXIT_AT)) if tk else None, "ticks": tk,
                    "days": _days_between(decided, today), "decided": decided})
    return out


def _closed_yen(t, shares):
    if t["kind"] == "day":
        return None if t["ret"] is None else t["ret"] / 100 * t["fill"] * shares
    if t["exit"] is None:
        return None
    rate = LONG_RATE if t["side"] > 0 else SHORT_RATE
    return t["side"] * (t["exit"] - t["fill"]) * shares - t["fill"] * shares * rate * t["days"] / 365


def size(trades: list, capital, now_hm: str, ev: dict | None = None) -> dict:
    """Shares for each trade at one size (overnight holds first: they were opened yesterday).
    ev=None: first come, first served (the reference figures).
    ev={rule: mean % after cost of the days before today}: OWNER 2026-11-09 「枠が足りない時に期待値の高いルールを優先する形にして。
    後のサインを知っているように選ばない。…成績がマイナスのルールのサインは、入った後に1回分の枠が残る時だけ入る（最後の1回分は
    成績がプラスのルール用に取っておく）。持ち越しも同じ」: signals of the same minute are taken highest rule first (nothing later is
    looked at), and a signal whose rule is negative or unknown enters only when one more full trade (the capital) still fits after it."""
    limit = None if capital is None else capital * MARGIN_MULT
    rank = (lambda t: -(ev.get(t.get("rule")) if ev.get(t.get("rule")) is not None else -1e9)) if ev is not None else (lambda t: 0)
    order = sorted(trades, key=lambda t: (0 if t["kind"] == "overnight" else 1, t["in"], rank(t)))
    taken, skipped_room, skipped_price, peak = [], 0, 0, 0.0
    # OWNER 2026-11-09 「入れなかったサインも直近の数件を理由つきで出す」
    skipped = []
    for t in order:
        sh = _shares(t["fill"], capital)
        if sh <= 0:
            skipped_price += 1
            skipped.append({"at": t["in"], "ticker": t["ticker"], "name": t.get("name"), "side": "買い" if t["side"] > 0 else "空売り",
                            "kind": t["kind"], "reason": "1単元（100株）が資金より高い", "need": round(t["fill"] * 100), "room": None})
            continue
        using = sum(x["fill"] * x["shares"] for x in taken
                    if x["in"] <= t["in"] and (x["out"] is None or x["out"] > t["in"]))
        weak = ev is not None and not ((ev.get(t.get("rule")) or 0) > 0)
        reserve = capital if (weak and limit is not None) else 0
        if limit is not None and using + t["fill"] * sh + reserve > limit:
            skipped_room += 1
            why = "枠が足りない" if using + t["fill"] * sh > limit else "成績がマイナスの手法なので、最後の1回分の枠を残した"
            skipped.append({"at": t["in"], "ticker": t["ticker"], "name": t.get("name"), "side": "買い" if t["side"] > 0 else "空売り",
                            "kind": t["kind"], "rule": t.get("rule"), "reason": why, "need": round(t["fill"] * sh), "room": round(max(0.0, limit - using))})
            continue
        taken.append(dict(t, shares=sh))
        peak = max(peak, using + t["fill"] * sh)
    rows = {"day": {"done": 0.0, "open": 0.0, "n": 0, "closed": 0, "wins": 0},
            "overnight": {"done": 0.0, "open": 0.0, "n": 0, "closed": 0, "wins": 0}}
    held = []
    for t in taken:
        r = rows[t["kind"]]
        r["n"] += 1
        y = _closed_yen(t, t["shares"]) if t["out"] is not None and t["out"] <= now_hm else None
        if y is not None:
            r["done"] += y
            r["closed"] += 1
            r["wins"] += y > 0
        elif t["last"] is not None:
            u = t["side"] * (t["last"] - t["fill"]) * t["shares"]
            r["open"] += u
            # OWNER 2026-11-09 「フルレバで３００万　５００万も表示…その場合のポジションはわかりやすく表示して」: name, side and entry for the screen
            held.append({"ticker": t["ticker"], "name": t.get("name"), "side": "買い" if t["side"] > 0 else "空売り", "fill": t["fill"], "last": t["last"],
                         "kind": t["kind"], "shares": t["shares"], "amount": round(t["fill"] * t["shares"]),
                         "open_yen": round(u)})
    using_now = sum(h["amount"] for h in held)
    done_rows = sorted(((t["out"], _closed_yen(t, t["shares"])) for t in taken
                        if t["kind"] == "day" and t["out"] is not None and t["out"] <= now_hm), key=lambda x: x[0])
    total, hit, after = 0.0, None, 0.0
    for at, y in done_rows:
        if y is None:
            continue
        if hit is None:
            total += y
            if total <= DAILY_LIMIT_YEN:
                hit = at
        else:
            after += y
    return {"rows": {k: {kk: (round(vv) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in rows.items()},
            "skipped_room": skipped_room, "skipped_price": skipped_price, "peak_amount": round(peak),
            "using_amount": using_now, "limit_amount": None if limit is None else round(limit),
            "limit_hit_at": hit, "limit_stop_yen": round(total) if hit else None, "held": held, "_taken": taken,
            "skipped_recent": sorted(skipped, key=lambda x: x["at"])[-5:][::-1]}


def curve(taken: list, kinds: tuple, points: list, now_hm: str) -> list:
    """[(HH:MM, closed yen, closed + open yen)] up to now."""
    out = []
    for hm in points:
        if hm > now_hm:
            break
        done = opn = 0.0
        for t in taken:
            if t["kind"] not in kinds or t["in"] > hm:
                continue
            if t["out"] is not None and t["out"] <= hm:
                y = _closed_yen(t, t["shares"])
                done += y or 0.0
            else:
                p = price_at(t["ticks"], hm)
                if p is not None:
                    opn += t["side"] * (p - t["fill"]) * t["shares"]
        out.append([hm, round(done), round(done + opn)])
    return out


def _past(records: Path, today: str) -> list:
    out = []
    try:
        days = sorted(p.name for p in Path(records).iterdir() if p.is_dir() and len(p.name) == 10 and p.name < today)
    except OSError:
        return out
    for name in days:
        try:
            out.append(json.loads((Path(records) / name / DAY_FILE).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


RULE_EV_FILE = "capital_rule_ev_v1.json"
ON_RATE_DAY = {"ON_LONG": LONG_RATE / 365 * 100, "ON_SHORT": SHORT_RATE / 365 * 100}


DAY_RULE_KEYS = ("R1", "R2", "R4", "R5", "BRAIN")


def rule_ev(runtime: Path, day_dir: Path, today: str) -> dict:
    """{rule: mean % after cost} from the records before today, fixed in records/<day>/capital_rule_ev_v1.json at the first
    pass of the day (so a figure built after today's close is never used for today). Day rules: rule_shadow_v1.json forward
    ev_pct (cost = the replay's). Overnight: overnight_hold_history.csv 検証済み rows evaluated before today, return_close_pct
    minus one day of interest, apart for long and short. A rule with no record is None (treated as not positive)."""
    f = day_dir / RULE_EV_FILE
    try:
        got = json.loads(f.read_text(encoding="utf-8"))
        if got.get("date") == today:
            return got
    except (OSError, ValueError):
        pass
    out = {"date": today, "made_at": datetime.now(JST).strftime("%H:%M"), "ev": {}, "n": {}, "win": {}, "pf": {}}
    try:
        rs = json.loads((Path(runtime) / "rule_shadow_v1.json").read_text(encoding="utf-8-sig"))
        if rs.get("real_submit_allowed") is False and today not in (rs.get("days") or []):
            for k, v in (rs.get("forward") or {}).items():
                if k in DAY_RULE_KEYS and v.get("ev_pct") is not None:
                    out["ev"][k], out["n"][k] = float(v["ev_pct"]), int(v.get("n") or 0)
                    out["win"][k] = v.get("win_rate_pct")
                    out["pf"][k] = v.get("pf")
    except (OSError, ValueError, TypeError):
        pass
    # OWNER 2026-11-10 「すべてなおして」(資金別の「ルールの成績」が、初回の計算が15:35より後の日は空になる件): when the shadow file
    # already holds today (first pass after the close), the day rules come from the latest earlier day's fixed file — built
    # before that day, so nothing of today is used. The overnight part below is unchanged.
    if not any(k in out["ev"] for k in DAY_RULE_KEYS):
        try:
            prev = sorted(d for d in Path(day_dir).parent.iterdir()
                          if d.is_dir() and d.name < today and (d / RULE_EV_FILE).is_file())
        except OSError:
            prev = []
        for d in reversed(prev[-10:]):
            try:
                old = json.loads((d / RULE_EV_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            keys = [k for k in DAY_RULE_KEYS if k in (old.get("ev") or {})]
            if not keys:
                continue
            for k in keys:
                for part in ("ev", "n", "win", "pf"):
                    if k in (old.get(part) or {}):
                        out[part][k] = old[part][k]
            out["day_rules_from"] = d.name
            break
    acc = {"ON_LONG": [], "ON_SHORT": []}
    for r in _rows(Path(runtime) / HISTORY_FILE):
        if r.get("status") != "検証済み" or not str(r.get("evaluation_date") or "") or str(r.get("evaluation_date")) >= today:
            continue
        try:
            acc["ON_LONG" if r.get("side") == "LONG" else "ON_SHORT"].append(float(r.get("return_close_pct")))
        except (TypeError, ValueError):
            continue
    for k, xs in acc.items():
        if xs:
            net = [x - ON_RATE_DAY[k] for x in xs]
            out["ev"][k], out["n"][k] = round(sum(net) / len(net), 4), len(net)
            out["win"][k] = round(sum(1 for x in net if x > 0) / len(net) * 100, 1)
            gain, loss = sum(x for x in net if x > 0), -sum(x for x in net if x < 0)
            out["pf"][k] = round(gain / loss, 2) if loss > 0 else None
    if day_dir.is_dir():
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    return out


def method_days(records: Path, runtime: Path, today: str) -> dict:
    """{method: [[day, yen]]} for the days before today, 100 shares, from the records as they are:
    records/<day>/owner_rules_virtual.json (closed rule trades, ①②④⑤) and overnight_hold_history.csv 検証済み rows
    (return_close_pct x reference price x 100, by evaluation day). The Brain has no per-day record, so it has no line."""
    by = {}
    try:
        days = sorted(p.name for p in Path(records).iterdir() if p.is_dir() and len(p.name) == 10 and p.name < today)
    except OSError:
        days = []
    for d in days:
        try:
            if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5:
                continue
            v = json.loads((Path(records) / d / OWNER_RULES_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for t in v.get("trades") or []:
            if t.get("status") == "CLOSED" and t.get("yen") is not None and t.get("rule"):
                by.setdefault(t["rule"], {}).setdefault(d, 0)
                by[t["rule"]][d] += t["yen"]
    for r in _rows(Path(runtime) / HISTORY_FILE):
        d = str(r.get("evaluation_date") or "")
        if r.get("status") != "検証済み" or not d or d >= today:
            continue
        try:
            y = float(r.get("return_close_pct")) / 100 * float(r.get("reference_price_1525")) * 100
        except (TypeError, ValueError):
            continue
        k = "ON_LONG" if r.get("side") == "LONG" else "ON_SHORT"
        by.setdefault(k, {}).setdefault(d, 0)
        by[k][d] += y
    return {k: [[d, round(y)] for d, y in sorted(v.items())] for k, v in by.items()}


FOCUS_ANALYST_FILE = "focus_analyst_v1.json"


def focus_analyst(runtime: Path, today: str, now_hm: str) -> dict:
    """OWNER 2026-11-09 「FOCUSの空いた枠に、8:50と12:20にアナリストの今日の8銘柄から自信の高い順でMS2の100銘柄に入っているものを
    自動で入れて」: the list a PC script writes (RuntimeDir/focus_analyst_v1.json, slots 0850 and 1220 of today), the later slot
    once it exists and its time has come. Only fields for the screen are passed; analyst text is data only. No orders."""
    try:
        doc = json.loads((Path(runtime) / FOCUS_ANALYST_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"state": "NO_FILE", "items": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("slots") or {}, dict):
        return {"state": "FORMAT_UNKNOWN", "items": []}
    if doc.get("schema_version") != "100b-v10-focus-analyst-v1" or doc.get("real_submit_allowed") is not False:
        return {"state": "FORMAT_UNKNOWN", "items": []}
    if doc.get("date") != today:
        return {"state": "OLD", "items": []}
    slots = doc.get("slots") or {}
    key = "1220" if "1220" in slots and now_hm >= "12:20" else "0850" if "0850" in slots else None
    if key is None:
        return {"state": "NOT_YET", "items": []}
    slot = slots[key] if isinstance(slots[key], dict) else {}
    items = []
    raw = slot.get("items") if isinstance(slot.get("items"), list) else []
    for x in raw[:8]:
        if not isinstance(x, dict):
            continue
        t = str(x.get("ticker") or "")
        if len(t) != 6 or not t.endswith(".T"):
            continue
        items.append({k: str(x.get(k) or "")[:80] for k in ("ticker", "code", "name", "side", "conf", "who", "entry")})
    return {"state": "OK", "slot": key, "made_at": str(slot.get("made_at") or "")[:5], "items": items}


AIR_FILE = "air300_v1.json"
AIR_START = 3_000_000
_AIR_MEMO: dict = {}


def _day_closes(path: Path) -> dict:
    """{ticker: the day's last fresh trade price up to 15:30} from one ticks.csv (stale ticks of an earlier day dropped)."""
    out, at = {}, {}
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = str(row.get("exchange_time") or "")[:8]
                p = _num(row.get("price"))
                if not p or p <= 0 or t > "15:30:59" or not _tick_from_today(t, str(row.get("captured_at") or "")):
                    continue
                k = str(row.get("ticker") or "")
                if t >= at.get(k, ""):
                    at[k], out[k] = t, p
    except OSError:
        return {}
    return out


def air300(records: Path, runtime: Path, day_dir: Path, today: str) -> dict:
    """OWNER 2026-11-11 「AIコクピットはかえない　AIトレード日記タブに資金３００万からスタートした場合のエアトレードを追加」:
    the days before today replayed with 300万 that grows with the results (virtual, display only, no order, nothing on the
    trading side changes). The same rules as the 300万 size: one trade up to the balance (100-share units), held total up
    to the balance x MARGIN_MULT, the overnight first, same-minute signals by the rule's mean % of the earlier days, a rule not
    above 0 only when one more full trade still fits. Day trades: owner_rules_virtual.json yen (100 shares, after cost)
    scaled by shares; the entry price is the matching signal's entry (the record has no fill price). Overnight:
    overnight_hold_history.csv 検証済み return_close_pct (to the next close) minus interest per day, held 09:00-14:00 for the
    room. The Brain has no per-day record, so it is not in. Fixed once a day in records/<today>/air300_v1.json."""
    f = day_dir / AIR_FILE
    if _AIR_MEMO.get("date") == today:   # also when the day folder is not made yet (early morning): once per day
        return dict(_AIR_MEMO)
    try:
        got = json.loads(f.read_text(encoding="utf-8"))
        if got.get("date") == today:
            return got
    except (OSError, ValueError):
        pass
    try:
        names = sorted(p.name for p in Path(records).iterdir() if p.is_dir() and len(p.name) == 10 and p.name < today)
    except OSError:
        names = []
    trades = {}
    for d in names:
        try:
            if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5:
                continue
            v = json.loads((Path(records) / d / OWNER_RULES_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sig = {}
        for r in _rows(Path(records) / d / RULE_SIGNALS_FILE):
            e = _num(r.get("entry"))
            if e and e > 0:
                sig.setdefault((r.get("ticker"), r.get("rule")), []).append((str(r.get("captured_at") or "")[11:19], e,
                                                                            -1 if "空売り" in str(r.get("signal") or "") else 1))
        for t in (v.get("trades") if isinstance(v, dict) else None) or []:
            yv = _num(t.get("yen")) if isinstance(t, dict) else None
            if yv is None or not math.isfinite(yv) or t.get("status") != "CLOSED" or not t.get("rule"):   # audit bcfb9de: no inf
                continue
            ft = str(t.get("fill_time") or "")[:8]
            cand = [(e, sd) for at, e, sd in sig.get((t.get("ticker"), t.get("rule")), []) if at <= ft]
            if not cand:
                continue
            y100 = float(yv)
            fill, sd = cand[-1]
            trades.setdefault(d, []).append({"kind": "day", "rule": t["rule"], "in": ft[:5], "out": str(t.get("exit_time") or "")[:5],
                                             "fill": fill, "y100": y100, "pct": y100 / (fill * 100) * 100,
                                             "name": str(t.get("name") or t.get("ticker") or ""), "side": sd})
    # OWNER 2026-11-11 「300万の検証が2回で数字が違う…正しい方に1本化」: a Friday pick is stamped 検証済み on the Saturday/Sunday with the
    # Friday close as the "next close" (no market), so its return is not the trade's. It is moved to the next weekday and priced
    # at that day's last recorded trade (ticks.csv, stale ticks dropped); without a price there it is left out and counted.
    weekend, bad = {}, 0
    for r in _rows(Path(runtime) / HISTORY_FILE):
        d = str(r.get("evaluation_date") or "")
        if r.get("status") != "検証済み" or len(d) != 10 or d >= today:
            continue
        try:
            wd = datetime.strptime(d, "%Y-%m-%d").weekday()
            ref = float(r.get("reference_price_1525"))
            if wd >= 5:
                nd = date.fromisoformat(d) + timedelta(days=7 - wd)
                while nd.weekday() >= 5 or nd.isoformat() in EXCHANGE_HOLIDAYS:
                    nd += timedelta(days=1)
                d = nd.isoformat()
                if d >= today:
                    continue
                if d not in weekend:
                    weekend[d] = _day_closes(Path(records) / d / TICKS_FILE)
                close = weekend[d].get(str(r.get("ticker") or ""))
                if close is None:
                    bad += 1
                    continue
                ret = (close / ref - 1) * 100 * (1 if r.get("side") == "LONG" else -1)
            else:
                ret = float(r.get("return_close_pct"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(ref) and math.isfinite(ret)):
            continue
        if ref <= 0:
            continue
        side = 1 if r.get("side") == "LONG" else -1
        pct = ret - (LONG_RATE if side > 0 else SHORT_RATE) * _days_between(str(r.get("decision_date") or ""), d) / 365 * 100
        trades.setdefault(d, []).append({"kind": "overnight", "rule": "ON_LONG" if side > 0 else "ON_SHORT", "in": "09:00", "out": EXIT_AT,
                                         "fill": ref, "y100": pct / 100 * ref * 100, "pct": pct,
                                         "name": str(r.get("name") or r.get("ticker") or ""), "side": side,
                                         "decided": str(r.get("decision_date") or "")})
    bal, peak, dd, past, rows, by, hist = float(AIR_START), float(AIR_START), 0.0, {}, [], {}, []
    for d in sorted(trades):
        cap, ev = bal, {k: sum(v) / len(v) for k, v in past.items() if v}
        limit = cap * MARGIN_MULT
        rank = lambda t: -(ev.get(t["rule"]) if ev.get(t["rule"]) is not None else -1e9)
        taken, pnl, skipped = [], 0.0, 0
        for t in sorted(trades[d], key=lambda t: (0 if t["kind"] == "overnight" else 1, t["in"], rank(t))):
            sh = _shares(t["fill"], cap)
            using = sum(x["fill"] * x["sh"] for x in taken if x["in"] <= t["in"] and x["out"] > t["in"])
            reserve = cap if not ((ev.get(t["rule"]) or 0) > 0) else 0
            if sh <= 0 or using + t["fill"] * sh + reserve > limit:
                skipped += 1
                continue
            taken.append(dict(t, sh=sh))
            y = t["y100"] * sh / 100
            pnl += y
            # OWNER 2026-11-11 「AIトレード日記タブにメルが資金３００万からはじめたトレード履歴を追加」: one row per trade taken
            hist.append([d, t.get("decided", "") if t["kind"] == "overnight" else "", t["in"], t["out"], t.get("name", ""),
                         t.get("side", 1), t["rule"], sh, round(t["fill"] * sh), round(y)])
            b = by.setdefault(t["rule"], [0.0, 0, 0])
            b[0] += y
            b[1] += 1
            b[2] += y > 0
        for t in trades[d]:
            past.setdefault(t["rule"], []).append(t["pct"])
        bal += pnl
        peak = max(peak, bal)
        dd = min(dd, bal - peak)
        rows.append([d, round(pnl), round(bal), len(taken), skipped])
    out = {"date": today, "start": AIR_START, "from": rows[0][0] if rows else None, "days": rows,
           "by_rule": {k: [round(v[0]), v[1], v[2]] for k, v in by.items()}, "max_dd": round(dd), "peak": round(peak),
           "trades": [t for t in hist if t[0] >= (rows[-30][0] if len(rows) >= 30 else "")],   # audit 1c38e0b: the last 30 days
           "weekend_moved_unpriced": bad,
           "real_submit_allowed": False}
    _AIR_MEMO.clear()
    _AIR_MEMO.update(out)
    if day_dir.is_dir():
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    return out


def _air300_safe(records: Path, runtime: Path, day_dir: Path, today: str) -> dict:
    """audit 0f33e32: a broken record file must never take the capital view down; the screen then says 「まだ記録がありません」."""
    try:
        return air300(records, runtime, day_dir, today)
    except Exception as exc:  # noqa: BLE001 - display only
        return {"state": "UNAVAILABLE", "reason": type(exc).__name__, "days": [], "real_submit_allowed": False}


def capital_view(records: Path, day_dir: Path, today: str, now_hm: str, trades: list, ev_doc: dict | None = None) -> dict:
    points = marks()
    past = _past(records, today)
    sizes = []
    keep = {"date": today, "sizes": {}}
    ev = (ev_doc or {}).get("ev") or {}
    for label, capital in SIZES:
        s = size(trades, capital, now_hm, ev if capital is not None else None)
        # OWNER 2026-11-09 「先着順の数字も参考に残す」
        if capital is not None:
            f = size(trades, capital, now_hm)
            f.pop("_taken")
            s["fifo"] = {"done": f["rows"]["day"]["done"] + f["rows"]["overnight"]["done"],
                         "open": f["rows"]["day"]["open"] + f["rows"]["overnight"]["open"],
                         "skipped": f["skipped_room"] + f["skipped_price"]}
        taken = s.pop("_taken")
        day_done = s["rows"]["day"]["done"] + s["rows"]["overnight"]["done"]
        day_open = s["rows"]["day"]["open"] + s["rows"]["overnight"]["open"]
        closed = s["rows"]["day"]["closed"] + s["rows"]["overnight"]["closed"]
        wins = s["rows"]["day"]["wins"] + s["rows"]["overnight"]["wins"]
        prev = [(p.get("sizes") or {}).get(label) or {} for p in past]
        total_done = sum(int(x.get("done") or 0) for x in prev) + day_done
        total_closed = sum(int(x.get("closed") or 0) for x in prev) + closed
        total_wins = sum(int(x.get("wins") or 0) for x in prev) + wins
        keep["sizes"][label] = {"done": day_done, "closed": closed, "wins": wins}
        sizes.append(dict(s, label=label, capital=capital, done=day_done, open=day_open, closed=closed, wins=wins,
                          total_done=total_done, total_closed=total_closed, total_wins=total_wins,
                          total_pct=None if capital is None else round(total_done / capital * 100, 2),
                          day_curve=curve(taken, ("day",), points, now_hm),
                          overnight_curve=curve(taken, ("overnight",), [p for p in points if p <= EXIT_AT], now_hm)))
    # OWNER 2026-11-09 「手法の勝率など結果については、グラフで比較、一目でわかる形にしてほしい」: today's per-method figures (100 shares)
    today_by = {}
    base = size(trades, None, now_hm)["_taken"]
    for t in base:
        y = _closed_yen(t, t["shares"]) if t["out"] is not None and t["out"] <= now_hm else None
        r = today_by.setdefault(t.get("rule") or "?", {"n": 0, "closed": 0, "wins": 0, "yen": 0.0, "pcts": []})
        r["n"] += 1
        if y is not None:
            r["closed"] += 1
            r["wins"] += y > 0
            r["yen"] += y
            r["pcts"].append(y / (t["fill"] * t["shares"]) * 100)
    def _fig(v):
        xs = v.pop("pcts")
        gain, loss = sum(x for x in xs if x > 0), -sum(x for x in xs if x < 0)
        return dict(v, yen=round(v["yen"]), win=round(v["wins"] / len(xs) * 100, 1) if xs else None,
                    mean=round(sum(xs) / len(xs), 4) if xs else None, pf=round(gain / loss, 2) if loss > 0 else None)
    today_by = {k: _fig(v) for k, v in today_by.items()}
    if day_dir.is_dir():
        tmp = day_dir / (DAY_FILE + ".tmp")
        tmp.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
        tmp.replace(day_dir / DAY_FILE)
    return {"from": (past[0].get("date") if past else today), "margin_mult": MARGIN_MULT, "sizes": sizes,
            "rule_ev": ev_doc or {}, "methods_today": today_by, "method_days": method_days(records, day_dir.parent.parent, today),
            "air300": _air300_safe(records, day_dir.parent.parent, day_dir, today),
            "note": "仮想・注文なし。1回は資金と同じ額まで（100株単位）、同時に持つ合計は資金の3.3倍まで。枠が足りない時は、同じ時刻のサインの中で成績（前の日までの平均・費用込み）の高い手法を先に。成績がマイナスの手法は、入った後に1回分の枠が残る時だけ入る。デイは費用込み、持ち越しは日数分の金利込み、含みは費用前",
            "real_submit_allowed": False}


# TSE holidays that fall on weekdays (only the ones known here; extend when a year is added)
# OWNER 2026-11-10 「すべてなおして」: the rest of 2027 from the Cabinet Office list (syukujitsu.csv, weekday ones) + the
# exchange's year-end and new-year closures (12/31, 1/1–1/3).
EXCHANGE_HOLIDAYS = {"2026-11-23", "2026-12-31", "2027-01-01", "2027-01-11", "2027-02-11", "2027-02-23",
                     "2027-03-22", "2027-04-29", "2027-05-03", "2027-05-04", "2027-05-05", "2027-07-19", "2027-08-11",
                     "2027-09-20", "2027-09-23", "2027-10-11", "2027-11-03", "2027-11-23", "2027-12-31", "2028-01-03"}


def _next_weekday(d: date) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in EXCHANGE_HOLIDAYS:
        d += timedelta(days=1)
    return d


def earnings_soon(runtime: Path, today: str, now_hm: str = "15:30") -> dict:
    """{code: {"label": 今夜決算|明日決算, "date", "time"}} for earnings between today's close and the next trading day's 14:00.
    An announcement already made in today's session (a known time before 15:25) is not marked; a next-day time at or
    after 14:00 is after the exit and not marked. Unknown times are marked with time ""."""
    try:
        doc = json.loads((Path(runtime) / EARN_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"state": "NO_FILE", "items": {}}
    if doc.get("schema_version") != "100b-v10-earnings-dates-pc-v1":
        return {"state": "FORMAT_UNKNOWN", "items": {}}
    d0 = date.fromisoformat(today)
    d1 = _next_weekday(d0)
    morning = now_hm < "15:00"   # until 15:00 the cards are yesterday's picks, held until 14:00 today
    times = doc.get("times") or {}
    items = {}
    try:   # only the cockpit's 100 stocks (the overnight picks come from them); all when the list is not readable
        w = json.loads((Path(runtime) / "watchlist_100.json").read_text(encoding="utf-8-sig"))
        universe = {str(v.get("ticker") or "").replace(".T", "") for v in (w.get("stocks") or {}).values()} - {""}
    except (OSError, ValueError, AttributeError):
        universe = set()
    for code, days in (doc.get("dates") or {}).items():
        if universe and code not in universe:
            continue
        for ds in days or []:
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            hm = str((times.get(code) or {}).get(ds) or "")
            if morning:
                if d != d0 or (hm and hm >= EXIT_AT):
                    continue
                items[code] = {"label": "今日決算", "date": ds, "time": hm}
                continue
            if not d0 <= d <= d1:
                continue
            if d == d0 and hm and hm < DECIDE_AT:
                continue
            if d == d1 and hm and hm >= EXIT_AT:
                continue
            label = "今夜決算" if d == d0 else "明日決算" if d == d1 else "休みの日に決算"
            items[code] = {"label": label, "date": ds, "time": hm}
    gen = str(doc.get("generated_at") or "")[:10]
    return {"state": "OK" if gen == today else "OLD", "generated_on": gen, "items": items}


def keep_marks(day_dir: Path, holds: list, soon: dict) -> None:
    """Write today's marks for the fixed 15:25 picks once, so the results can be counted apart later."""
    target = day_dir / EARN_MARK_FILE
    if target.is_file() or not holds or soon.get("state") not in ("OK", "OLD"):
        return
    rows = {str(h.get("ticker") or "").replace(".T", ""): (soon["items"].get(str(h.get("ticker") or "").replace(".T", "")) or None)
            for h in holds}
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps({"date": day_dir.name, "marks": rows}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)


def earnings_split(runtime: Path) -> dict:
    """Overnight results (the Collector's history, 検証済み rows) counted apart: earnings inside the hold or not.
    Only days with a kept mark file are counted (from 2026-11-09)."""
    records = Path(runtime) / "records"
    marks_by_day = {}
    try:
        for p in records.iterdir():
            f = p / EARN_MARK_FILE
            if f.is_file():
                try:
                    marks_by_day[p.name] = json.loads(f.read_text(encoding="utf-8")).get("marks") or {}
                except (OSError, ValueError):
                    continue
    except OSError:
        pass
    groups = {"earnings": [], "other": []}
    try:
        with open(Path(runtime) / HISTORY_FILE, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                m = marks_by_day.get(str(r.get("decision_date") or ""))
                if m is None or r.get("status") != "検証済み":
                    continue
                code = str(r.get("ticker") or "").replace(".T", "")
                if code not in m:
                    continue
                try:
                    v = float(r.get("return_close_pct"))
                except (TypeError, ValueError):
                    continue
                groups["earnings" if m.get(code) else "other"].append(v)
    except OSError:
        pass

    def tally(xs):
        return {"n": len(xs), "win_pct": round(sum(1 for x in xs if x > 0) / len(xs) * 100, 1) if xs else None,
                "avg_pct": round(sum(xs) / len(xs), 2) if xs else None}
    return {"from": min(marks_by_day) if marks_by_day else None, "earnings": tally(groups["earnings"]),
            "other": tally(groups["other"])}


def build(runtime: Path, *, now: datetime, ev, rules: dict, state: dict) -> dict:
    """Write RuntimeDir/positions_live_v1.json and return it."""
    runtime = Path(runtime)
    local = now.astimezone(JST)
    today = local.date().isoformat()
    hm = local.strftime("%H:%M")
    records = runtime / "records"
    day_dir = records / today
    signals = _rows(day_dir / RULE_SIGNALS_FILE)
    prev0 = _previous_day_dir(records, today)
    carry = _overnight(prev0, valid_until="") if prev0 is not None else []   # their prices for the capital view
    wanted = {s.get("ticker", "") for s in signals} | {h.get("ticker", "") for h in carry}
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
    overnight, overnight_closed = [], []
    prev = _previous_day_dir(records, today)
    # OWNER 2026-10-24 「持ち越しているはず」: on Saturday and Sunday Friday's holds are still held; they are
    # scored at Monday's close (exchange holidays are not known here).
    weekend = local.weekday() >= 5
    if prev is not None and not weekend and hm >= OVERNIGHT_SCORED_AT:
        overnight_closed = _overnight_closed(day_dir, _overnight(prev, valid_until=today + " " + OVERNIGHT_SCORED_AT))
    if prev is not None and (hm < OVERNIGHT_SCORED_AT or weekend):   # carry-over, out at 14:00 the next session
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
    # OWNER 2026-11-09 資金別（100株・300万・500万）と1日の損益の線グラフ、決算またぎの印. A failure here never stops the holdings view.
    try:
        capital = capital_view(records, day_dir, today, hm,
                               trades_of(rule_positions, carry if not weekend else [], overnight_closed, today, ticks, hm), rule_ev(runtime, day_dir, today))
    except Exception as exc:
        capital = {"status": "UNAVAILABLE", "reason": type(exc).__name__}
    try:
        soon = earnings_soon(runtime, today, hm)
        if hm >= DECIDE_AT:
            keep_marks(day_dir, _overnight(day_dir, valid_until=""), soon)
        soon = dict(soon, split=earnings_split(runtime))
    except Exception as exc:
        soon = {"state": "UNAVAILABLE", "reason": type(exc).__name__, "items": {}}
    try:
        focus = focus_analyst(runtime, today, hm)
    except Exception as exc:
        focus = {"state": "UNAVAILABLE", "reason": type(exc).__name__, "items": []}
    view = {"schema_version": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(), "date": today,
            "rule_positions": rule_positions, "overnight": overnight, "swing": None, "value": None,
            "owner_rules": owner, "short_rebound": rebound, "overnight_closed": overnight_closed,
            "capital": capital, "earnings_soon": soon, "focus_analyst": focus,
            "counts": {"rule_open": sum(1 for p in rule_positions if p["status"] == "OPEN"),
                       "overnight": len(overnight)},
            "status": "VIRTUAL_DISPLAY_ONLY", "real_submit_allowed": False, "trade_instruction": False}
    target = runtime / OUT_FILE
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp, target)
    return view
