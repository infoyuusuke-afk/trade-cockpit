"""OWNER 2026-11-09 「FOCUSの空いた枠に、8:50と12:20にアナリストの今日の8銘柄から自信の高い順でMS2の100銘柄に入っているものを自動で入れて。
自分で固定した銘柄が先で外さない。カードに誰が挙げたか・自信・入る条件を出す。入った銘柄のその日の動きを記録する。表示と記録だけで注文はしない」
OWNER 2026-11-09 「FOCUSのアナリスト銘柄を書き出すPCの仕組みと16:00の記録をGitHubに上げて監査に回して」

The logic of the PC job that writes RuntimeDir/focus_analyst_v1.json (read by v10_positions_live.focus_analyst) and of the 16:00 record.
No paths and no source names live here: the PC wrapper reads the files and passes their text in. Display and research only.
Nothing here can place an order: the file always says real_submit_allowed=false and trade_instruction=false.

- build_slots(doc, now_hm, today, pick): the 08:50 and 12:20 slots, each made once (the first run at or after its time) and never rewritten.
- pick(plans, universe): today's ANALYST_PLAN_V1 stock lines, highest confidence first (same confidence: the order they came in),
  one entry per code with its best confidence, only codes in the MS2 100 list, at most 8.
- record(doc, ticks, today): for every stock of each slot, the first tick at or after the later of the slot time and the time the slot
  was actually made (no look-ahead), then the high, low and last of the session. Listed in slot order: the screen fills its free slots
  from the top, and only the browser knows how many were free.
"""
from __future__ import annotations

import re

SCHEMA = "100b-v10-focus-analyst-v1"
SLOTS = (("0850", "08:50"), ("1220", "12:20"))
CONF = {"高": 0, "中": 1, "低": 2}
LIMIT = 8
LINE = re.compile(r"^\s*([0-9][0-9A-Z]{2}[0-9A-Z])\s*\|([^|]*)\|\s*(買い|売り)\s*\|\s*(高|中|低)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|?(.*)$")
CSV_HEADER = ["日", "回", "コード", "銘柄", "向き", "自信", "挙げた", "入った時", "高値", "安値", "引け",
              "向きどおりの動き%", "高値まで%", "安値まで%"]


def plan_rows(plans):
    """plans: [(who, text)] in the fixed analyst order. Returns [(code, name, side, conf, entry, stop, exit, who, order)].
    Only the lines between ANALYST_PLAN_V1 and END are read; the rest of the analyst text is never used."""
    rows, order = [], 0
    for who, text in plans:
        if not isinstance(text, str) or "ANALYST_PLAN_V1" not in text:
            continue
        for line in text[text.index("ANALYST_PLAN_V1"):].splitlines()[1:]:
            if line.strip() == "END":
                break
            m = LINE.match(line)
            if m:
                order += 1
                rows.append((m.group(1), m.group(2).strip(), m.group(3), m.group(4), m.group(5).strip(),
                             m.group(6).strip(), m.group(7).strip(), str(who), order))
    return rows


def pick(plans, universe, limit=LIMIT):
    """universe: {code: name} of the MS2 100 list."""
    best = {}
    for code, name, side, conf, entry, stop, exit_, who, order in plan_rows(plans):
        if code not in universe:
            continue
        rank = CONF[conf]
        if code not in best or rank < best[code]["rank"]:
            best[code] = {"rank": rank, "order": order, "code": code, "ticker": code + ".T", "name": universe[code] or name,
                          "side": side, "conf": conf, "who": who,
                          "entry": "入る " + (entry or "—") + "・損切り " + (stop or "—") + "・手じまい " + (exit_ or "—")}
    items = sorted(best.values(), key=lambda x: (x["rank"], x["order"]))[:limit]
    return [{k: v for k, v in x.items() if k not in ("rank", "order")} for x in items]


def new_doc(today):
    return {"schema_version": SCHEMA, "date": today, "slots": {},
            "note": "アナリストの今日の8銘柄から自信の高い順・MS2の100銘柄のみ。表示と記録だけ・注文なし",
            "real_submit_allowed": False, "trade_instruction": False}


