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
SUMMARY_FILE = "market_summary.json"
DATA_MAX_BYTES = 16 * 1024 * 1024
# OWNER 2026-10-23 「検証・除外に本来地合判定がでるはず」: the daily index figures of the
# public page's 地合いサマリー, plus a reference verdict. Display only (never a gate,
# Brain score, voice or order); daily after-close data, not intraday.
SUMMARY_INDICES = ("日経平均", "TOPIX", "NASDAQ", "S&P500", "SOX", "VIX", "ドル円", "米10年金利")
INDEX_FIELDS = ("price", "change_pct", "ret5", "ret20", "ma5", "ma20", "ma60", "from_ma20")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def regime_verdict(indices: dict) -> dict:
    """Reference score from daily data: Japan trend and day move, US risk appetite."""
    parts = []
    for name in ("日経平均", "TOPIX"):
        r = indices.get(name) or {}
        price, ma20, ma60, chg = (_num(r.get(k)) for k in ("price", "ma20", "ma60", "change_pct"))
        if price is not None and ma20 is not None:
            parts.append((name + " 20日線の" + ("上" if price > ma20 else "下"), 1 if price > ma20 else -1))
        if ma20 is not None and ma60 is not None:
            parts.append((name + " 20日線が60日線の" + ("上" if ma20 > ma60 else "下"), 1 if ma20 > ma60 else -1))
        if chg is not None and abs(chg) >= 0.3:
            parts.append((name + " 前日比%+.2f%%" % chg, 1 if chg > 0 else -1))
    for name in ("NASDAQ", "SOX"):
        chg = _num((indices.get(name) or {}).get("change_pct"))
        if chg is not None and abs(chg) >= 0.3:
            parts.append((name + " %+.2f%%" % chg, 1 if chg > 0 else -1))
    vix = _num((indices.get("VIX") or {}).get("change_pct"))
    if vix is not None and abs(vix) >= 5:
        parts.append(("VIX %+.1f%%" % vix, -1 if vix > 0 else 1))
    score = sum(v for _, v in parts)
    label = "強い" if score >= 3 else "弱い" if score <= -3 else "中立"
    return {"label": label, "score": score, "parts": [{"text": t, "point": v} for t, v in parts],
            "status": "REFERENCE_DAILY_NOT_A_GATE"}


def summarize(data: dict) -> dict:
    indices = {}
    for name in SUMMARY_INDICES:
        r = (data.get("indices") or {}).get(name) or {}
        if r.get("ok") is True:
            indices[name] = {k: _num(r.get(k)) for k in INDEX_FIELDS}
    themes = []
    for row in (data.get("themes") or [])[:5]:
        try:
            name, score, count, members = row
            themes.append({"name": str(name), "score": _num(score), "count": count,
                           "members": [{"name": str(m[0]), "score": _num(m[1]), "change_pct": _num(m[2])}
                                       for m in members[:3]]})
        except (TypeError, ValueError, IndexError):
            continue
    return {"updated_at": str(data.get("updated_at") or ""), "phase": str(data.get("phase") or ""),
            "indices": indices, "verdict": regime_verdict(indices), "themes": themes,
            "real_submit_allowed": False, "trade_instruction": False}


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
    try:
        raw = fetch(BASE_URL + "data.json")
        if len(raw) > DATA_MAX_BYTES:
            raise ValueError("TOO_LARGE")
        summary = summarize(json.loads(raw.decode("utf-8-sig")))
        temp = target / (SUMMARY_FILE + ".tmp")
        temp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")   # index order kept
        os.replace(temp, target / SUMMARY_FILE)
        files[SUMMARY_FILE] = {"ok": True, "bytes": (target / SUMMARY_FILE).stat().st_size}
    except Exception as exc:  # keep the previous copy
        files[SUMMARY_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    meta = {"fetched_at": now.isoformat(), "source": BASE_URL, "files": files,
            "real_submit_allowed": False, "trade_instruction": False}
    (target / META_FILE).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return meta
