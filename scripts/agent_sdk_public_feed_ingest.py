"""100B read-only official BOJ RSS -> public-only Agents SDK evidence JSON.

Manual --fetch only, no model/API/Excel/Broker/GitHub/Scheduler integration.
Conservative availability: fetched_at, NOT invented public release time.
If RSS gives only a publication calendar date, treat the headline as observed at fetch;
never fabricate an exact public release clock or a predictive lead time.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta, date
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
import xml.etree.ElementTree as ET

SCHEMA = "100b-public-agent-evidence-v1"
FEEDS = {
    "pre_next": "https://www.boj.or.jp/rss/whatsnew.xml",
    "supply_sq": "https://www.boj.or.jp/rss/statistics.xml",
}
HOST = "www.boj.or.jp"
MAX_FEED_BYTES = 1_048_576
MAX_ITEMS_PER_ROLE = 6
MAX_AGE = timedelta(days=7)
JST = timezone(timedelta(hours=9))
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


class EvidenceBlocked(ValueError):
    """Failure is non-billable; never fabricate an observation."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _field(node: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        for child in node:
            if _local(child.tag) == name:
                raw = (child.text or "").strip()
                if raw:
                    return raw
    return ""


def _time(raw: str) -> datetime:
    if not raw or not re.search(r"\d{1,2}:\d\d", raw):
        raise EvidenceBlocked("RSS_PUBLICATION_CLOCK_MISSING")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError) as exc:
            raise EvidenceBlocked("RSS_PUBLICATION_UNPARSEABLE") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise EvidenceBlocked("RSS_PUBLICATION_OFFSET_MISSING")
    return dt.astimezone(timezone.utc)


def _url(raw: str) -> str:
    url = urlsplit(raw)
    if (url.scheme != "https" or url.hostname != HOST or url.port not in (None, 443)
            or url.username or url.password or url.query or url.fragment
            or not url.path.startswith("/") or len(raw) > 500):
        raise EvidenceBlocked("RSS_LINK_NOT_APPROVED_PUBLIC_HTTPS")
    return raw


def fetch_official_feed(url: str) -> bytes:
    if url not in FEEDS.values():
        raise EvidenceBlocked("RSS_ENDPOINT_NOT_ALLOWLISTED")
    opener = build_opener(NoRedirect())
    request = Request(url, headers={
        "User-Agent": "100B-Cockpit-Public-RSS-Research/0.1 (manual; no trading)",
        "Accept": "application/rss+xml, application/xml, text/xml",
    })
    try:
        with opener.open(request, timeout=12) as response:
            if response.status != 200:
                raise EvidenceBlocked("RSS_HTTP_NOT_OK")
            raw = response.read(MAX_FEED_BYTES + 1)
    except EvidenceBlocked:
        raise
    except Exception as exc:
        raise EvidenceBlocked("RSS_FETCH_UNAVAILABLE") from exc
    if len(raw) > MAX_FEED_BYTES:
        raise EvidenceBlocked("RSS_SIZE_LIMIT")
    return raw


