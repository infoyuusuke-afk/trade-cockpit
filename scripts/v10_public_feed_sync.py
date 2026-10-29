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
import csv
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


_TARGET_MOVE = re.compile(r"([0-9][0-9,]*)円?\s*→\s*([0-9][0-9,]*)")


def grok3_broker_points(text: str) -> int:
    """OWNER 2026-10-24 「証券会社の点数」: +1 when the target-price changes 3号 lists are mostly raises
    (引き上げ, or A→B with B > A), -1 when mostly cuts, 0 for none / mixed / 見当たらず (an older change
    quoted after 見当たらず is not counted)."""
    text = str(text or "")
    if "見当たらず" in text[:24]:
        return 0
    up = text.count("引き上げ")
    down = text.count("引き下げ")
    for a, b in _TARGET_MOVE.findall(text):
        a, b = int(a.replace(",", "")), int(b.replace(",", ""))
        up, down = up + (b > a), down + (b < a)
    return (up > down) - (down > up)


def grok3_points(b: dict):
    mood = b.get("事前の空気", "").split("（")[0].strip()
    if mood not in _MOOD:
        return None
    x = b.get("Xの空気", "")[:6]
    return {"mood": _MOOD[mood], "x": 1 if x.startswith("強気") else -1 if x.startswith("弱気") else 0,
            "broker": grok3_broker_points(b.get("証券会社", ""))}


def grok3_score(b: dict):
    p = grok3_points(b)
    return None if p is None else p["mood"] + p["x"] + p["broker"]


_CHECK_KEY = "決算のあとの答え合わせ"
_VERDICTS = ("当たり", "外れ", "判定不能")


def grok3_checks(folder: Path, max_files: int = 60) -> list:
    """OWNER 2026-10-24 「答え合わせ（確認日ごと）」: 3号's after-results checks from every saved answer,
    grouped by the answer's run day (newest first) with 当たり / 外れ / 判定不能 counts. One stock counts
    once per day (a re-saved answer of the same day replaces the earlier line)."""
    files = sorted(Path(folder).glob("*.txt"), key=lambda p: p.stat().st_mtime)[-max_files:] if Path(folder).is_dir() else []
    days = {}
    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        m = _GROK_RUN.search(text)
        if not m:
            continue
        day = "%s-%s-%s" % m.groups()
        for line in text.splitlines():
            key, sep, value = line.strip().partition("：")
            if key != _CHECK_KEY or not sep:
                continue
            for part in value.split("；"):
                cm = _GROK_CODE.search(part)
                if not cm:
                    continue
                fields = [f.strip() for f in part.split("／")]
                verdict = next((w for w in _VERDICTS if w in part.split("→")[-1]), "判定不能")
                pick = lambda head: next((f[len(head):].strip() for f in fields if f.startswith(head)), "")
                days.setdefault(day, {})[cm.group(1)] = {
                    "code": cm.group(1), "name": fields[0][:40], "result": pick("結果")[:20],
                    "gap": pick("翌日の窓")[:20], "mood": pick("事前の空気").split("→")[0].strip()[:20],
                    "verdict": verdict}
    out = []
    for day in sorted(days, reverse=True)[:20]:
        items = list(days[day].values())
        out.append({"day": day[5:].replace("-", "/"), "date": day, "items": items,
                    "hit": sum(i["verdict"] == "当たり" for i in items), "miss": sum(i["verdict"] == "外れ" for i in items),
                    "unknown": sum(i["verdict"] == "判定不能" for i in items)})
    return out


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
                history.setdefault(cm.group(1), []).append((day, b, grok3_score(b), grok3_points(b)))
    cards = []
    for code, rows in history.items():
        day, b, score, points = rows[-1]
        prev = next(((d, s) for d, _, s, _ in reversed(rows[:-1]) if s is not None), None)
        cards.append({"code": code, "name": b.get("銘柄", "").split("／")[0].strip()[:40], "day": day,
                      "earnings": b.get("決算予定", "")[:60], "mood": b.get("事前の空気", "")[:120],
                      "x": b.get("Xの空気", "")[:120], "supply": b.get("需給と織り込み", "")[:120],
                      "consensus": b.get("市場予想", "")[:160], "broker": b.get("証券会社", "")[:160],
                      "score": score, "points": points, "prev_score": prev[1] if prev else None, "prev_day": prev[0] if prev else None,
                      "history": [s for _, _, s, _ in rows if s is not None][-10:]})
    cards.sort(key=lambda c: c["earnings"])
    return cards[:20]


