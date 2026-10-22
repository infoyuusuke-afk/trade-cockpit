"""Grok notes handed over by the OWNER by hand (no API, no cost; display and Brain flags only).

OWNER 2026-10-23 「自動連係については保留、まずは手動で連携できる形でgrokの情報をAIコクピットに渡し、
ブレインに総合判断させるようにAIコクピットを改修する」.

The OWNER asks Grok (in Cursor) with the prompt in docs/GROK_MANUAL_PROMPT.md, copies the
answer and runs the desktop button, which saves the clipboard as
RuntimeDir/grok_inbox/grok_<yyyyMMdd_HHmmss_fff>.txt and checks it with ``--check``. The Brain observer
reads the inbox every pass: each valid row (4-character code, stance, summary, at least
one https source) becomes a Brain flag on that issue and is listed on the screen. Like the
other specialists, Grok watches and the Brain decides: a note never changes a score, a
gate or an order (real_submit_allowed stays false). Each row is logged once to
records/<day>/grok_notes.csv so its later outcome can be measured.

Grok's text is untrusted data: only the fixed line format below is read, every field is
length-limited, and nothing in it is executed or followed.

    GROK_NOTE_V1
    as_of: 2026-10-23 07:40
    285A | 悪材料 | 要約（120文字まで） | https://x.com/... https://...
    END
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

JST = timezone(timedelta(hours=9))
INBOX_DIR = "grok_inbox"
NOTES_FILE = "grok_notes.csv"
NOTE_FIELDS = ["seen_at", "note", "as_of", "code", "name", "stance", "summary", "sources", "in_universe"]
HEADER = "GROK_NOTE_V1"
STANCES = ("好材料", "悪材料", "話題", "噂")
MAX_FILE_BYTES = 65_536
MAX_FILES = 20
MAX_ROWS = 30
MAX_SUMMARY = 120
MAX_SOURCES = 3
VALID_FOR = timedelta(hours=8)
FUTURE_SLACK = timedelta(minutes=5)
CODE = re.compile(r"^[0-9][0-9A-Z]{3}$")
URL = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?$")
AS_OF = re.compile(r"^as_of:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
# Brain flag direction: a note against the lit signal is marked as a caution.
AGAINST = {1: ("悪材料",), -1: ("好材料",)}


def parse_note(text: str, *, now: datetime) -> dict:
    """The rows of one Grok answer, or ok=False with the reason. Never raises."""
    lines = [x.strip() for x in str(text or "").replace("\r\n", "\n").split("\n")]
    try:
        start = lines.index(HEADER)
        end = lines.index("END", start)
    except ValueError:
        return {"ok": False, "reason": "形式が違います（GROK_NOTE_V1 と END の行が必要）", "items": [], "rejected": []}
    body = [x for x in lines[start + 1:end] if x]
    match = AS_OF.match(body[0]) if body else None
    if not match:
        return {"ok": False, "reason": "as_of の行がありません（例 as_of: 2026-10-23 07:40）", "items": [], "rejected": []}
    try:
        as_of = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    except ValueError:
        return {"ok": False, "reason": "as_of の日時が読めません", "items": [], "rejected": []}
    local = now.astimezone(JST)
    if as_of > local + FUTURE_SLACK:
        return {"ok": False, "reason": "as_of が未来の時刻です", "items": [], "rejected": []}
    valid_until = min(as_of + VALID_FOR, as_of.replace(hour=23, minute=59))
    items, rejected, seen = [], [], set()
    for n, line in enumerate(body[1:], start=1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            rejected.append({"row": n, "reason": "区切り（|）が4つの欄になっていません"})
            continue
        code, stance, summary, sources = parts
        code = code.upper()
        urls = [u for u in sources.split() if URL.match(u)][:MAX_SOURCES]
        if not CODE.match(code):
            reason = "銘柄コードが4文字ではありません"
        elif stance not in STANCES:
            reason = "種類は 好材料・悪材料・話題・噂 のどれか"
        elif not summary:
            reason = "要約がありません"
        elif not urls:
            reason = "出典（https のURL）がありません"
        elif code in seen:
            reason = "同じ銘柄が2回あります"
        else:
            reason = None
        if reason:
            rejected.append({"row": n, "code": code[:8], "reason": reason})
            continue
        seen.add(code)
        items.append({"code": code, "stance": stance, "summary": summary[:MAX_SUMMARY], "sources": urls})
        if len(items) >= MAX_ROWS:
            break
    if not items:
        return {"ok": False, "reason": "使える行がありません", "items": [], "rejected": rejected,
                "as_of": as_of.isoformat()}
    return {"ok": True, "as_of": as_of.isoformat(), "valid_until": valid_until.isoformat(),
            "expired": local >= valid_until, "items": items, "rejected": rejected}


def load_notes(runtime: Path, *, now: datetime, known: dict, logged: set | None = None) -> dict:
    """Unexpired notes in RuntimeDir/grok_inbox, newest first. known: code -> name of the
    cockpit's watched universe. Returns the screen view and code -> [watch entries]."""
    inbox = Path(runtime) / INBOX_DIR
    try:
        files = sorted((p for p in inbox.glob("grok_*.txt") if p.is_file()), key=lambda p: p.name, reverse=True)[:MAX_FILES]
    except OSError:
        files = []
    notes, attention = [], {}
    for path in files:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            note = parse_note(path.read_text(encoding="utf-8-sig", errors="replace"), now=now)
        except OSError:
            continue
        if not note["ok"] or note["expired"]:
            continue
        rows = []
        for item in note["items"]:
            inside = item["code"] in known
            rows.append(dict(item, name=known.get(item["code"]) or "", in_universe=inside))
            if inside and item["code"] not in attention:   # the newest note wins for an issue
                attention[item["code"]] = [{"role": "grok", "report_id": path.name, "expires_at": note["valid_until"],
                                            "stance": item["stance"], "summary": item["summary"]}]
        notes.append({"note": path.name, "as_of": note["as_of"], "valid_until": note["valid_until"], "items": rows})
    if logged is not None:
        _log(Path(runtime) / "records", notes, now=now, logged=logged)
    return {"view": {"notes": notes[:5], "status": "MANUAL_WATCH_ONLY_NOT_A_SCORE"}, "attention": attention}


