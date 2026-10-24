"""Hand-delivered notes: Grok's X topics and, as a backup, the GPT analysts (no API, no cost).

OWNER 2026-10-23:
- 「決まったフォルダに貼ったGrokの答え（銘柄コード・話題の強さ・強気/弱気・理由・投稿URL・時刻）を
  コクピットが読み、期限と出典を確かめて、ブレインと注目欄に『X話題』として出す。最初は売買の点数は
  変えず、当たり外れを記録する。有料のAPIは使わない」
- 「GPTアナリスト4人（寄り前・PRE-NEXT・需給・Revenue Hunter）の答えを手で取り込めるようにして。
  自動実行が失敗した時だけ使う予備。画面には『手動』と付け、売買の点数は変えない」

The OWNER pastes an answer as a text file into RuntimeDir/grok_inbox or
RuntimeDir/analyst_inbox (or uses the desktop button, which saves the clipboard there and
runs ``--check``). Only the fixed line formats below are read; the text is untrusted data,
every field is length-limited and nothing in it is followed.

    GROK_NOTE_V2
    285A | 強 | 弱気 | 理由（120文字まで） | https://x.com/... | 2026-10-23 07:40
    END

    GPT_ANALYST_NOTE_V1
    寄り前 | 285A | 監視 | 理由 | https://... | 2026-10-23 08:20
    END

A row needs a 4-character code (Revenue Hunter may use "-"), a known strength / view, a
reason, at least one https source and a posting time that is not in the future; it is valid
for 8 hours from that time, the same day only. A GPT analyst row is used only when that
slot's automatic run (08:30 before 12:15, 12:15 after) has not delivered its report.

Rows become Brain flags (never a score, gate or order; Revenue Hunter is not a market lane
and only listed) and are logged once to records/<day>/manual_notes.csv. After the close
(or at the next start) each logged row with a view is scored on that day's ticks at +30 min,
+60 min and the close: 強気 is a hit when the price rose, 弱気 when it fell (no costs, the
direction only) -> records/<day>/manual_notes_outcomes.csv.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys

JST = timezone(timedelta(hours=9))
GROK_DIR = "grok_inbox"
ANALYST_DIR = "analyst_inbox"
LOG_FILE = "manual_notes.csv"
OUTCOME_FILE = "manual_notes_outcomes.csv"
LOG_FIELDS = ["seen_at", "source", "role", "note", "posted_at", "code", "name", "strength", "view", "reason",
              "sources", "in_universe"]
OUTCOME_FIELDS = LOG_FIELDS + ["price_at_seen", "price_30m", "price_60m", "price_close", "hit_30m", "hit_60m",
                               "hit_close"]
GROK_HEADER = "GROK_NOTE_V2"
GPT_HEADER = "GPT_ANALYST_NOTE_V1"
STRENGTHS = ("強", "中", "弱")
GROK_VIEWS = ("強気", "弱気")
GPT_VIEWS = ("強気", "弱気", "監視")
ANALYSTS = {"寄り前": "premarket", "PRE-NEXT": "pre_next", "需給": "supply_sq", "Revenue Hunter": "revenue_hunter"}
MARKET_ROLES = ("premarket", "pre_next", "supply_sq")
MAX_FILE_BYTES = 65_536
MAX_FILES = 30
MAX_ROWS = 30
MAX_REASON = 120
MAX_SOURCES = 3
VALID_FOR = timedelta(hours=8)
FUTURE_SLACK = timedelta(minutes=5)
SLOT_SPLIT = "12:15"
CODE = re.compile(r"^[0-9][0-9A-Z]{3}$")
URL = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?$")
POSTED = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def _body(text: str, header: str):
    lines = [x.strip() for x in str(text or "").replace("\r\n", "\n").split("\n")]
    try:
        start = lines.index(header)
        end = lines.index("END", start)
    except ValueError:
        return None
    return [x for x in lines[start + 1:end] if x]


def _posted(raw: str, local: datetime):
    if not POSTED.match(raw):
        return None, "時刻は YYYY-MM-DD HH:MM で書く"
    try:
        at = datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except ValueError:
        return None, "時刻が読めません"
    if at > local + FUTURE_SLACK:
        return None, "未来の時刻です"
    if local >= min(at + VALID_FOR, at.replace(hour=23, minute=59)):
        return None, "期限切れ（投稿から8時間・その日のうち）"
    return at, None


def parse(text: str, *, now: datetime) -> dict:
    """Rows of one pasted answer (Grok or GPT analyst) or ok=False with the reason. Never raises."""
    local = now.astimezone(JST)
    kind, body = "grok", _body(text, GROK_HEADER)
    if body is None:
        kind, body = "gpt", _body(text, GPT_HEADER)
    if body is None:
        return {"ok": False, "kind": None, "reason": "形式が違います（GROK_NOTE_V2 か GPT_ANALYST_NOTE_V1 と END の行が必要）",
                "items": [], "rejected": []}
    items, rejected, seen = [], [], set()
    for n, line in enumerate(body, start=1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 6:
            rejected.append({"row": n, "reason": "区切り（|）が6つの欄になっていません"})
            continue
        if kind == "grok":
            code, strength, view, reason, sources, posted = parts
            role, bad = "grok", (None if strength in STRENGTHS else "話題の強さは 強・中・弱 のどれか")
            bad = bad or (None if view in GROK_VIEWS else "強気か弱気のどちらか")
        else:
            analyst, code, view, reason, sources, posted = parts
            role, strength = ANALYSTS.get(analyst), ""
            bad = None if role else "アナリスト名は 寄り前・PRE-NEXT・需給・Revenue Hunter のどれか"
            bad = bad or (None if view in GPT_VIEWS else "強気・弱気・監視のどれか")
        code = code.upper()
        urls = [u for u in sources.split() if URL.match(u)][:MAX_SOURCES]
        if bad is None and not (CODE.match(code) or (role == "revenue_hunter" and code == "-")):
            bad = "銘柄コードが4文字ではありません"
        if bad is None and not reason:
            bad = "理由がありません"
        if bad is None and not urls:
            bad = "出典（https のURL）がありません"
        at = None
        if bad is None:
            at, bad = _posted(posted, local)
        if bad is None and (role, code) in seen:
            bad = "同じ銘柄が2回あります"
        if bad:
            rejected.append({"row": n, "code": code[:8], "reason": bad})
            continue
        seen.add((role, code))
        items.append({"role": role, "code": code, "strength": strength, "view": view, "reason": reason[:MAX_REASON],
                      "sources": urls, "posted_at": at.isoformat(),
                      "valid_until": min(at + VALID_FOR, at.replace(hour=23, minute=59)).isoformat()})
        if len(items) >= MAX_ROWS:
            break
    if not items:
        return {"ok": False, "kind": kind, "reason": "使える行がありません", "items": [], "rejected": rejected}
    return {"ok": True, "kind": kind, "items": items, "rejected": rejected}


def _auto_delivered(inbox, day: str, slot: str) -> bool:
    """True when that slot's automatic research envelope reached the private inbox."""
    if not inbox:
        return False
    try:
        return (Path(inbox) / ("agent_research_sched_%s_%s.json" % (day.replace("-", ""), slot))).is_file()
    except OSError:
        return False


