#!/usr/bin/env python3
"""C-024: evidence-first, read-only theme detection and audit output.

Never places orders, changes the MS2 watchlist, or treats replay data as live.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
WEIGHTS = {"novelty": 15, "catalyst": 15, "money_flow": 20,
           "japan_link": 15, "breadth": 10, "small_cap": 10,
           "overseas_lead": 10, "price_confirmation": 5}


def parse_time(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(JST) if dt.tzinfo else None
    except ValueError:
        return None


def recent(at, now, minutes):
    return at is not None and timedelta() <= now - at <= timedelta(minutes=minutes)


def fetch_news(query, now, opener=urllib.request.urlopen):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    req = urllib.request.Request(url, headers={"User-Agent": "trade-cockpit-next-theme/0.1"})
    with opener(req, timeout=12) as response:
        root = ET.fromstring(response.read())
    events = []
    for item in root.findall("./channel/item")[:30]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        raw_date = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(raw_date).astimezone(JST)
        except (TypeError, ValueError, IndexError):
            continue
        if recent(published, now, 24 * 60) and link.startswith("https://"):
            events.append({"title": title, "url": link, "published_at": published.isoformat(),
                           "source": (item.findtext("source") or "Google News RSS").strip()})
    return events


def theme_events(theme, events):
    aliases = [a.casefold() for a in theme["aliases"]]
    return [e for e in events if any(a in e.get("title", "").casefold() for a in aliases)]


def tv_rows(payload):
    unique = {}
    for row in payload.get("scan_rows") or []:
        code = str(row.get("code") or "")
        if code:
            unique[code] = row
    for block in (payload.get("rankings") or {}).values():
        for row in block.get("items") or []:
            code = str(row.get("code") or "")
            if code:
                unique[code] = row
    return unique


def tv_time(payload):
    value = payload.get("updated_at", "")
    return parse_time(value.replace(" JST", "+09:00").replace(" ", "T", 1))


def evaluate(theme, events, observations, screener, now, previous=None):
    matched = theme_events(theme, events)
    latest = max((parse_time(e.get("published_at")) for e in matched), default=None)
    latest = latest if latest and recent(latest, now, 24 * 60) else None
    obs_at = parse_time(observations.get("observed_at"))
    obs_fresh = recent(obs_at, now, 30) and observations.get("source_url", "").startswith("https://")
    tv_fresh = recent(tv_time(screener), now, 30) and not screener.get("error")
    rows = tv_rows(screener) if tv_fresh else {}
    stocks = []
    for relation in theme["relations"]:
        row = rows.get(relation["code"], {})
        change = row.get("change_pct")
        rvol = row.get("relative_volume")
        price = row.get("price")
        volume = row.get("volume")
        reaction = (isinstance(change, (int, float)) and change >= 3 and
                    isinstance(rvol, (int, float)) and rvol >= 1.5 and
                    isinstance(price, (int, float)) and isinstance(volume, (int, float)))
        stocks.append({**relation, "market_reaction_verified": bool(reaction),
                       "change_pct": change if tv_fresh else None,
                       "relative_volume": rvol if tv_fresh else None,
                       "turnover_yen": round(price * volume) if reaction else None})
    responders = [s for s in stocks if s["market_reaction_verified"]]
    first_seen = (parse_time((previous or {}).get("first_seen")) or now) if matched else None
    money_ratio = observations.get("turnover_vs_baseline") if obs_fresh else None
    peg_deviation = observations.get("peg_deviation_pct") if obs_fresh else None
    money_ok = (isinstance(money_ratio, (int, float)) and money_ratio >= 3) or (
        isinstance(peg_deviation, (int, float)) and abs(peg_deviation) >= 2)
    catalyst_words = ("list", "上場", "partnership", "提携", "depeg", "peg", "乖離")
    catalyst = any(any(w in e["title"].casefold() for w in catalyst_words) for e in matched)
    market_caps = [rows[s["code"]].get("market_cap") for s in responders if s["code"] in rows]
    smallcap = any(isinstance(v, (int, float)) and 0 < v <= 100_000_000_000 for v in market_caps)
    lead = latest and tv_fresh and tv_time(screener) and latest < tv_time(screener)
    points = {
        "novelty": 15 if latest and first_seen and recent(first_seen, now, 7 * 24 * 60) else 0,
        "catalyst": 10 if catalyst else (5 if matched else 0),
        "money_flow": 20 if money_ok else 0,
        "japan_link": 15 if stocks and all(s.get("source_url", "").startswith("https://") for s in stocks) else 0,
        "breadth": min(10, len(responders) * 5),
        "small_cap": 10 if smallcap else 0,
        "overseas_lead": 10 if lead else 0,
        "price_confirmation": 5 if responders else 0,
    }
    score = sum(points.values())
    confirmed = score >= 80 and money_ok and len(responders) >= 2 and tv_fresh and obs_fresh
    status = "CONFIRMED" if confirmed else ("WATCH" if matched else "NO_EVENT")
    return {"theme_id": theme["id"], "theme": theme["label"], "status": status,
            "score": score, "score_breakdown": points, "weights": WEIGHTS,
            "first_seen": first_seen.isoformat() if first_seen else None,
            "last_event_at": latest.isoformat() if latest else None,
            "events": matched[:10], "stocks": stocks, "reacting_stock_count": len(responders),
            "evidence": {"news_fresh": bool(latest), "money_flow_fresh": bool(obs_fresh),
                         "money_flow_anomaly": bool(money_ok), "tv_fresh": bool(tv_fresh),
                         "money_flow_source": observations.get("source_url") if obs_fresh else None},
            "emergency_display": bool(score >= 75 and matched),
            "handoff_codes": [s["code"] for s in stocks] if matched else [],
            "trading_enabled": False, "real_submit_allowed": False}


def run(now, config, events, observations, screener, previous):
    results = [evaluate(t, events.get(t["id"], []), observations.get(t["id"], {}),
                        screener, now, (previous or {}).get(t["id"])) for t in config["themes"]]
    return {"schema_version": "next-theme-radar-0.2", "updated_at": now.isoformat(),
            "source_note": "ニュース集約RSSは一次資料ではない。価格・資金流入は取得済み証拠だけで採点。",
            "themes": results, "trading_enabled": False, "real_submit_allowed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path, help="再現テスト専用。公開結果・実検知ログを書かない")
    args = parser.parse_args()
    config = json.loads((ROOT / "config/next_theme_radar.json").read_text(encoding="utf-8"))
    if args.replay:
        fixture = json.loads(args.replay.read_text(encoding="utf-8"))
        report = run(parse_time(fixture["now"]), config, fixture["events"],
                     fixture.get("observations", {}), fixture.get("screener", {}), {})
        print(json.dumps({"replay_only": True, **report}, ensure_ascii=False, indent=2))
        return
    now = datetime.now(JST)
    old_path = ROOT / "next_theme_radar.json"
    try:
        old = json.loads(old_path.read_text(encoding="utf-8"))
        previous = ({t["theme_id"]: t for t in old.get("themes", [])}
                    if old.get("schema_version") == "next-theme-radar-0.2" else {})
    except (FileNotFoundError, ValueError):
        old = {}
        previous = {}
    events = {}
    for theme in config["themes"]:
        try:
            events[theme["id"]] = fetch_news(theme["feed_query"], now)
        except (OSError, ET.ParseError, ValueError):
            events[theme["id"]] = []
    def load(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    observations = load(ROOT / "data/next_theme_observations.json")
    screener = load(ROOT / "tradingview_screener_watch.json")
    report = run(now, config, events, observations, screener, previous)
    def identity(item):
        return (item.get("status"), item.get("score"), item.get("first_seen"),
                item.get("last_event_at"),
                item.get("reacting_stock_count"), item.get("evidence"))
    unchanged = all(identity(item) == identity(previous.get(item["theme_id"], {}))
                    for item in report["themes"])
    if unchanged and recent(parse_time(old.get("updated_at")), now, 59):
        return
    old_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_path = ROOT / "data/next_theme_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for item in report["themes"]:
            before = previous.get(item["theme_id"], {})
            if item["status"] != "NO_EVENT" and (item["status"], item["score"], item["last_event_at"]) != (
                    before.get("status"), before.get("score"), before.get("last_event_at")):
                log.write(json.dumps({"detected_at": now.isoformat(), "theme_id": item["theme_id"],
                                      "status": item["status"], "score": item["score"],
                                      "score_breakdown": item["score_breakdown"],
                                      "first_seen": item["first_seen"],
                                      "last_event_at": item["last_event_at"],
                                      "reacting_stock_count": item["reacting_stock_count"],
                                      "evidence": item["evidence"]}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
