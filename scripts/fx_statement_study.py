#!/usr/bin/env python3
"""Measure USD/JPY reactions to verified official-comment clusters."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "fx_statement_events.json"
OUT = ROOT / "fx_statement_study.json"
JST = ZoneInfo("Asia/Tokyo")


def prior_output():
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def download_fx(start, end):
    frame = yf.download(
        "JPY=X", start=start, end=end, interval="1d", auto_adjust=False,
        progress=False, threads=False, timeout=20,
    )
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if frame.empty or "Close" not in frame:
        raise RuntimeError("USDJPY history unavailable")
    return frame.dropna(subset=["Close"])


def reaction(frame, event_date):
    day = pd.Timestamp(event_date)
    prior = frame.loc[frame.index < day]
    after = frame.loc[frame.index >= day]
    if prior.empty or after.empty:
        return None
    base = float(prior["Close"].iloc[-1])
    d0 = float(after["Close"].iloc[0])
    d1 = float(after["Close"].iloc[min(1, len(after) - 1)])
    return {
        "base": round(base, 3), "close_0d": round(d0, 3),
        "move_0d_pct": round((d0 / base - 1) * 100, 3),
        "move_1d_pct": round((d1 / base - 1) * 100, 3),
    }


def aggregate(events, key=None):
    groups = {}
    for e in events:
        if not e.get("comparable"):
            continue
        label = e.get(key, "全体") if key else "純粋な発言"
        groups.setdefault(label, []).append(e)
    rows = []
    for label, items in groups.items():
        moves = [float(x["reaction"]["move_1d_pct"]) for x in items]
        hits = sum(bool(x.get("hit")) for x in items)
        rows.append({
            "label": label, "sample": len(items), "hits": hits,
            "hit_rate": round(hits / len(items) * 100, 1),
            "median_1d_pct": round(float(pd.Series(moves).median()), 3),
            "reliable": len(items) >= 10,
        })
    return sorted(rows, key=lambda x: (x["sample"], x["hit_rate"]), reverse=True)


def main():
    payload = json.loads(EVENTS.read_text(encoding="utf-8"))
    events = [x for x in payload.get("events", []) if x.get("verified")]
    previous = prior_output()
    try:
        start = (pd.Timestamp(min(x["date"] for x in events)) - timedelta(days=7)).date().isoformat()
        end = (datetime.now(JST).date() + timedelta(days=3)).isoformat()
        frame = download_fx(start, end)
        price_source = "Yahoo Finance JPY=X 日足"
    except Exception as exc:
        frame = None
        price_source = f"取得失敗・前回値保持（{type(exc).__name__}）"

    old = {x.get("date"): x for x in previous.get("events", [])}
    measured = []
    for raw in events:
        item = dict(raw)
        result = reaction(frame, item["date"]) if frame is not None else None
        if result is None:
            result = (old.get(item["date"]) or {}).get("reaction")
        item["reaction"] = result
        comparable = bool(result) and not item.get("confounded")
        item["comparable"] = comparable
        if comparable:
            move = float(result["move_1d_pct"])
            item["hit"] = move <= -.30 if item["direction"] == "yen_up" else move >= .30
        else:
            item["hit"] = None
        measured.append(item)

    verbal = aggregate(measured)
    current = sorted(measured, key=lambda x: x["date"], reverse=True)[0] if measured else None
    sample = verbal[0]["sample"] if verbal else 0
    hit_rate = verbal[0]["hit_rate"] if verbal else None
    if sample < 10:
        grade = "統計不足・参考のみ"
        score = 0
    else:
        grade = "円高発言優位" if hit_rate >= 60 else "優位性なし"
        score = round((hit_rate - 50) * 2)
    output = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "price_source": price_source,
        "method": payload.get("rule"),
        "current": current,
        "summary": {
            "grade": grade, "signal_score": score,
            "sample": sample, "hit_rate": hit_rate,
            "minimum_sample": 10,
            "warning": "N<10は先回り点へ加算しない。実弾介入・重要指標重複日は除外。",
        },
        "by_category": aggregate(measured, "category"),
        "events": measured,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
