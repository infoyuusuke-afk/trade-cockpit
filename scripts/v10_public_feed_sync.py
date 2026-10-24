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
STALE_HOURS = {"weekly_review.json": 24 * 8, "grok_bots.json": 36}
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


# OWNER 2026-10-24 「Grokの答えをコクピットで読む機能」: the latest answer of Grok 1号・2号・3号 that the
# OWNER saved with the 5番 button (Desktop\Claudeブレイン\Grok1号 ... Grok3号). Read only, this PC only;
# shown for reading, never a score, gate, voice or order.
GROK_FILE = "grok_bots.json"
GROK_BOTS = (("Grok1号", "1号 朝夕ニュース巡回"), ("Grok2号", "2号 好決算監視"), ("Grok3号", "3号 決算前監視"))
GROK_TEXT_MAX = 20000
GROK2_FIELDS = ("銘柄", "決算発表日", "動きの型", "判断案", "目安の価格帯", "無効になる条件", "見直す日", "自信")


def grok_default_root() -> Path:
    return Path.home() / "Desktop" / "Claudeブレイン"


def grok_cards(text: str) -> list:
    """2号: one card per 銘柄 (a new card starts at each 「銘柄：」 line; fields after the full-width colon)."""
    cards, fields = [], None
    for line in text.splitlines():
        key, sep, value = line.strip().partition("：")
        if not sep or key not in GROK2_FIELDS:
            continue
        if key == GROK2_FIELDS[0]:
            fields = {}
            cards.append(fields)
        if fields is not None and key not in fields:
            fields[key] = value.strip()[:200]
    return [c for c in cards if "判断案" in c][:15]


_GROK_CODE = re.compile(r"[（(]([0-9][0-9A-Z]{3})[）)]")
_GROK_RUN = re.compile(r"実行日時：\s*(\d{4})-(\d{2})-(\d{2})")


def grok_tags(bots: list) -> dict:
    """OWNER 2026-10-24 「決算日程にGrokをつなぐ」: per stock code, the labels the earnings calendar shows —
    2号's 判断案, 3号's 事前の空気 and the after-results check (当たり/外れ/判定不能), each with its date."""
    tags = {}

    def add(code, bot, kind, label, day):
        if code and label:
            tags.setdefault(code, []).append({"bot": bot, "kind": kind, "label": label[:40], "day": day})

    for b in bots:
        text = b.get("text") or ""
        m = _GROK_RUN.search(text)
        day = "%s/%s" % (m.group(2), m.group(3)) if m else str(b.get("saved_at") or "")[5:10].replace("-", "/")
        if b.get("bot") == "Grok2号":
            for c in b.get("cards") or []:
                cm = _GROK_CODE.search(c.get("銘柄", ""))
                add(cm.group(1) if cm else None, "2号", "決算後", c.get("判断案", "").split("（")[0], day)
        if b.get("bot") == "Grok3号":
            code = None
            for line in text.splitlines():
                key, sep, value = line.strip().partition("：")
                if not sep:
                    continue
                if key == "銘柄":
                    cm = _GROK_CODE.search(value)
                    code = cm.group(1) if cm else None
                elif key == "事前の空気":
                    add(code, "3号", "決算前", value.split("（")[0].strip(), day)
                elif key == "決算のあとの答え合わせ":
                    cm = _GROK_CODE.search(value)
                    verdict = next((w for w in ("当たり", "外れ", "判定不能") if w in value.split("→")[-1]), "")
                    add(cm.group(1) if cm else None, "3号", "答え合わせ", verdict, day)
    return tags


# OWNER 2026-10-24 「文字なのか　カードタイプで点数バロメーター付きで日々の上下が一目でわかるようにして」:
# 3号's answers as one card per stock with a 期待の強さ score (-4..+4) and its change from the previous answer.
# The score only summarises 3号's own words (a record of market mood, not a buy/sell signal):
# 事前の空気 期待先行 +2 / 中立 0 / 警戒 -2 (材料不足: no score), Xの空気 強気 +1 / 弱気 -1,
# 証券会社 目標株価の引き上げ +1 / 引き下げ -1.
GROK3_FIELDS = ("銘柄", "決算予定", "市場予想", "証券会社", "Xの空気", "需給と織り込み", "事前の空気")
_MOOD = {"期待先行": 2, "中立": 0, "警戒": -2}


def grok3_blocks(text: str) -> list:
    blocks, cur = [], None
    for line in text.splitlines():
        key, sep, value = line.strip().partition("：")
        if not sep or key not in GROK3_FIELDS:
            continue
        if key == "銘柄":
            cur = {}
            blocks.append(cur)
        if cur is not None and key not in cur:
            cur[key] = value.strip()
    return [b for b in blocks if "事前の空気" in b]


def grok3_score(b: dict):
    mood = b.get("事前の空気", "").split("（")[0].strip()
    if mood not in _MOOD:
        return None
    x = b.get("Xの空気", "")[:6]
    broker = b.get("証券会社", "")
    return (_MOOD[mood] + (1 if x.startswith("強気") else -1 if x.startswith("弱気") else 0)
            + (1 if "引き上げ" in broker else 0) - (1 if "引き下げ" in broker else 0))