def _files(folder: Path) -> list:
    try:
        files = [p for p in folder.glob("*.txt") if p.is_file() and not p.is_symlink()]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_FILES]


def load(runtime: Path, *, now: datetime, known: dict, agent_inbox=None, logged: set | None = None) -> dict:
    """Valid rows of both inboxes, newest file first. known: code -> name of the watched universe.
    Returns the screen view, code -> [Brain watch entries] and the backup analysts per role."""
    runtime = Path(runtime)
    local = now.astimezone(JST)
    day = local.date().isoformat()
    notes, attention, analysts, refused = [], {}, {}, []
    for folder in (runtime / GROK_DIR, runtime / ANALYST_DIR):
        for path in _files(folder):
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
                got = parse(path.read_text(encoding="utf-8-sig", errors="replace"), now=now)
            except OSError:
                continue
            if not got["ok"]:
                continue
            for item in got["items"]:
                if item["posted_at"][:10] != day:
                    continue
                if got["kind"] == "gpt":
                    slot = "0830" if item["posted_at"][11:16] < SLOT_SPLIT else "1215"
                    if _auto_delivered(agent_inbox, day, slot):
                        refused.append({"note": path.name, "role": item["role"], "code": item["code"],
                                        "reason": "自動のレポートが届いているので使いません"})
                        continue
                inside = item["code"] in known
                row = dict(item, source=got["kind"], note=path.name, name=known.get(item["code"]) or "", in_universe=inside)
                notes.append(row)
                if got["kind"] == "gpt":
                    analysts.setdefault(item["role"], []).append(row)
                if inside and item["role"] in ("grok",) + MARKET_ROLES:
                    attention.setdefault(item["code"], [])
                    if not any(x["role"] == item["role"] for x in attention[item["code"]]):   # the newest file wins
                        attention[item["code"]].append({"role": item["role"] if got["kind"] == "grok" else "manual_" + item["role"],
                                                        "report_id": path.name, "expires_at": item["valid_until"],
                                                        "stance": item["view"], "strength": item["strength"],
                                                        "summary": item["reason"]})
    if logged is not None:
        _log(runtime / "records", notes, now=now, logged=logged)
    notes.sort(key=lambda r: r["posted_at"], reverse=True)
    view = {"notes": notes[:40], "refused": refused[:20], "status": "MANUAL_WATCH_ONLY_NOT_A_SCORE"}
    return {"view": view, "attention": attention, "analysts": analysts}


