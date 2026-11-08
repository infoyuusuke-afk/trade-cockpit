"""OWNER 2026-11-08 「朝、音声できょうの相場で注意するところをアナウンスしてほしい、また場中決算１５分、５分前でも音声でしらせてほしい」
OWNER 2026-11-08 「決算前の知らせは確かめた時刻の銘柄だけにして。監査が通るまで定時登録はしない」

コクピットの今の音声の仕組み（127.0.0.1:28583 の読み上げ）に話させる。コクピットの版は変えない。話すだけで、売買や画面は変えない。
  python voice_notice.py morning --files <MS2のfilesフォルダ> --brain <研究のフォルダ>   平日8:40。今日の注意
  python voice_notice.py watch   --files ... --brain ...                                平日9:00〜15:30に1分おき。決算の15分前と5分前
  --dry で話さずに画面に出す。--date YYYY-MM-DD と --now HH:MM で試せる
決算の時刻は「確かめた時刻」だけを使う：AIアナリスト3号の答えの「決算予定：YYYY-MM-DD HH:MM」で、時刻未確認と書かれておらず、https の出典があるもの。
または <brain>/研究結果/音声/決算時刻_確認済み.json に人が書いたもの（{"items":[{"code","date","time","source"}]}、source は https）。
前回の決算の時刻は朝の案内で「参考」として言うだけで、決算前の知らせには使わない。TDnetで発表が出た銘柄は話さない。銘柄コードは読まない。
"""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request

KEY = ["285A", "6857", "8035", "9984", "6981", "4062", "6525", "6963", "6920", "9983", "7203", "6758"]
BRIDGE = "http://127.0.0.1:28583/announce?level=WATCH&text="
# the same readings as the Collector's voice (Convert-ToCockpitSpeechText), keyed by the code so the calendar's spelling does not matter
READ = {"5714": "ドーワ ホールディングス", "581A": "ゴー", "4475": "ヘンゲ", "7741": "ホーヤ", "7013": "アイエイチアイ", "1605": "インペックス",
        "9020": "ジェイアール東日本", "5016": "ジェイエックス金属", "9433": "ケーディーディーアイ", "6525": "コクサイ エレクトリック", "8725": "エムエスアンドエーディー",
        "6701": "エヌイーシー", "9432": "エヌティーティー", "7735": "スクリーン ホールディングス", "3697": "シフト", "3436": "サムコ", "5805": "エスダブリューシーシー",
        "4443": "サンサン", "6762": "ティーディーケー", "6481": "ティーエイチケー", "278A": "テラドローン", "5243": "ノート", "8306": "三菱ユーエフジェイ フィナンシャルグループ",
        "285A": "きおくしあ ホールディングス"}
SESSION = (("09:00", "11:30"), ("12:30", "15:30"))
CONFIRMED_DAYS = 5   # an answer of AIアナリスト3号 older than this is not used
TIME_LINE = re.compile(r"^決算予定：\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})(.*)$")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def in_session(hm):
    return any(a <= hm < b for a, b in SESSION)


def hm_words(hm):
    h, m = int(hm[:2]), int(hm[3:5])
    return "%d時" % h + ("" if m == 0 else "半" if m == 30 else "%d分" % m)


def name_of(code, raw):
    return READ.get(code) or re.sub(r"\s+", "", str(raw or ""))


def confirmed_times(brain, day):
    """code -> HH:MM for the day, from AIアナリスト3号 (newest file wins) and the hand-written file. Only a time with an https source."""
    out = {}
    today = date.fromisoformat(day)
    for f in sorted(Path(brain, "Grok3号").glob("決算前監視_*.txt")):
        m = re.search(r"_(\d{4})(\d{2})(\d{2})_", f.name)
        if not m or (today - date(*map(int, m.groups()))).days > CONFIRMED_DAYS or date(*map(int, m.groups())) > today:
            continue
        code = None
        for line in f.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            c = re.match(r"^銘柄：.*?[（(]([0-9][0-9A-Z]{3})[）)]", line)
            if c:
                code = c.group(1)
                continue
            t = TIME_LINE.match(line)
            if code and t and t.group(1) == day:
                rest = t.group(4)
                head = rest.split("出典")[0]
                if "未確認" not in head and "https://" in rest and 0 <= int(t.group(2)) <= 23:
                    out[code] = "%02d:%s" % (int(t.group(2)), t.group(3))
                code = None
    hand = load(Path(brain, "研究結果", "音声", "決算時刻_確認済み.json")) or {}
    for it in hand.get("items") or []:
        if isinstance(it, dict) and it.get("date") == day and re.fullmatch(r"\d{2}:\d{2}", str(it.get("time") or "")) and str(it.get("source") or "").startswith("https://"):
            out[str(it.get("code"))] = it["time"]
    return out


