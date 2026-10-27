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
    owner = owner_rules(rule_positions, today)
    if day_dir.is_dir():
        tmp = day_dir / (OWNER_RULES_FILE + ".tmp")
        tmp.write_text(json.dumps(owner, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(tmp, day_dir / OWNER_RULES_FILE)
    owner = dict(owner, history=_owner_history(records, today))
    view = {"schema_version": SCHEMA, "generated_at": now.astimezone(timezone.utc).isoformat(), "date": today,
            "rule_positions": rule_positions, "overnight": overnight, "swing": None, "value": None,
            "owner_rules": owner,
            "counts": {"rule_open": sum(1 for p in rule_positions if p["status"] == "OPEN"),
                       "overnight": len(overnight)},
            "status": "VIRTUAL_DISPLAY_ONLY", "real_submit_allowed": False, "trade_instruction": False}
    target = runtime / OUT_FILE
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(temp, target)
    return view
