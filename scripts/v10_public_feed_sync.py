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

from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import urllib.request

BASE_URL = "https://raw.githubusercontent.com/infoyuusuke-afk/trade-cockpit/main/"
# Audit 6349440798: live_focus.json (voice switch), signals.json (IN/準備 lists in the
# live tab) and paper_trade_history.json (trade control) are NOT fed: they are not
# display-only.
FEED_FILES = (
    "correlations.json", "credit_supply.json", "earnings_calendar.json", "event_calendar.json",
    "kioxia_5m_calendar.json", "kioxia_catalysts.json", "kioxia_prediction_history.json",
    "next_theme_radar.json", "weekly_review.json", "world_market.json",
)
# OWNER 2026-10-23 「古い時は画面に古いと出して、表示可にしない」: a file whose own update
# time is older than this (hours), or has no readable update time, is marked stale in
# the meta file; the screen shows 古い and nothing from it as verified. World market rows
# of a stale copy are written with verified=false.
STALE_HOURS = {"weekly_review.json": 24 * 8}
DEFAULT_STALE_HOURS = 24
TIME_KEYS = ("updated_at", "generated_at", "created_at", "fetched_at")
_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2}|JST)?")


def source_time(doc) -> datetime | None:
    """The file's own update time; None when absent or without a time zone (never assumed)."""
    if not isinstance(doc, dict):
        return None
    for key in TIME_KEYS:
        m = _TIME.search(str(doc.get(key) or ""))
        if not m:
            continue
        zone = m.group(7)
        if not zone:
            return None
        if zone == "JST":
            tz = timezone(timedelta(hours=9))
        elif zone == "Z":
            tz = timezone.utc
        else:
            sign = 1 if zone[0] == "+" else -1
            digits = zone[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)),
                        int(m.group(6) or 0), tzinfo=tz)
    return None


def freshness(name: str, doc, now: datetime) -> dict:
    at = source_time(doc)
    limit = STALE_HOURS.get(name, DEFAULT_STALE_HOURS)
    if at is None:
        return {"source_at": None, "age_hours": None, "limit_hours": limit, "stale": True, "reason": "NO_SOURCE_TIME"}
    age = (now - at).total_seconds() / 3600
    stale = age > limit or age < -0.25
    return {"source_at": at.isoformat(), "age_hours": round(age, 2), "limit_hours": limit, "stale": stale,
            "reason": "TOO_OLD" if age > limit else "FUTURE_TIME" if age < -0.25 else None}
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 20
META_FILE = "public_feed_meta.json"
SUMMARY_FILE = "market_summary.json"
# OWNER 2026-10-23 「EVENT5もあやしい」: only the EVENT 5 list (speculative_theme_watch) is
# taken out of the public signals.json; signals.json itself stays unfed (it also drives the
# live tab's IN/準備 lists and a status badge, audit 6349440798).
EVENT5_FILE = "event5_watch.json"
EVENT5_FIELDS = ("code", "ticker", "name", "score", "phase", "action", "close", "ret1", "ret5", "ret20", "rvol",
                 "theme", "theme_status", "signal_date")


def event5_view(signals: dict) -> dict:
    rows = []
    for x in (signals.get("speculative_theme_watch") or [])[:5]:
        if isinstance(x, dict):
            rows.append({k: x.get(k) for k in EVENT5_FIELDS})
    return {"updated_at": str(signals.get("updated_at") or ""), "speculative_theme_watch": rows,
            "real_submit_allowed": False, "trade_instruction": False}
# OWNER 2026-10-24 「最重要、特に昨日のザラバがセリクラとなり反転となるか」: the 下ヒゲ吸収反転 list
# (daily_capitulation_reversals) of the public signals.json is fed the same way as EVENT 5, so the
# screen no longer shows the checkout's frozen copy.
WICK_FILE = "wick_watch.json"
WICK_FIELDS = ("code", "ticker", "name", "phase", "setup", "score", "close", "fall_from_10d", "volume_ratio",
               "trigger", "stop", "target1", "target2", "reason", "signal_date")


def wick_view(signals: dict) -> dict:
    rows = []
    for x in (signals.get("daily_capitulation_reversals") or [])[:20]:
        if isinstance(x, dict):
            rows.append({k: x.get(k) for k in WICK_FIELDS})
    return {"updated_at": str(signals.get("updated_at") or ""), "daily_capitulation_reversals": rows,
            "real_submit_allowed": False, "trade_instruction": False}


# OWNER 2026-10-24 「本当に買い集めなのか」: the 大口買い集め list of the public signals.json, fed like 下ヒゲ.
ACCUMULATION_FILE = "accumulation_watch.json"


def accumulation_view(signals: dict) -> dict:
    rows = [x for x in (signals.get("large_lot_accumulation") or [])[:20] if isinstance(x, dict)]
    return {"updated_at": str(signals.get("updated_at") or ""), "large_lot_accumulation": rows,
            "large_lot_accumulation_note": str(signals.get("large_lot_accumulation_note") or ""),
            "credit_supply_updated_at": str(signals.get("credit_supply_updated_at") or ""),
            "real_submit_allowed": False, "trade_instruction": False}