# OWNER 2026-10-24 「決算前の値動きと出来高のヒントをPCで計算して、3号カードの横に出して」:
# daily bars of each 3号 stock (and the Nikkei 225 for comparison) are read from Yahoo's public chart
# API on this PC at most once per HINT_REFRESH_HOURS, and turned into a few numbers and plain hints.
# Display only: nothing here reaches a signal, gate, Brain score, voice or order.
HINT_CACHE = "earnings_hints_cache.json"
HINT_REFRESH_HOURS = 3
HINT_INDEX = "^N225"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=6mo&interval=1d"


def _yahoo_bars(symbol: str) -> list:
    req = urllib.request.Request(YAHOO_CHART % urllib.request.quote(symbol), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        doc = json.loads(resp.read(MAX_BYTES).decode("utf-8"))
    r = doc["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    return [(c, v or 0) for c, v in zip(q["close"], q["volume"]) if isinstance(c, (int, float))]


def price_volume_hint(bars: list, index_bars: list | None = None):
    """bars: [(close, volume), ...] oldest first. Returns the numbers and hints, or None when too short."""
    if len(bars) < 30:
        return None
    closes = [c for c, _ in bars]
    vols = [v for _, v in bars]
    last = closes[-1]
    ret = lambda n, xs=closes: round((xs[-1] / xs[-1 - n] - 1) * 100, 1) if len(xs) > n and xs[-1 - n] else None
    base = vols[-65:-5] if len(vols) >= 35 else vols[:-5]
    base_avg = sum(base) / len(base) if base else 0
    vol_ratio = round(sum(vols[-5:]) / 5 / base_avg, 2) if base_avg else None
    ma25 = sum(closes[-25:]) / 25
    # share of the last 10 days' volume on up days, among up and down days (unchanged days left out)
    up_vol = sum(v for i, v in enumerate(vols[-10:], len(vols) - 10) if closes[i] > closes[i - 1])
    down_vol = sum(v for i, v in enumerate(vols[-10:], len(vols) - 10) if closes[i] < closes[i - 1])
    up_share = round(up_vol / (up_vol + down_vol), 2) if up_vol + down_vol else None
    ret5, ret20 = ret(5), ret(20)
    idx20 = ret(20, [c for c, _ in index_bars]) if index_bars and len(index_bars) > 20 else None
    rel20 = round(ret20 - idx20, 1) if ret20 is not None and idx20 is not None else None
    high = max(closes[-120:])
    hints = []
    if vol_ratio is not None and vol_ratio >= 1.5:
        if ret5 is not None and ret5 >= 3:
            hints.append(("warn", "出来高を伴って上昇（期待で買われている。織り込みに注意）"))
        elif ret5 is not None and ret5 <= -3:
            hints.append(("bad", "出来高を伴って下落（売られている。悪い話の先回りかも）"))
        else:
            hints.append(("warn", "値段は動かず出来高だけ増加（誰かが先回りしているかも。要注目）"))
    elif vol_ratio is not None and vol_ratio <= 0.7 and ret20 is not None and ret20 <= -5:
        hints.append(("good", "出来高が細りながら下落（売り枯れ気味）"))
    if up_share is not None and up_share >= 0.65:
        hints.append(("good", "上げた日の出来高が多い（買い集めの気配）"))
    elif up_share is not None and up_share <= 0.35:
        hints.append(("bad", "下げた日の出来高が多い（売り抜けの気配）"))
    if rel20 is not None and rel20 >= 8:
        hints.append(("warn", "日経平均より強い（20日で%+.1f%%）" % rel20))
    elif rel20 is not None and rel20 <= -8:
        hints.append(("bad", "日経平均より弱い（20日で%+.1f%%）" % rel20))
    if not hints:
        hints.append(("", "目立つ動きなし"))
    return {"close": round(last, 1), "ret5": ret5, "ret20": ret20, "rel20": rel20, "vol_ratio": vol_ratio,
            "up_vol_share": up_share, "from_ma25": round((last / ma25 - 1) * 100, 1),
            "from_high": round((last / high - 1) * 100, 1), "hints": [{"tone": t, "text": x} for t, x in hints]}


def attach_hints(view: dict, cache_dir: Path, now: datetime, bars_fetch=_yahoo_bars) -> None:
    """Adds card["pv"] to each 3号 card from the cache, refreshing codes older than HINT_REFRESH_HOURS."""
    cards = [c for b in view.get("bots", []) for c in (b.get("preview_cards") or [])]
    if not cards:
        return
    path = Path(cache_dir) / HINT_CACHE
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    fresh = lambda e: isinstance(e, dict) and (now - datetime.fromisoformat(e.get("at", "2000-01-01T00:00:00+00:00"))).total_seconds() < HINT_REFRESH_HOURS * 3600
    index_bars = None
    for c in cards:
        code = c["code"]
        if not fresh(cache.get(code)):
            try:
                if index_bars is None:
                    index_bars = bars_fetch(HINT_INDEX)
                cache[code] = {"at": now.isoformat(), "hint": price_volume_hint(bars_fetch(code + ".T"), index_bars)}
            except Exception as exc:  # keep the previous numbers, if any
                cache.setdefault(code, {"at": now.isoformat(), "hint": None, "error": type(exc).__name__})
        c["pv"] = (cache.get(code) or {}).get("hint")
        c["pv_at"] = (cache.get(code) or {}).get("at")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


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
                     "preview_cards": grok3_cards(Path(root) / folder) if folder == "Grok3号" else [],
                     "checks": grok3_checks(Path(root) / folder) if folder == "Grok3号" else []})
        latest = saved if latest is None or saved > latest else latest
    return {"updated_at": latest.isoformat() if latest else "", "bots": bots, "tags": grok_tags(bots),
            "real_submit_allowed": False, "trade_instruction": False}