def _log(records: Path, notes: list, *, now: datetime, logged: set) -> int:
    local = now.astimezone(JST)
    path = Path(records) / local.date().isoformat() / NOTES_FILE
    if not logged and path.is_file():
        with open(path, newline="", encoding="utf-8-sig") as f:
            logged.update((r.get("note"), r.get("code")) for r in csv.DictReader(f))
    new = []
    for note in notes:
        for item in note["items"]:
            key = (note["note"], item["code"])
            if key in logged:
                continue
            logged.add(key)
            new.append({"seen_at": local.strftime("%Y-%m-%d %H:%M:%S"), "note": note["note"], "as_of": note["as_of"],
                        "code": item["code"], "name": item["name"], "stance": item["stance"], "summary": item["summary"],
                        "sources": " ".join(item["sources"]), "in_universe": item["in_universe"]})
    if not new:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8-sig" if first else "utf-8") as f:
        w = csv.DictWriter(f, fieldnames=NOTE_FIELDS)
        if first:
            w.writeheader()
        w.writerows(new)
    return len(new)


def brain_flag(entry: dict, side: int) -> str:
    """The Brain card's flag for one Grok watch entry on a lit signal of this side."""
    text = "Grok（手動）：" + entry["stance"] + "「" + entry["summary"] + "」"
    return text + ("（サインと逆向き・注意）" if entry["stance"] in AGAINST.get(side, ()) else "")


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
    note = parse_note(raw.decode("utf-8-sig", errors="replace"), now=datetime.now(timezone.utc))
    if not note["ok"]:
        print("NG：" + note["reason"])
    elif note["expired"]:
        print("NG：期限切れです（as_of から8時間、その日のうち）")
    else:
        print("OK：%d銘柄を受け取りました（%sまで有効）。ブレインが次の判定で読み込みます。"
              % (len(note["items"]), note["valid_until"][11:16]))
        for item in note["items"]:
            print("  %s %s %s" % (item["code"], item["stance"], item["summary"]))
    for r in note["rejected"]:
        print("  使わなかった行 %d：%s" % (r["row"], r["reason"]))
    return 0 if note["ok"] and not note["expired"] else 1


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        sys.exit(check_file(sys.argv[2]))
    print(json.dumps({"usage": "v10_grok_manual.py --check <file>"}))
    sys.exit(2)
