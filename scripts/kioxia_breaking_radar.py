#!/usr/bin/env python3
"""Kioxia public breaking-news radar.

Polls public sources only. It never places orders and never turns a headline
directly into a trading signal. The public TDnet viewer is intentionally not
scraped because JPX asks users not to automate scraping of that service.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kioxia_breaking_radar.json"
LOG = ROOT / "data" / "kioxia_breaking_log.jsonl"
JST = ZoneInfo("Asia/Tokyo")
UA = "TradeCockpit-KioxiaBreaking/1.0 (+https://github.com/infoyuusuke-afk/trade-cockpit)"
ALERT_WINDOW = timedelta(hours=36)

OFFICIAL_SOURCES = [
    ("Kioxia IR", "https://www.kioxia-holdings.com/ja-jp/ir/news.html", "official_ir"),
    ("Kioxia News", "https://www.kioxia-holdings.com/ja-jp/news.html", "official_news"),
]
SEC_CIK = "0001773708"
SEC_SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{SEC_CIK}.json"
SEC_ATOM_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?"
    "action=getcompany&CIK=1773708&owner=exclude&count=40&output=atom"
)
NEWS_QUERIES = [
    'Kioxia ADR OR "American Depositary Shares" OR "U.S. listing"',
    "キオクシア ADR OR 米国上場 OR 米国預託株式",
    "Kioxia Reuters",
    "Kioxia Bloomberg",
]
ADR_TERMS = (
    "adr", "american depositary", "depositary shares", "米国預託", "米国上場",
    "米国の証券取引所", "u.s. listing", "us listing", "nasdaq", "nyse",
    "f-1", "f-6", "20-f",
)
OFFICIAL_TERM_WORDS = (
    "上場日", "上場予定", "取引開始", "価格決定", "売出価格", "ads比率",
    "listing date", "pricing", "ads ratio", "commence trading",
)
MARKET_MOVING_TERMS = (
    "上場", "預託", "決算", "業績", "配当", "自己株", "主要株主", "増資",
    "株式", "訴訟", "判決", "投資計画", "買収", "合併", "提携", "一部報道",
    "listing", "offering", "earnings", "guidance", "share", "lawsuit", "merger",
)
MAJOR_MEDIA = ("reuters", "bloomberg", "nikkei", "financial times", "wall street journal")


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def fetch_bytes(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/atom+xml,application/rss+xml,text/html,application/xhtml+xml,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def event_id(source_kind: str, url: str, title: str) -> str:
    raw = f"{source_kind}|{url}|{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(JST)
    except ValueError:
        return None


def classify(event: dict) -> dict:
    text = f"{event.get('title', '')} {event.get('source', '')}".casefold()
    adr = any(term in text for term in ADR_TERMS)
    source_kind = event["source_kind"]
    source = event.get("source", "").casefold()

    if source_kind == "sec":
        stage, priority = "SEC_FILING", 100
    elif source_kind == "official_ir":
        if adr and any(word in text for word in OFFICIAL_TERM_WORDS):
            stage, priority = "OFFICIAL_TERMS", 100
        elif adr:
            stage, priority = "CONFIRMED_PREPARATION", 98
        else:
            stage = "OFFICIAL_NEWS"
            priority = 92 if any(word in text for word in MARKET_MOVING_TERMS) else 78
    elif source_kind == "official_news":
        if adr:
            stage, priority = "CONFIRMED_PREPARATION", 96
        else:
            stage, priority = "OFFICIAL_NEWS", 72
    elif adr and any(media in source for media in MAJOR_MEDIA):
        stage, priority = "REPORTED_TERMS", 90
    elif adr:
        stage, priority = "UNCONFIRMED_RUMOR", 76
    else:
        stage = "MEDIA_MENTION"
        priority = 62 if any(media in source for media in MAJOR_MEDIA) else 45

    return {
        **event,
        "adr_related": adr,
        "stage": stage,
        "priority": priority,
        "urgent": priority >= 85,
        "trading_enabled": False,
        "real_submit_allowed": False,
    }


def parse_official_html(payload: bytes, page_url: str, source: str, source_kind: str) -> list[dict]:
    text = payload.decode("utf-8", errors="replace")
    rows: dict[str, dict] = {}
    for href, body in re.findall(
        r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        text,
        flags=re.I | re.S,
    ):
        title = clean_text(body)
        if len(title) < 4:
            continue
        url = urllib.parse.urljoin(page_url, html.unescape(href))
        date_match = re.search(r"/(20\d{2})/(20\d{6})(?:-\d+)?\.html(?:$|[?#])", url)
        if not date_match:
            continue
        ymd = date_match.group(2)
        published = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}T00:00:00+09:00"
        row = {
            "source": source,
            "source_kind": source_kind,
            "title": title,
            "url": url,
            "published_at": published,
            "published_precision": "date",
        }
        row["event_id"] = event_id(source_kind, url, title)
        rows[row["event_id"]] = classify(row)
    return list(rows.values())


def google_news_url(query: str) -> str:
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    )


def parse_google_news(payload: bytes) -> list[dict]:
    root = ET.fromstring(payload)
    rows = []
    for item in root.findall("./channel/item")[:40]:
        title = clean_text(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        source_el = item.find("source")
        source = clean_text(source_el.text if source_el is not None and source_el.text else "Google News")
        raw_date = item.findtext("pubDate")
        try:
            published = parsedate_to_datetime(raw_date).astimezone(JST).isoformat()
        except (TypeError, ValueError, IndexError):
            continue
        if not title or not link.startswith("https://"):
            continue
        row = {
            "source": source,
            "source_kind": "media",
            "title": title,
            "url": link,
            "published_at": published,
            "published_precision": "timestamp",
        }
        row["event_id"] = event_id("media", link, title)
        rows.append(classify(row))
    return rows


def parse_sec_submissions(payload: bytes) -> list[dict]:
    data = json.loads(payload.decode("utf-8"))
    recent = data.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber") or []
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    primary_docs = recent.get("primaryDocument") or []
    rows = []
    for i, accession in enumerate(accessions[:80]):
        form = forms[i] if i < len(forms) else ""
        filing_date = filing_dates[i] if i < len(filing_dates) else ""
        primary = primary_docs[i] if i < len(primary_docs) else ""
        if not accession or not form or not filing_date:
            continue
        accession_compact = accession.replace("-", "")
        archive_cik = str(int(SEC_CIK))
        if primary:
            link = f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/{accession_compact}/{primary}"
        else:
            link = f"https://www.sec.gov/Archives/edgar/data/{archive_cik}/{accession_compact}/"
        title = f"Kioxia Holdings SEC {form} filing ({filing_date})"
        row = {
            "source": "SEC EDGAR",
            "source_kind": "sec",
            "title": title,
            "url": link,
            "published_at": f"{filing_date}T00:00:00+09:00",
            "published_precision": "date",
            "sec_form": form,
            "sec_accession": accession,
        }
        row["event_id"] = event_id("sec", link, title)
        rows.append(classify(row))
    return rows


def parse_sec_atom(payload: bytes) -> list[dict]:
    root = ET.fromstring(payload)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    rows = []
    for entry in root.findall("a:entry", ns):
        title = clean_text(entry.findtext("a:title", default="", namespaces=ns))
        updated = entry.findtext("a:updated", default="", namespaces=ns)
        link_el = entry.find("a:link", ns)
        link = (link_el.attrib.get("href") if link_el is not None else "") or ""
        if not title or not link.startswith("https://"):
            continue
        try:
            published = datetime.fromisoformat(updated.replace("Z", "+00:00")).astimezone(JST).isoformat()
        except ValueError:
            continue
        row = {
            "source": "SEC EDGAR",
            "source_kind": "sec",
            "title": title,
            "url": link,
            "published_at": published,
            "published_precision": "timestamp",
        }
        row["event_id"] = event_id("sec", link, title)
        rows.append(classify(row))
    return rows


def dedupe(events: list[dict]) -> list[dict]:
    unique = {}
    for event in events:
        unique[event["event_id"]] = event
    return list(unique.values())


def alert_recent(event: dict, now: datetime) -> bool:
    published = parse_iso(event.get("published_at"))
    if published is None:
        return False
    window = timedelta(days=2) if event.get("published_precision") == "date" else ALERT_WINDOW
    age = now - published
    return timedelta(0) <= age <= window


def build_state(events: list[dict], previous: dict | None, source_health: list[dict], now: datetime) -> tuple[dict, list[dict]]:
    previous = previous or {}
    previous_items = {x["event_id"]: x for x in previous.get("events", []) if x.get("event_id")}
    bootstrap = not bool(previous.get("bootstrap_complete"))
    merged = []
    new_urgent = []
    now_iso = now.isoformat()

    for event in dedupe(events):
        old = previous_items.get(event["event_id"])
        event["first_seen_at"] = old.get("first_seen_at") if old else now_iso
        event["last_seen_at"] = now_iso
        merged.append(event)
        if not old and not bootstrap and event.get("urgent") and alert_recent(event, now):
            new_urgent.append(event)

    fetched_ids = {x["event_id"] for x in merged}
    for old in previous_items.values():
        if old["event_id"] not in fetched_ids:
            merged.append(old)

    merged.sort(key=lambda x: (x.get("published_at", ""), x.get("priority", 0)), reverse=True)
    merged = merged[:160]
    source_status = "READY" if source_health and all(x["status"] == "OK" for x in source_health) else "DEGRADED"
    state = {
        "schema_version": "kioxia-breaking-radar-1.0",
        "ticker": "285A.T",
        "name": "キオクシアホールディングス",
        "status": source_status,
        "bootstrap_complete": True,
        "policy": (
            "5分間隔の公開情報監視。一次情報・SEC・主要報道・噂を分離し、"
            "見出しだけで売買サインへ変換しない。TDnet無料閲覧サービスは自動スクレイピングしない。"
        ),
        "source_health": source_health,
        "events": merged,
        "trading_enabled": False,
        "real_submit_allowed": False,
    }
    return state, sorted(new_urgent, key=lambda x: x["priority"], reverse=True)


def stable_view(state: dict) -> dict:
    clone = json.loads(json.dumps(state, ensure_ascii=False))
    for event in clone.get("events", []):
        event.pop("last_seen_at", None)
    clone.pop("updated_at", None)
    return clone


def render_alert(events: list[dict], now: datetime) -> str:
    lines = [
        "@infoyuusuke-afk **KIOXIA BREAKING RADAR**",
        "",
        f"新規高重要度イベント {len(events)}件を検知しました。検知時刻: {now.strftime('%Y-%m-%d %H:%M:%S JST')}",
    ]
    for event in events[:8]:
        lines.extend([
            "",
            f"- **[{event['stage']}] {event['title']}**",
            f"  - source: {event['source']} / priority: {event['priority']}",
            f"  - published: {event['published_at']}",
            f"  - {event['url']}",
        ])
    lines.extend([
        "",
        "これは速報検知であり売買サインではありません。一次情報・SEC・主要報道の順に確認してください。",
    ])
    return "\n".join(lines)


def load_previous() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {}


def persist(state: dict, new_urgent: list[dict], now: datetime, alert_file: Path | None) -> bool:
    previous = load_previous()
    changed = stable_view(state) != stable_view(previous)
    if changed:
        state["updated_at"] = now.isoformat()
        OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if new_urgent:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            for event in new_urgent:
                fh.write(json.dumps({"detected_at": now.isoformat(), **event}, ensure_ascii=False) + "\n")
        if alert_file:
            alert_file.write_text(render_alert(new_urgent, now), encoding="utf-8")
    return changed


def scan(now: datetime, fetcher=fetch_bytes) -> tuple[list[dict], list[dict]]:
    events = []
    health = []
    for source, url, kind in OFFICIAL_SOURCES:
        try:
            rows = parse_official_html(fetcher(url), url, source, kind)
            events.extend(rows)
            health.append({"source": source, "status": "OK", "count": len(rows)})
        except Exception as exc:
            health.append({"source": source, "status": "ERROR", "error": type(exc).__name__})
    sec_errors = []
    sec_rows = []
    sec_endpoint = None
    try:
        sec_rows = parse_sec_submissions(fetcher(SEC_SUBMISSIONS_URL))
        sec_endpoint = "submissions-json"
    except Exception as exc:
        sec_errors.append(type(exc).__name__ + (f":{getattr(exc, 'code', '')}" if getattr(exc, "code", None) else ""))
        try:
            sec_rows = parse_sec_atom(fetcher(SEC_ATOM_URL))
            sec_endpoint = "company-atom"
        except Exception as fallback_exc:
            sec_errors.append(type(fallback_exc).__name__ + (f":{getattr(fallback_exc, 'code', '')}" if getattr(fallback_exc, "code", None) else ""))
    if sec_endpoint:
        events.extend(sec_rows)
        health.append({
            "source": "SEC EDGAR",
            "status": "OK",
            "count": len(sec_rows),
            "endpoint": sec_endpoint,
            "fallback_errors": sec_errors,
        })
    else:
        health.append({"source": "SEC EDGAR", "status": "ERROR", "errors": sec_errors})
    media_count = 0
    media_errors = 0
    for query in NEWS_QUERIES:
        try:
            rows = parse_google_news(fetcher(google_news_url(query)))
            events.extend(rows)
            media_count += len(rows)
        except Exception:
            media_errors += 1
    health.append({
        "source": "Google News RSS targeted queries",
        "status": "OK" if media_errors < len(NEWS_QUERIES) else "ERROR",
        "count": media_count,
        "query_errors": media_errors,
    })
    return dedupe(events), health


def bootstrap_health_ok(health: list[dict]) -> bool:
    """Require one official Kioxia source and one independent discovery path."""
    by_source = {row.get("source"): row.get("status") for row in health}
    official_ok = any(by_source.get(name) == "OK" for name in ("Kioxia IR", "Kioxia News"))
    discovery_ok = any(
        by_source.get(name) == "OK"
        for name in ("SEC EDGAR", "Google News RSS targeted queries")
    )
    return official_ok and discovery_ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alert-file", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and parse live public sources without writing state, logs, alerts, or GitHub outputs.",
    )
    args = parser.parse_args()
    now = datetime.now(JST)
    events, health = scan(now)
    if args.dry_run:
        ready = bootstrap_health_ok(health)
        print(json.dumps({
            "mode": "dry-run",
            "ready": ready,
            "event_count": len(events),
            "source_health": health,
        }, ensure_ascii=False))
        if not ready:
            raise SystemExit(2)
        return
    previous = load_previous()
    state, new_urgent = build_state(events, previous, health, now)
    persist(state, new_urgent, now, args.alert_file)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"urgent_count={len(new_urgent)}\n")
    print(f"Kioxia Breaking Radar: events={len(events)} urgent_new={len(new_urgent)} status={state['status']}")


if __name__ == "__main__":
    main()