def grok3_cards(folder: Path, max_files: int = 30) -> list:
    files = sorted(Path(folder).glob("*.txt"), key=lambda p: p.stat().st_mtime)[-max_files:] if Path(folder).is_dir() else []
    history = {}
    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        m = _GROK_RUN.search(text)
        day = "%s/%s" % (m.group(2), m.group(3)) if m else ""
        for b in grok3_blocks(text):
            cm = _GROK_CODE.search(b.get("銘柄", ""))
            if cm:
                history.setdefault(cm.group(1), []).append((day, b, grok3_score(b)))
    cards = []
    for code, rows in history.items():
        day, b, score = rows[-1]
        prev = next(((d, s) for d, _, s in reversed(rows[:-1]) if s is not None), None)
        cards.append({"code": code, "name": b.get("銘柄", "").split("／")[0].strip()[:40], "day": day,
                      "earnings": b.get("決算予定", "")[:60], "mood": b.get("事前の空気", "")[:120],
                      "x": b.get("Xの空気", "")[:120], "supply": b.get("需給と織り込み", "")[:120],
                      "consensus": b.get("市場予想", "")[:160], "broker": b.get("証券会社", "")[:160],
                      "score": score, "prev_score": prev[1] if prev else None, "prev_day": prev[0] if prev else None,
                      "history": [s for _, _, s in rows if s is not None][-10:]})
    cards.sort(key=lambda c: c["earnings"])
    return cards[:20]


def grok_bots_view(root: Path) -> dict:
    bots, latest = [], None
    for folder, label in GROK_BOTS:
        files = sorted((Path(root) / folder).glob("*.txt"), key=lambda p: p.stat().st_mtime) if (Path(root) / folder).is_dir() else []
        if not files:
            bots.append({"bot": folder, "label": label, "file": None, "saved_at": None, "text": "", "cards": []})
            continue
        path = files[-1]
        saved = datetime.fromtimestamp(path.stat().st_mtime, timezone(timedelta(hours=9)))
        text = path.read_text(encoding="utf-8-sig", errors="replace")[:GROK_TEXT_MAX]
        bots.append({"bot": folder, "label": label, "file": path.name, "saved_at": saved.isoformat(),
                     "text": text, "cards": grok_cards(text) if folder == "Grok2号" else [],
                     "preview_cards": grok3_cards(Path(root) / folder) if folder == "Grok3号" else []})
        latest = saved if latest is None or saved > latest else latest
    return {"updated_at": latest.isoformat() if latest else "", "bots": bots, "tags": grok_tags(bots),
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


def yield_points(level, change_pct):
    """A yield's move in percentage points from its level and its percent change."""
    level, change_pct = _num(level), _num(change_pct)
    if level is None or change_pct is None or change_pct == -100:
        return None
    return round(level - level / (1 + change_pct / 100), 2)


def edition_name(phase: str, updated_at: str) -> str:
    """OWNER 2026-10-24: a run after the close (e.g. 21:01) is not the 15:00 pre-close edition."""
    m = re.search(r"(\d{2}):(\d{2})", updated_at[11:16] if len(updated_at) >= 16 else "")
    if phase == "引け前持ち越し15:00版" and m and (int(m.group(1)), int(m.group(2))) >= (15, 30):
        return "大引け後版（%s作成）" % m.group(0)
    return phase


def summarize(data: dict) -> dict:
    indices = {}
    for name in SUMMARY_INDICES:
        r = (data.get("indices") or {}).get(name) or {}
        if r.get("ok") is True:
            indices[name] = {k: _num(r.get(k)) for k in INDEX_FIELDS}
            if "金利" in name:
                # OWNER 2026-10-24: yields are shown in percentage points (4.95%, -0.19 points)
                x = indices[name]
                x["unit"] = "yield"
                x["change_pt"] = yield_points(x.get("price"), x.get("change_pct"))
                x["ret5_pt"] = yield_points(x.get("price"), x.get("ret5"))
                x["from_ma20_pt"] = (round(x["price"] - x["ma20"], 2)
                                     if x.get("price") is not None and x.get("ma20") is not None else None)
    themes = []
    for row in (data.get("themes") or [])[:5]:
        try:
            name, score, count, members = row
            themes.append({"name": str(name), "score": _num(score), "count": count,
                           "members": [{"name": str(m[0]), "score": _num(m[1]), "change_pct": _num(m[2])}
                                       for m in members[:3]]})
        except (TypeError, ValueError, IndexError):
            continue
    updated_at = str(data.get("updated_at") or "")
    return {"updated_at": updated_at, "phase": edition_name(str(data.get("phase") or ""), updated_at),
            "indices": indices, "verdict": regime_verdict(indices), "themes": themes,
            "real_submit_allowed": False, "trade_instruction": False}


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trade-cockpit-v10-public-feed"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        data = resp.read(MAX_BYTES + 1)
    return data


def sync(target: Path, *, fetch=_download, now: datetime | None = None, grok_root: Path | None = None) -> dict:
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
    try:
        root = Path(grok_root) if grok_root is not None else grok_default_root()
        if not root.is_dir():
            raise ValueError("NO_GROK_FOLDER")
        view = grok_bots_view(root)
        fresh = freshness(GROK_FILE, view, now) if view["updated_at"] else {"stale": True, "reason": "NO_ANSWER"}
        temp = target / (GROK_FILE + ".tmp")
        temp.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target / GROK_FILE)
        files[GROK_FILE] = dict(fresh, ok=True, bytes=(target / GROK_FILE).stat().st_size)
    except Exception as exc:  # keep the previous copy
        files[GROK_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    meta = {"fetched_at": now.isoformat(), "source": BASE_URL, "files": files,
            "real_submit_allowed": False, "trade_instruction": False}
    (target / META_FILE).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return meta
