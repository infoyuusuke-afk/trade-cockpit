"""SCALP8 board view for the cockpit's 板 panel and 板 tab (display only, never a trade instruction).

OWNER 2026-11-02 「SCALP8の8銘柄の板パネルを、トレード中タブに作って。板の厚さ・壁と消えた壁・大きな約定・大口吸収の印を、
未検証の表示で…板タブを別にようい」「買い板は緑、売り板は赤…買い板の割合（%）の1本線…UNDERとOVERと割合を足して」

Reads only what the Collector already records under RuntimeDir/records/<day>/ (read incrementally, a bounded number of
bytes per call): scalp8_board.csv (10 levels), scalp8_ticks.csv (prints with size), under_over.csv (OVER / UNDER of the
100 stocks) and absorb_voice.csv (the absorb voice log). Writes RuntimeDir/scalp8_board_live_v1.json for the gateway.
Rules (the same as the research script board_analyst.py):
  - continuous trading only: after each stock's first print of the morning / afternoon (the auction) and before 11:30 /
    15:25; the first read ("initial") of the prints is skipped, a "gap" read skips prints already seen, and a print
    stamped more than 4 s after its read is the previous day's
  - side of a print: the read's quote, but a SELL above the previous print / a BUY below it is unknown (tick rule)
  - 壁 (wall): a top-5 level of 5x the stock's usual level size or more; 消えた壁: a wall that loses 80 % within 60 s
    while the prints at that price stay under 20 % of what went (a suspicion only, orders can be cancelled)
  - 大きな約定: a print of 10x the median print size and at least the 99th percentile of the day so far
Everything is unverified (on 10/26-11/2 none of these shapes passed the research pass line). real_submit_allowed is false.
"""
import bisect
import csv
import io
import json
import os
import statistics
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SCHEMA = "100b-v10-scalp8-board-v1"
OUT_FILE = "scalp8_board_live_v1.json"
MAX_READ_BYTES = 4 * 1024 * 1024
WALL_X = 5.0
BIG_X = 10.0


def _sec(t):
    try:
        h, m, s = str(t)[:8].split(":")
        return int(h) * 3600 + int(m) * 60 + int(float(s))
    except ValueError:
        return None


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def _read_new(path, st, key):
    """New complete lines of a CSV appended since the last call (st[key] keeps offset + header)."""
    s = st.setdefault(key, {"offset": 0, "header": None})
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size < s["offset"]:
        s.update(offset=0, header=None)
    if size == s["offset"]:
        return []
    with open(path, "rb") as f:
        f.seek(s["offset"])
        raw = f.read(min(size - s["offset"], MAX_READ_BYTES))
    end = raw.rfind(b"\n")
    if end < 0:
        return []
    chunk = raw[:end + 1]
    s["offset"] += len(chunk)
    lines = chunk.decode("utf-8-sig", errors="replace").splitlines()
    if s["header"] is None and lines:
        s["header"] = next(csv.reader([lines[0]]))
        lines = lines[1:]
    hdr = s["header"]
    return [dict(zip(hdr, r)) for r in csv.reader(io.StringIO("\n".join(lines))) if len(r) == len(hdr)]


def _stock(st, code):
    return st["stocks"].setdefault(code, {
        "name": code, "levels": None, "board_at": None, "sizes": [], "prev": {}, "walls": {}, "vanished": [],
        "ratio_hist": {}, "price_hist": {}, "prints": [], "recent": [], "vols": [], "big": [], "big_th": None, "big_th_at": -1,
        "keys": set(), "key_order": [], "last_price": 0.0, "am_open": None, "pm_open": None,
        "over": None, "under": None, "uo_at": None})


def _continuous(sk, s):
    return (sk["am_open"] is not None and sk["am_open"] < s <= 41399) or (sk["pm_open"] is not None and sk["pm_open"] < s <= 55499)