DATA_MAX_BYTES = 16 * 1024 * 1024
# OWNER 2026-10-23 「検証・除外に本来地合判定がでるはず」: the daily index figures of the
# public page's 地合いサマリー, plus a reference verdict. Display only (never a gate,
# Brain score, voice or order); daily after-close data, not intraday.
# Audit 6349520576 item 3: the source "TOPIX" row is about 420 against a real TOPIX of
# about 3,998 (another series), so it is neither shown nor scored until the source is fixed.
SUMMARY_INDICES = ("日経平均", "NASDAQ", "S&P500", "SOX", "VIX", "ドル円", "米10年金利")
INDEX_FIELDS = ("price", "change_pct", "ret5", "ret20", "ma5", "ma20", "ma60", "from_ma20")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def regime_verdict(indices: dict) -> dict:
    """Reference score from daily data: Japan trend and day move, US risk appetite."""
    parts = []
    for name in ("日経平均",):   # TOPIX excluded (wrong series in the source)
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
    # Audit item 4: an unvalidated rule (thresholds not tested); shown as 未検証 and read by
    # nothing until GPT gives it a D-number.
    label = "強い" if score >= 3 else "弱い" if score <= -3 else "中立"
    return {"label": label + "（未検証）", "score": score, "parts": [{"text": t, "point": v} for t, v in parts],
            "status": "REFERENCE_DAILY_UNVALIDATED_NOT_A_GATE"}


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
            doc = json.loads(data.decode("utf-8-sig"))
            fresh = freshness(name, doc, now)
            if fresh["stale"] and name == "world_market.json" and isinstance(doc, dict):
                for row in (doc.get("rows") or {}).values():   # never shown as 表示可
                    if isinstance(row, dict):
                        row["verified"] = False
                doc["verified_count"] = 0
                data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
            temp = target / (name + ".tmp")
            temp.write_bytes(data)
            os.replace(temp, target / name)
            files[name] = dict(fresh, ok=True, bytes=len(data))
        except Exception as exc:  # keep the previous copy
            files[name] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    try:
        raw = fetch(BASE_URL + "data.json")
        if len(raw) > DATA_MAX_BYTES:
            raise ValueError("TOO_LARGE")
        data_doc = json.loads(raw.decode("utf-8-sig"))
        summary = summarize(data_doc)
        fresh = freshness("data.json", data_doc, now)
        summary["freshness"] = fresh
        if fresh["stale"]:   # a stale day is not judged
            summary["verdict"] = dict(summary["verdict"], label="古い（判定しない）", stale=True)
        temp = target / (SUMMARY_FILE + ".tmp")
        temp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")   # index order kept
        os.replace(temp, target / SUMMARY_FILE)
        files[SUMMARY_FILE] = dict(fresh, ok=True, bytes=(target / SUMMARY_FILE).stat().st_size)
    except Exception as exc:  # keep the previous copy
        files[SUMMARY_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    try:
        raw = fetch(BASE_URL + "signals.json")
        if len(raw) > MAX_BYTES:
            raise ValueError("TOO_LARGE")
        sig = json.loads(raw.decode("utf-8-sig"))
        view = event5_view(sig if isinstance(sig, dict) else {})
        fresh = freshness(EVENT5_FILE, view, now)
        temp = target / (EVENT5_FILE + ".tmp")
        temp.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target / EVENT5_FILE)
        files[EVENT5_FILE] = dict(fresh, ok=True, bytes=(target / EVENT5_FILE).stat().st_size)
    except Exception as exc:  # keep the previous copy
        files[EVENT5_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
        sig = None
    try:
        if not isinstance(sig, dict):
            raise ValueError("NO_SIGNALS")
        view = wick_view(sig)
        fresh = freshness(WICK_FILE, view, now)
        temp = target / (WICK_FILE + ".tmp")
        temp.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target / WICK_FILE)
        files[WICK_FILE] = dict(fresh, ok=True, bytes=(target / WICK_FILE).stat().st_size)
    except Exception as exc:  # keep the previous copy
        files[WICK_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    try:
        if not isinstance(sig, dict):
            raise ValueError("NO_SIGNALS")
        view = accumulation_view(sig)
        fresh = freshness(ACCUMULATION_FILE, view, now)
        temp = target / (ACCUMULATION_FILE + ".tmp")
        temp.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target / ACCUMULATION_FILE)
        files[ACCUMULATION_FILE] = dict(fresh, ok=True, bytes=(target / ACCUMULATION_FILE).stat().st_size)
    except Exception as exc:  # keep the previous copy
        files[ACCUMULATION_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    meta = {"fetched_at": now.isoformat(), "source": BASE_URL, "files": files,
            "real_submit_allowed": False, "trade_instruction": False}
    (target / META_FILE).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return meta