def parse_feed(raw: bytes, role: str, observed_at: datetime) -> list[dict]:
    """Parse trusted feed metadata only; do not retrieve articles or store prices."""
    if role not in FEEDS or not isinstance(raw, bytes) or len(raw) > MAX_FEED_BYTES:
        raise EvidenceBlocked("RSS_INPUT_INVALID")
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise EvidenceBlocked("RSS_XML_DTD_FORBIDDEN")
    if observed_at.utcoffset() is None:
        raise EvidenceBlocked("RSS_CLOCK_UNVERIFIED")
    now = observed_at.astimezone(timezone.utc)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise EvidenceBlocked("RSS_XML_INVALID") from exc
    results: list[dict] = []
    seen: set[str] = set()
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title = html.unescape(_field(node, ("title",)))
        title = re.sub(r"\s+", " ", title).strip()
        published = _field(node, ("pubdate", "date", "published", "updated"))
        link = _field(node, ("link",))
        if not link:
            link = next((c.attrib.get("href", "") for c in node
                         if _local(c.tag) == "link" and c.attrib.get("href")), "")
        if not title or not published or not link:
            continue
        try:
            link = _url(link)
            # BOJ RSS may carry a *calendar day* without publication clock.
            # Never manufacture hh:mm or a zone on such a date. This records
            # evidence of a headline observed NOW, NOT when the BOJ released it.
            date_only = bool(re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", published))
            if date_only:
                published_day = date.fromisoformat(published)
                today_jst = now.astimezone(JST).date()
                if published_day > today_jst or (today_jst - published_day).days > 7:
                    continue
                at = now
                temporal_label = (
                    "DATE_ONLY_OBSERVED_AT_FETCH; source calendar day="
                    + published + "; earliest release TIME UNKNOWN; no lead-time inference. "
                )
            else:
                at = _time(published)
                if at > now or now - at > MAX_AGE:
                    continue
                temporal_label = "EXPLICIT_FEED_PUBLICATION_TIMESTAMP; "
        except (EvidenceBlocked, ValueError):
            continue
        if link in seen:
            continue
        seen.add(link)
        token = hashlib.sha256((role + "\n" + link).encode("utf-8")).hexdigest()[:20]
        summary = (
            "Official BOJ RSS headline ONLY; article/data not inspected; "
            + temporal_label + "not a trading signal: " + title
        )[:390]
        if any(ord(c) < 32 for c in summary):
            continue
        results.append({
            "source_id": f"boj_{role}_{token}",
            "role": role, "source_url": link,
            "as_of": at.isoformat(),
            # available_at is actual first verified fetch, NOT release-time proof.
            "available_at": now.isoformat(),
            "summary": summary,
        })
        if len(results) >= MAX_ITEMS_PER_ROLE:
            break
    return results


def build_snapshot(feeds: dict[str, bytes], run_id: str,
                   observed_at: datetime) -> dict:
    if not RUN_ID.fullmatch(run_id):
        raise EvidenceBlocked("RSS_RUN_ID_INVALID")
    if not feeds or any(role not in FEEDS for role in feeds):
        raise EvidenceBlocked("RSS_ROLE_INVALID")
    rows = []
    for role in ("pre_next", "supply_sq"):
        if role in feeds:
            rows.extend(parse_feed(feeds[role], role, observed_at))
    if not rows:
        raise EvidenceBlocked("NO_DATED_RECENT_OFFICIAL_RSS_EVIDENCE")
    return {"schema_version": SCHEMA, "run_id": run_id, "sources": rows}


def write_once(path: Path, snapshot: dict) -> None:
    """No overwrite and no accidental GitHub publication of fetched evidence."""
    if not path.parent.is_dir() or path.is_symlink():
        raise EvidenceBlocked("PRIVATE_OUTPUT_DIRECTORY_REQUIRED")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    payload = (json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                          indent=2) + "\n").encode("utf-8")
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise EvidenceBlocked("OUTPUT_ALREADY_EXISTS_NO_REPLAY") from exc
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Manual BOJ official RSS evidence builder")
    ap.add_argument("--fetch", action="store_true", required=True,
                    help="Download two approved BOJ RSS feeds; no AI/API calls")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        feeds = {role: fetch_official_feed(url) for role, url in FEEDS.items()}
        snap = build_snapshot(feeds, args.run_id, datetime.now(timezone.utc))
        write_once(args.output, snap)
        print(json.dumps({
            "status": "PUBLIC_FEED_SNAPSHOT_WRITTEN_RESEARCH_ONLY",
            "source_count": len(snap["sources"]),
            "roles": sorted({r["role"] for r in snap["sources"]}),
            "model_calls": 0, "real_submit_allowed": False
        }, sort_keys=True))
        return 0
    except (EvidenceBlocked, OSError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, EvidenceBlocked) else "RSS_IO_BLOCKED"
        print(json.dumps({"status": "BLOCKED", "reason": reason,
                          "model_calls": 0, "real_submit_allowed": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