def build_slots(doc, now_hm, today, make_items):
    """Returns (doc, changed). A doc of another day (or a broken one) is started again; a slot already made is kept as it is."""
    if not isinstance(doc, dict) or doc.get("date") != today or not isinstance(doc.get("slots"), dict):
        doc = new_doc(today)
    changed = False
    for key, hm in SLOTS:
        if now_hm >= hm and key not in doc["slots"]:
            doc["slots"][key] = {"made_at": now_hm, "items": make_items()}
            changed = True
    doc["real_submit_allowed"] = False
    doc["trade_instruction"] = False
    return doc, changed


def _price(v):
    try:
        p = float(str(v).replace(",", ""))
    except ValueError:
        return None
    return p if p > 0 else None


def session_ticks(rows, wanted):
    """rows: dicts with ticker, price, exchange_time (HH:MM:SS). Only 09:00:00–15:30:59 of the wanted tickers."""
    ticks = {}
    for r in rows:
        t = r.get("ticker", "")
        if t not in wanted:
            continue
        p = _price(r.get("price", ""))
        c = (r.get("exchange_time") or "").strip()
        if p and len(c) == 8 and "09:00:00" <= c <= "15:30:59":
            ticks.setdefault(t, []).append((c, p))
    return ticks


def record(doc, tick_rows, today):
    """Returns (csv_rows, text_lines). Research only: no cost, not a recommendation."""
    if not isinstance(doc, dict) or doc.get("date") != today:
        return [], ["今日の候補がありません"]
    slots = doc.get("slots") if isinstance(doc.get("slots"), dict) else {}
    wanted = {x.get("ticker") for s in slots.values() if isinstance(s, dict) for x in (s.get("items") or []) if isinstance(x, dict)}
    ticks = session_ticks(tick_rows, wanted)
    rows, lines = [], ["# FOCUSに自動で入れたアナリスト銘柄のその日の動き %s（記録のみ・注文なし）" % today, ""]
    for key, hm in SLOTS:
        s = slots.get(key)
        if not isinstance(s, dict):
            continue
        lines.append("■ %s の回（作成 %s・値段は作成の時刻より後から。上から順に空いた枠へ入る）" % (hm, s.get("made_at")))
        start = max(hm, str(s.get("made_at") or hm)[:5]) + ":00"
        for x in s.get("items") or []:
            if not isinstance(x, dict):
                continue
            after = [p for c, p in sorted(ticks.get(x.get("ticker"), [])) if c >= start]
            if not after:
                lines.append("・%s(%s) %s・自信%s（%s）：その後の値段の記録なし" % (x.get("name"), x.get("code"), x.get("side"), x.get("conf"), x.get("who")))
                continue
            p0, hi, lo, close = after[0], max(after), min(after), after[-1]
            sign = 1 if x.get("side") == "買い" else -1
            move = sign * (close / p0 - 1) * 100
            rows.append([today, key, x.get("code"), x.get("name"), x.get("side"), x.get("conf"), x.get("who"), p0, hi, lo, close,
                         round(move, 2), round((hi / p0 - 1) * 100, 2), round((lo / p0 - 1) * 100, 2)])
            lines.append("・%s(%s) %s・自信%s（%s）：入った時 %s → 引け %s（向きどおりなら %+.2f%%）／高値 %+.2f%%・安値 %+.2f%%" % (
                x.get("name"), x.get("code"), x.get("side"), x.get("conf"), x.get("who"), p0, close, move,
                (hi / p0 - 1) * 100, (lo / p0 - 1) * 100))
        lines.append("")
    lines.append("研究の記録で、売買の勧めではありません。値段はコクピットの歩み値の記録（その時刻の後の最初の約定）。費用は入っていません。")
    return rows, lines


def merge_csv(old_rows, new_rows, today):
    """The day's rows replace that day's earlier rows; other days are kept."""
    return [r for r in old_rows if r and r[0] != today] + new_rows