# OWNER 2026-10-27 「AIコクピットの成績が一目で分かるように…各アナリスト別」: the GPT analysts' answers the
# cockpit logged (records/<day>/manual_notes.csv) and their scores (manual_notes_outcomes.csv: 強気 hits when the
# close is above the price when the note was seen, 弱気 when below; 監視 is counted but never scored).
# Display only. Returns per analyst: answers, scored count, hits, hit rate and the average move in the view's direction.
ANALYST_FILE = "analyst_scores.json"
ANALYST_NAMES = {"pre_next": "PRE-NEXT", "supply_sq": "需給", "premarket": "寄り前", "revenue_hunter": "Revenue Hunter"}


def _csv_num(v):
    """A positive number from a CSV cell (text), else None."""
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def analyst_view(records_root: Path, now: datetime) -> dict:
    stats = {}
    days = sorted(p for p in Path(records_root).glob("*") if p.is_dir()) if Path(records_root).is_dir() else []
    for day in days:
        for name, kind in (("manual_notes.csv", "log"), ("manual_notes_outcomes.csv", "out")):
            path = day / name
            if not path.is_file():
                continue
            with open(path, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f):
                    if r.get("source") != "gpt":
                        continue
                    s = stats.setdefault(ANALYST_NAMES.get(r.get("role"), r.get("role") or "?"),
                                         {"answers": 0, "watch": 0, "scored": 0, "hits": 0, "sum_pct": 0.0, "days": set()})
                    if kind == "log":
                        s["answers"] += 1
                        s["watch"] += r.get("view") == "監視"
                        s["days"].add(day.name)
                        continue
                    side = {"強気": 1, "弱気": -1}.get(r.get("view"))
                    seen, close = _csv_num(r.get("price_at_seen")), _csv_num(r.get("price_close"))
                    if side and seen and close:
                        move = side * (close / seen - 1) * 100
                        s["scored"] += 1
                        s["hits"] += move > 0
                        s["sum_pct"] += move
    rows = [{"name": k, "answers": v["answers"], "watch": v["watch"], "days": len(v["days"]), "scored": v["scored"],
             "hits": v["hits"], "hit_rate_pct": round(v["hits"] / v["scored"] * 100, 1) if v["scored"] else None,
             "avg_move_pct": round(v["sum_pct"] / v["scored"], 3) if v["scored"] else None}
            for k, v in sorted(stats.items())]
    return {"updated_at": now.isoformat(), "basis": "強気/弱気の答えを、コクピットが答えを見た時の値段から大引けまでで採点（費用なし・向きだけ）",
            "analysts": rows, "real_submit_allowed": False, "trade_instruction": False}


# OWNER 2026-10-26 「ドル円をMS2から取って連動を出して。表示と記録だけで、サインには使わない」:
# today's USD/JPY (key USDJPY in records/<day>/futures_index.csv, from MS2 RssFXMarket) beside the Nikkei
# 225 mini future (N225MF) and Kioxia (285A.T in market_snapshots.csv): the last price of each minute in
# the session, and the correlation of their 1-minute changes over the last 30 minutes and the whole day.
# Display only: nothing here reaches a signal, gate, Brain score, voice or order.
FX_KEY, FX_PEERS = "USDJPY", (("N225MF", "日経225ミニ"), ("285A.T", "キオクシアHD（285A）"))
FX_MIN_POINTS = 10
FX_RECENT_MINUTES = 30