def _feed_ticks(st, rows):
    for r in rows:
        if r.get("batch") == "initial":
            continue
        cap, t = _sec(r.get("captured_at", "")[11:19]), _sec(r.get("exchange_time", ""))
        p, v = _num(r.get("price")), _num(r.get("volume"))
        if cap is None or t is None or not p or not v or t > cap + 4 or not (32400 <= t <= 55800):
            continue
        sk = _stock(st, r.get("ticker", ""))
        key = "%s|%s|%s" % (r.get("exchange_time"), r.get("price"), r.get("volume"))
        if r.get("batch") == "gap" and key in sk["keys"]:
            continue
        sk["keys"].add(key)
        sk["key_order"].append(key)
        if len(sk["key_order"]) > 600:
            sk["keys"].discard(sk["key_order"].pop(0))
        side = r.get("side_estimate") or ""
        if sk["last_price"] and ((side == "SELL" and p > sk["last_price"]) or (side == "BUY" and p < sk["last_price"])):
            side = "MID"
        sk["last_price"] = p
        if t >= 32400 and sk["am_open"] is None:
            sk["am_open"] = t
        if t >= 45000 and sk["pm_open"] is None:
            sk["pm_open"] = t
        if not _continuous(sk, t):
            continue
        sk["recent"].append((t, p, v))
        sk["price_hist"]["%02d:%02d" % (t // 3600, t % 3600 // 60)] = p   # the last continuous print of each minute
        while sk["recent"] and sk["recent"][0][0] < t - 120:
            sk["recent"].pop(0)
        bisect.insort(sk["vols"], v)
        th = sk["big_th"]
        if th and v >= th:
            sk["big"].append({"at": "%02d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60), "price": p, "qty": int(v),
                              "side": {"BUY": "買い", "SELL": "売り"}.get(side, "不明")})
            sk["big"] = sk["big"][-10:]
        # refresh the threshold every 200 prints (10x the median, at least the 99th percentile)
        if len(sk["vols"]) >= 200 and len(sk["vols"]) % 200 == 0:
            vs = sk["vols"]
            sk["big_th"] = max(BIG_X * vs[len(vs) // 2], vs[int(len(vs) * 0.99)])


def _feed_board(st, rows):
    for r in rows:
        s = _sec(r.get("captured_at", "")[11:19])
        if s is None:
            continue
        sk = _stock(st, r.get("ticker", ""))
        lv = [(_num(r.get("ask%d" % i)), _num(r.get("ask_qty%d" % i)), _num(r.get("bid%d" % i)), _num(r.get("bid_qty%d" % i))) for i in range(1, 11)]
        sk["levels"], sk["board_at"] = lv, r.get("captured_at", "")[:19]
        if not _continuous(sk, s):
            sk["prev"] = {}
            continue
        sizes = [q for a, aq, b, bq in lv[:5] for q in (aq, bq) if q]
        sk["sizes"] = (sk["sizes"] + sizes)[-3000:]
        usual = statistics.median(sk["sizes"]) if len(sk["sizes"]) >= 100 else None
        b5 = sum(x[3] or 0 for x in lv[:5])
        a5 = sum(x[1] or 0 for x in lv[:5])
        if a5 + b5 > 0:
            sk["ratio_hist"]["%02d:%02d" % (s // 3600, s % 3600 // 60)] = round(b5 / (a5 + b5), 3)
        cur = {}
        for a, aq, b, bq in lv[:5]:
            if a and aq is not None:
                cur[("売り", a)] = aq
            if b and bq is not None:
                cur[("買い", b)] = bq
        if usual:
            for key, q in cur.items():
                add = q - sk["prev"].get(key, 0)
                if add >= WALL_X * usual and key not in sk["walls"]:
                    sk["walls"][key] = (s, add, q)
            for key, (s0, add, q0) in list(sk["walls"].items()):
                q = cur.get(key)
                if s - s0 > 60:
                    del sk["walls"][key]
                    continue
                if q is not None and q0 - q >= 0.8 * add:
                    traded = sum(v for t, p, v in sk["recent"] if p == key[1] and s0 <= t <= s)
                    if traded < 0.2 * (q0 - q):
                        sk["vanished"].append({"at": "%02d:%02d:%02d" % (s0 // 3600, s0 % 3600 // 60, s0 % 60), "side": key[0],
                                               "price": key[1], "qty": int(q0 - q), "traded": int(traded)})
                        sk["vanished"] = sk["vanished"][-10:]
                    del sk["walls"][key]
        sk["prev"] = cur
        sk["usual"] = usual


def _feed_under_over(st, rows):
    for r in rows:
        code = str(r.get("ticker", "")).replace(".T", "")
        if code not in st["stocks"]:
            continue
        sk = st["stocks"][code]
        o, u = _num(r.get("over")), _num(r.get("under"))
        if o is not None and u is not None:
            sk["over"], sk["under"], sk["uo_at"] = int(o), int(u), r.get("captured_at", "")[:19]
        if r.get("name"):
            sk["name"] = str(r["name"])


def _absorb(day_dir):
    out = {}
    try:
        with open(os.path.join(day_dir, "absorb_voice.csv"), encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                out.setdefault(r.get("ticker", ""), []).append({"at": str(r.get("rang_at", ""))[11:19], "times": _num(r.get("times")),
                                                               "price": _num(r.get("last_price")), "voice": r.get("voice", "")})
    except OSError:
        pass
    return out


def build(runtime, *, now=None, state=None):
    """Read what is new and write RuntimeDir/scalp8_board_live_v1.json. Returns the view."""
    now = (now or datetime.now(timezone.utc)).astimezone(JST)
    day = now.date().isoformat()
    state = state if state is not None else {}
    if state.get("day") != day:
        state.clear()
        state.update(day=day, stocks={})
    day_dir = os.path.join(str(runtime), "records", day)
    ticks_path = os.path.join(day_dir, "scalp8_ticks.csv")
    _feed_ticks(state, _read_new(ticks_path, state, "ticks"))
    try:
        ticks_behind = state["ticks"]["offset"] < os.path.getsize(ticks_path) - 65536
    except OSError:
        ticks_behind = False
    # the board waits while the prints are still catching up (a restart mid-day), so each board row is judged with
    # the stock's opening print already known
    if not ticks_behind:
        _feed_board(state, _read_new(os.path.join(day_dir, "scalp8_board.csv"), state, "board"))
    _feed_under_over(state, _read_new(os.path.join(day_dir, "under_over.csv"), state, "uo"))
    absorb = _absorb(day_dir)
    stocks = []
    for code, sk in state["stocks"].items():
        if sk["levels"] is None:
            continue
        lv = sk["levels"]
        b5 = sum(x[3] or 0 for x in lv[:5])
        a5 = sum(x[1] or 0 for x in lv[:5])
        usual = sk.get("usual")
        walls = [{"side": "売り", "level": i + 1, "price": a, "qty": int(aq), "x": round(aq / usual, 1)}
                 for i, (a, aq, b, bq) in enumerate(lv[:5]) if usual and aq and aq >= WALL_X * usual] + \
                [{"side": "買い", "level": i + 1, "price": b, "qty": int(bq), "x": round(bq / usual, 1)}
                 for i, (a, aq, b, bq) in enumerate(lv[:5]) if usual and bq and bq >= WALL_X * usual]
        stocks.append({
            "code": code, "name": sk["name"], "board_at": sk["board_at"], "last_price": sk["last_price"] or None,
            "levels": [{"ask": a, "ask_qty": aq, "bid": b, "bid_qty": bq} for a, aq, b, bq in lv],
            "spread": (lv[0][0] - lv[0][2]) if lv[0][0] and lv[0][2] else None,
            "bid5": int(b5), "ask5": int(a5), "buy_ratio": round(b5 / (a5 + b5), 3) if a5 + b5 else None,
            "over": sk["over"], "under": sk["under"], "uo_at": sk["uo_at"],
            "under_ratio": round(sk["under"] / (sk["under"] + sk["over"]), 3) if sk["over"] is not None and sk["under"] is not None and (sk["under"] + sk["over"]) > 0 else None,
            "usual_level_qty": int(usual) if usual else None, "walls": walls, "vanished": sk["vanished"],
            "big": sk["big"], "big_threshold": int(sk["big_th"]) if sk["big_th"] else None,
            "absorb": absorb.get(code, [])[-10:], "ratio_hist": sorted(sk["ratio_hist"].items()),
            "price_hist": sorted(sk["price_hist"].items())})
    view = {"schema_version": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "day": day, "stocks": stocks,
            "unverified": True, "note": "表示だけ・未検証。壁・消えた壁・大口吸収は売買の合図ではない",
            "real_submit_allowed": False, "trade_instruction": False}
    out = os.path.join(str(runtime), OUT_FILE)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False)
    os.replace(tmp, out)
    return view
