"""Fresh copies of the cockpit's public analysis files for the local V10 screen.

OWNER 2026-10-23 「キオクシアの予測チャートが直ってない」: V10 serves files from a pinned
checkout, so the analysis JSON that the update workflow refreshes on main several times a
day (KIOXIA 5-minute forecast, market, correlations, events, earnings, next themes, ...)
stayed at the checkout's date. This copies those public files from main into
RuntimeDir/public_feed; the Gateway serves a copy there instead of the checkout's file.
Each file must be valid JSON and at most MAX_BYTES; a failed or invalid download keeps
the previous copy. Read-only display data: nothing here reaches a signal, gate, Brain
score, voice or order.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import urllib.request

BASE_URL = "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/"
FEED_FILES = (
    "correlations.json", "credit_supply.json", "earnings_calendar.json", "event_calendar.json",
    "kioxia_5m_calendar.json", "kioxia_catalysts.json", "kioxia_prediction_history.json",
    "live_focus.json", "next_theme_radar.json", "paper_trade_history.json", "signals.json",
    "weekly_review.json", "world_market.json",
)
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 20
META_FILE = "public_feed_meta.json"


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trade-cockpit-v10-public-feed"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        data = resp.read(MAX_BYTES + 1)
    return data


def sync(target: Path, *, fetch=_download, now: datetime | None = None) -> dict:
    """Refresh every feed file it can; returns a summary (also written as META_FILE)."""
    now = now or datetime.now(timezone.utc)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError("PUBLIC_FEED_DIR_UNTRUSTED")
    files = {}
    for name in FEED_FILES:
        try:
            data = fetch(BASE_URL + name)
            if len(data) > MAX_BYTES:
                raise ValueError("TOO_LARGE")
            json.loads(data.decode("utf-8-sig"))
            temp = target / (name + ".tmp")
            temp.write_bytes(data)
            os.replace(temp, target / name)
            files[name] = {"ok": True, "bytes": len(data)}
        except Exception as exc:  # keep the previous copy
            files[name] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    meta = {"fetched_at": now.isoformat(), "source": BASE_URL, "files": files,
            "real_submit_allowed": False, "trade_instruction": False}
    (target / META_FILE).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return meta