def _minute_series(path: Path, key_field: str, keys: set, ok_field: str | None = None) -> dict:
    out = {k: {} for k in keys}
    if not path.is_file():
        return out
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            k = row.get(key_field)
            if k not in keys or (ok_field and row.get(ok_field) != "OK"):
                continue
            minute = str(row.get("captured_at") or "").replace("T", " ")[11:16]
            try:
                price = float(row.get("price") or "")
            except ValueError:
                continue
            if price > 0 and ("09:00" <= minute < "11:31" or "12:30" <= minute < "15:31"):
                out[k][minute] = price
    return out


def _corr(xs: list, ys: list):
    n = len(xs)
    if n < FX_MIN_POINTS:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (vx * vy) ** 0.5, 2)


def fx_link(records_root: Path, now: datetime) -> dict:
    day = now.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    folder = Path(records_root) / day
    fut = _minute_series(folder / "futures_index.csv", "key", {FX_KEY, "N225MF"}, ok_field="status")
    stock = _minute_series(folder / "market_snapshots.csv", "ticker", {"285A.T"})
    series = {FX_KEY: fut[FX_KEY], "N225MF": fut["N225MF"], "285A.T": stock["285A.T"]}
    fx = series[FX_KEY]
    view = {"date": day, "display_only": True, "trade_instruction": False, "real_submit_allowed": False,
            "usdjpy": None, "usdjpy_at": None, "points": len(fx), "peers": []}
    if not fx:
        view["state"] = "NO_DATA"
        return view
    last = max(fx)
    view.update(state="OK", usdjpy=fx[last], usdjpy_at=last)
    for key, label in FX_PEERS:
        peer = series[key]
        minutes = sorted(set(fx) & set(peer))
        steps = [(m, (fx[m] / fx[p] - 1), (peer[m] / peer[p] - 1)) for p, m in zip(minutes, minutes[1:])]
        recent = steps[-FX_RECENT_MINUTES:]
        view["peers"].append({"key": key, "label": label, "n_today": len(steps),
                              "corr_today": _corr([a for _, a, _ in steps], [b for _, _, b in steps]),
                              "n_recent": len(recent),
                              "corr_recent": _corr([a for _, a, _ in recent], [b for _, _, b in recent])})
    return view


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


def sync(target: Path, *, fetch=_download, now: datetime | None = None, grok_root: Path | None = None, bars_fetch=None,
         records_root: Path | None = None) -> dict:
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
        try:   # OWNER 2026-10-26: USD/JPY link, display only
            summary["fx_link"] = fx_link(Path(records_root) if records_root is not None else Path(target).parent / "records",
                                         now)
        except Exception as exc:
            summary["fx_link"] = {"state": "UNAVAILABLE", "reason": type(exc).__name__}
        # OWNER 2026-10-24 「完全照合の日付」: the header line showed the pinned 10/20 copy. Only the
        # counts, status and time of main's live_focus.json are copied (display only; the voice
        # switch stays on the local file, audit 6349440798).
        try:
            lf = json.loads(fetch(BASE_URL + "live_focus.json").decode("utf-8-sig"))
            if isinstance(lf, dict) and isinstance(lf.get("verified_count"), int) and isinstance(lf.get("expected_count"), int):
                summary["live_check"] = {"verified_count": lf["verified_count"], "expected_count": lf["expected_count"],
                                         "status": str(lf.get("status") or "")[:20], "updated_at": str(lf.get("updated_at") or "")[:30]}
        except Exception:
            pass
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
        try:
            attach_hints(view, target, now, bars_fetch if bars_fetch is not None else _yahoo_bars)
        except Exception:
            pass
        fresh = freshness(GROK_FILE, view, now) if view["updated_at"] else {"stale": True, "reason": "NO_ANSWER"}
        temp = target / (GROK_FILE + ".tmp")
        temp.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target / GROK_FILE)
        files[GROK_FILE] = dict(fresh, ok=True, bytes=(target / GROK_FILE).stat().st_size)
    except Exception as exc:  # keep the previous copy
        files[GROK_FILE] = {"ok": False, "reason": type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)[:40]}
    try:   # OWNER 2026-10-27: analyst scores for the CONTROL results panel (display only)
        view = analyst_view(Path(records_root) if records_root is not None else Path(target).parent / "records", now)
        temp = target / (ANALYST_FILE + ".tmp")
        temp.write_text(json.dumps(view, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, target / ANALYST_FILE)
        files[ANALYST_FILE] = {"ok": True, "stale": False, "bytes": (target / ANALYST_FILE).stat().st_size}
    except Exception as exc:  # keep the previous copy
        files[ANALYST_FILE] = {"ok": False, "reason": type(exc).__name__}
    meta = {"fetched_at": now.isoformat(), "source": BASE_URL, "files": files,
            "real_submit_allowed": False, "trade_instruction": False}
    (target / META_FILE).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
    return meta