def _log(records: Path, notes: list, *, now: datetime, logged: set) -> int:
    local = now.astimezone(JST)
    path = Path(records) / local.date().isoformat() / LOG_FILE
    if not logged and path.is_file():
        with open(path, newline="", encoding="utf-8-sig") as f:
            logged.update((r.get("note"), r.get("role"), r.get("code")) for r in csv.DictReader(f))
    new = []
    for r in notes:
        key = (r["note"], r["role"], r["code"])
        if key in logged:
            continue
        logged.add(key)
        new.append({"seen_at": local.strftime("%Y-%m-%d %H:%M:%S"), "source": r["source"], "role": r["role"],
                    "note": r["note"], "posted_at": r["posted_at"], "code": r["code"], "name": r["name"],
                    "strength": r["strength"], "view": r["view"], "reason": r["reason"],
                    "sources": " ".join(r["sources"]), "in_universe": r["in_universe"]})
    if not new:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if first:
            w.writeheader()
        w.writerows(new)
    return len(new)


def score_day(day_dir: Path, *, ev) -> int:
    """Hit or miss of each logged row with a view, on that day's ticks (pinned EV loader)."""
    day_dir = Path(day_dir)
    log, out = day_dir / LOG_FILE, day_dir / OUTCOME_FILE
    if not log.is_file() or out.is_file():
        return 0
    with open(log, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    ticks = ev.load_ticks(day_dir / "ticks.csv")

    def price_at(series, hhmmss, before=False):
        if before:
            got = [p for t, _, p in series if t <= hhmmss]
            return got[-1] if got else None
        return next((p for t, _, p in series if t >= hhmmss), None)

    scored = []
    for r in rows:
        series = ticks.get(r["code"] + ".T", [])
        side = {"強気": 1, "弱気": -1}.get(r.get("view"))
        seen = str(r.get("seen_at", ""))[11:19]
        p0 = price_at(series, max(seen, "09:00:00"))
        res = dict(r, price_at_seen=p0 or "")
        for label, minutes in (("30m", 30), ("60m", 60)):
            try:
                t = (datetime.strptime(max(seen, "09:00:00"), "%H:%M:%S") + timedelta(minutes=minutes)).strftime("%H:%M:%S")
            except ValueError:
                t = None
            p = price_at(series, t, before=True) if t and t <= "15:30:00" else None
            res["price_" + label] = p or ""
            res["hit_" + label] = "" if not (side and p and p0) else ("当たり" if side * (p / p0 - 1) > 0 else "外れ")
        pc = price_at(series, "15:30:00", before=True)
        res["price_close"] = pc or ""
        res["hit_close"] = "" if not (side and pc and p0) else ("当たり" if side * (pc / p0 - 1) > 0 else "外れ")
        scored.append(res)
    temp = out.with_name(out.name + ".tmp")
    with open(temp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=OUTCOME_FIELDS)
        w.writeheader()
        w.writerows(scored)
    os.replace(temp, out)
    return len(scored)


def check_file(path: str) -> int:
    """The desktop button's check: prints the result in Japanese, exit 0 when usable."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        print("NG：ファイルが読めません")
        return 2
    if len(raw) > MAX_FILE_BYTES:
        print("NG：大きすぎます（64KBまで）")
        return 2
    got = parse(raw.decode("utf-8-sig", errors="replace"), now=datetime.now(timezone.utc))
    if not got["ok"]:
        print("NG：" + got["reason"])
    else:
        until = min(x["valid_until"] for x in got["items"])[11:16]
        print("OK：%d件を受け取りました（早いものは%sまで有効）。ブレインが次の判定で読み込みます。" % (len(got["items"]), until))
        for x in got["items"]:
            print("  %s %s %s %s" % (x["code"], x["strength"] or x["role"], x["view"], x["reason"]))
    for r in got["rejected"]:
        print("  使わなかった行 %d：%s" % (r["row"], r["reason"]))
    return 0 if got["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        sys.exit(check_file(sys.argv[2]))
    print(json.dumps({"usage": "v10_manual_notes.py --check <file>"}))
    sys.exit(2)