def earnings_today(files, brain, day):
    cal = load(Path(files, "public_feed", "earnings_calendar.json")) or {}
    last = (load(Path(files, "earnings_times_v1.json")) or {}).get("stocks") or {}
    sure = confirmed_times(brain, day)
    out, seen = [], set()
    for x in cal.get("calendar") or []:
        code = str(x.get("code"))
        if x.get("date") != day or code in seen or not (code in KEY or x.get("watched") is True or code in sure):
            continue
        seen.add(code)
        prev = str((last.get(code) or {}).get("last_at") or "")
        out.append({"code": code, "name": name_of(code, x.get("name")), "key": code in KEY, "sure": sure.get(code, ""),
                    "prev": prev[11:16] if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", prev) else ""})
    return out


def announced(files, day):
    td = load(Path(files, "tdnet_today_v1.json")) or {}
    if td.get("date") != day:
        return set()
    return {str(i.get("code")) for i in td.get("items") or [] if "決算短信" in str(i.get("title") or "") and "訂正" not in str(i.get("title") or "")}


def first_line(p):
    try:
        return Path(p).read_text(encoding="utf-8").splitlines()[0]
    except (OSError, IndexError):
        return ""


def say(brain, text, dry):
    log = Path(brain, "研究結果", "音声")
    log.mkdir(parents=True, exist_ok=True)
    with open(log / "話した記録.txt", "a", encoding="utf-8") as f:
        f.write("%s%s %s\n" % ("（試し）" if dry else "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
    print(text)
    if dry:
        return True
    try:
        urllib.request.urlopen(BRIDGE + urllib.parse.quote(text), timeout=40).read()
        return True
    except Exception as e:
        with open(log / "話した記録.txt", "a", encoding="utf-8") as f:
            f.write("  読み上げ失敗 %s\n" % type(e).__name__)
        return False


def morning_text(files, brain, day):
    parts = ["おはようございます。今日の注意です。"]
    ev = load(Path(files, "public_feed", "event_calendar.json")) or {}
    hi = [e for e in ev.get("events") or [] if e.get("date") == day and e.get("impact") == "高"]
    for e in hi[:3]:
        t = str(e.get("time_jst") or "")
        parts.append("%s、%s。" % (hm_words(t) if re.match(r"\d{2}:\d{2}$", t) else t, e.get("title")))
    es = earnings_today(files, brain, day)
    alerts = [x for x in es if x["sure"] and in_session(x["sure"])]
    for x in es:
        if x["sure"]:
            parts.append("%sの決算、%s%s。" % (x["name"], "場中の" if in_session(x["sure"]) else "", hm_words(x["sure"])))
        elif x["key"]:
            parts.append("%sの決算、時刻は未確認。%s" % (x["name"], "前回は%sでした。" % hm_words(x["prev"]) if x["prev"] else ""))
    others = len([x for x in es if not x["sure"] and not x["key"]])
    if others:
        parts.append("ほかに、時刻が未確認の監視銘柄の決算が%d社あります。" % others)
    if alerts:
        parts.append("場中の決算は、時刻を確かめた銘柄だけ、15分前と5分前にお知らせします。")
    if not hi and not es:
        parts.append("大きな予定と主な決算はありません。")
    m = first_line(Path(brain, "研究結果", "朝の段", "最新.txt"))
    if m.startswith(day) and len(m.split()) > 1:
        parts.append("朝の点数は%s。" % m.split()[1])
    v = re.search(r"シナリオ：([^（／]+)", first_line(Path(brain, "研究結果", "シナリオ", "最新.txt")))
    if v:
        parts.append("SOXのシナリオは、%s。" % v.group(1))
    a = Path(brain, "アナリスト報告", "地合い", "地合い_%s_0815.txt" % day.replace("-", ""))
    if a.is_file():
        t = a.read_text(encoding="utf-8", errors="replace")
        d1, d2 = re.search(r"危なさ[：:]\s*(\S+)", t), re.search(r"^向き[：:]\s*(\S+)", t, re.M)
        if d1 and d2:
            parts.append("地合いの見立ては、危なさ%s、向きは%s。" % (d1.group(1), d2.group(1)))
    parts.append("売買の判断はご自身でお願いします。")
    return "".join(parts)


def due(files, brain, day, now, done):
    """(key, text) to speak now. A minute that was missed still speaks up to 2 minutes late."""
    out = []
    t0 = datetime.strptime(day + " " + now, "%Y-%m-%d %H:%M")
    gone = announced(files, day)
    for x in earnings_today(files, brain, day):
        if not x["sure"] or not in_session(x["sure"]) or x["code"] in gone:
            continue
        at = datetime.strptime(day + " " + x["sure"], "%Y-%m-%d %H:%M")
        for mins in (15, 5):
            key = "%s-%d" % (x["code"], mins)
            start = at - timedelta(minutes=mins)
            if key not in done and start <= t0 < start + timedelta(minutes=3):
                out.append((key, "%sの決算、発表予定の%sまで、あと%d分です。" % (x["name"], hm_words(x["sure"]), mins)))
    return out


def main():
    files, brain = arg("--files"), arg("--brain")
    if not files or not brain:
        print("--files と --brain を指定してください")
        return 1
    dry = "--dry" in sys.argv
    day = arg("--date", date.today().isoformat())
    now = arg("--now", datetime.now().strftime("%H:%M"))
    if date.fromisoformat(day).weekday() > 4:
        return 0
    if "morning" in sys.argv:
        say(brain, morning_text(files, brain, day), dry)
        return 0
    if "watch" in sys.argv:
        if not ("08:45" <= now <= "15:30"):
            return 0
        state = Path(brain, "研究結果", "音声", "決算の知らせ_%s.json" % day.replace("-", ""))
        done = set(load(state) or [])
        for key, text in due(files, brain, day, now, done):
            if say(brain, text, dry):
                done.add(key)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(sorted(done)), encoding="utf-8")
        return 0
    print("morning か watch を指定してください")
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
