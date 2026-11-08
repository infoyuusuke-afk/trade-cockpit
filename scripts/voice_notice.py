"""OWNER 2026-11-08 「朝、音声できょうの相場で注意するところをアナウンスしてほしい、また場中決算１５分、５分前でも音声でしらせてほしい」
OWNER 2026-11-08 「決算前の知らせは確かめた時刻の銘柄だけにして。監査が通るまで定時登録はしない」

コクピットの今の音声の仕組み（127.0.0.1:28583 の読み上げ）に話させる。コクピットの版は変えない。話すだけで、売買や画面は変えない。
  python voice_notice.py morning --files <MS2のfilesフォルダ> --brain <研究のフォルダ>   平日8:40。今日の注意
  python voice_notice.py watch   --files ... --brain ...                                平日8:45〜15:30に1分おき（9:00〜9:14の決算の15分前も出すため）。決算の15分前と5分前
  --dry で話さずに画面に出す。--date YYYY-MM-DD と --now HH:MM で試せる
決算の時刻は「確かめた時刻」だけを使う：AIアナリスト3号の答えの「決算予定：YYYY-MM-DD HH:MM」で、行のどこにも疑いの言葉
（未確認・未確定・未定・推定・見込・予想・慣例・例年・前回・観測など。URLの中は見ない）が無く、「出典」か「／」の後ろに https があるもの。
二次サイトの時刻も https があれば使う（OWNER 2026-11-08）。場中と昼休み（9:00〜15:30）の決算を知らせる。土日・休場日・12/31〜1/3は鳴らさない。
同じ銘柄は、その銘柄が載ったいちばん新しい答えだけで決める（新しい答えで未確認になれば、古い答えの時刻は使わない）。
または <brain>/研究結果/音声/決算時刻_確認済み.json に人が書いたもの（{"items":[{"code","date","time","source"}]}、source は https）。こちらが優先。
前回の決算の時刻は朝の案内で「参考」として言うだけで、決算前の知らせには使わない。TDnetで発表が出た銘柄は話さない。銘柄コードは読まない。
読み上げ側は Origin の無い /announce を PowerShell の呼び出し（Collector と同じ道）からだけ受けるので、PowerShell の Invoke-WebRequest で送る。
"""
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse

KEY = ["285A", "6857", "8035", "9984", "6981", "4062", "6525", "6963", "6920", "9983", "7203", "6758"]
BRIDGE = "http://127.0.0.1:28583/announce?level=WATCH&text="
# the same readings as the Collector's voice (Convert-ToCockpitSpeechText), keyed by the code so the calendar's spelling does not matter
READ = {"5714": "ドーワ ホールディングス", "581A": "ゴー", "4475": "ヘンゲ", "7741": "ホーヤ", "7013": "アイエイチアイ", "1605": "インペックス",
        "9020": "ジェイアール東日本", "5016": "ジェイエックス金属", "9433": "ケーディーディーアイ", "6525": "コクサイ エレクトリック", "8725": "エムエスアンドエーディー",
        "6701": "エヌイーシー", "9432": "エヌティーティー", "7735": "スクリーン ホールディングス", "3697": "シフト", "3436": "サムコ", "5805": "エスダブリューシーシー",
        "4443": "サンサン", "6762": "ティーディーケー", "6481": "ティーエイチケー", "278A": "テラドローン", "5243": "ノート", "8306": "三菱ユーエフジェイ フィナンシャルグループ",
        "285A": "きおくしあ ホールディングス"}
SESSION = (("09:00", "11:30"), ("12:30", "15:30"))
ALERT = ("09:00", "15:30")   # OWNER 2026-11-08: the lunch break too
CONFIRMED_DAYS = 5   # an answer of AIアナリスト3号 older than this is not used
TIME_LINE = re.compile(r"^決算予定[：:]\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})(.*)$")
STOCK_LINE = re.compile(r"銘柄[：:]")
CODE_IN = re.compile(r"[（(]([0-9][0-9A-Z]{3})[）)]")
# any of these anywhere on the line means the time is not one the company stated
# OWNER 2026-11-08 「二次サイトの時刻は使う」: a secondary site with an https source counts. URLs are removed before this check.
UNSURE = ("未確認", "未確定", "未定", "推定", "見込", "予想", "慣例", "例年", "前回", "観測", "?", "？")
URL = re.compile(r"https?://\S+")
EARN = re.compile(r"決算(?:予定)?[：:]\s*(.*)$")
WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})")
MAX_ITEM, MAX_TEXT = 40, 450
# the text goes to PowerShell through an environment variable, never into the command line
# exit 3 = timed out after sending (the voice answers only when it has finished speaking), 2 = any other failure
PS_SEND = ("$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
           "try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 60 -Uri $env:VOICE_NOTICE_URL;$c=$r.Content;if($c -is [byte[]]){$c=[Text.Encoding]::UTF8.GetString($c)};[Console]::Out.Write([string]$c);exit 0}"
           "catch [System.Net.WebException]{if($_.Exception.Status -eq [System.Net.WebExceptionStatus]::Timeout){[Console]::Out.Write('TIMEOUT');exit 3};"
           "$c='';if($_.Exception.Response){$c=[int]$_.Exception.Response.StatusCode};[Console]::Out.Write('FAILED '+$_.Exception.Status+' '+$c);exit 2}"
           "catch{[Console]::Out.Write('FAILED '+$_.Exception.GetType().Name);exit 2}")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv and sys.argv.index(name) + 1 < len(sys.argv) else default


def load(p, kind=dict):
    try:
        v = json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return kind()
    return v if isinstance(v, kind) else kind()


def dicts(v):
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def clip(t):
    return re.sub(r"\s+", " ", str(t or "")).strip()[:MAX_ITEM]


def valid_hm(t):
    try:
        datetime.strptime(t, "%H:%M")
        return True
    except (TypeError, ValueError):
        return False


def in_session(hm):
    return any(a <= hm < b for a, b in SESSION)


def alert_time(hm):
    return ALERT[0] <= hm < ALERT[1]


def closed(files, day):
    """Weekend, a TSE closed day in the cockpit's event calendar (category 休場 with 日本株), or the year-end 12/31-1/3."""
    d = date.fromisoformat(day)
    if d.weekday() > 4 or (d.month, d.day) in ((12, 31), (1, 1), (1, 2), (1, 3)):
        return True
    ev = load(Path(files, "public_feed", "event_calendar.json"))
    return any(e.get("date") == day and e.get("category") == "休場" and "日本株" in str(e.get("title") or "") for e in dicts(ev.get("events")))


def hm_words(hm):
    h, m = int(hm[:2]), int(hm[3:5])
    return "%d時" % h + ("" if m == 0 else "半" if m == 30 else "%d分" % m)


def name_of(code, raw):
    return READ.get(code) or re.sub(r"\s+", "", str(raw or ""))[:MAX_ITEM]


def file_day(f):
    m = re.search(r"_(\d{4})(\d{2})(\d{2})_", f.name)
    try:
        return date(*map(int, m.groups())) if m else None
    except ValueError:
        return None


def judge(rest, line, day):
    """HH:MM when `rest` (the words after 決算予定： or 決算：) is a sure time for the day, else "" """
    t = WHEN.match(rest.strip())
    if not t:
        return ""
    hm = "%02d:%s" % (int(t.group(2)), t.group(3))
    words = URL.sub("", line)
    src = line.split("出典", 1)[1] if "出典" in line else line.split("／", 1)[1] if "／" in line else ""
    ok = t.group(1) == day and valid_hm(hm) and not any(w in words for w in UNSURE) and "https://" in src
    return hm if ok else ""


def read_answer(lines, day):
    """code -> HH:MM or "" (listed but no sure time) from one answer. Only the first 決算予定 line after a stock's 銘柄 line counts;
    a line like 「銘柄：X（code）／決算：…」 (the check list at the end) is judged by itself."""
    code, found = None, {}
    for line in lines:
        line = line.strip()
        if line.startswith("決算予定"):
            if code and code not in found:
                m = EARN.match(line)
                found[code] = judge(m.group(1), line, day) if m else ""
            code = None
        elif STOCK_LINE.search(line):
            c = CODE_IN.search(line)
            code = c.group(1) if c else None   # a stock line without a code never keeps the stock before it
            m = EARN.search(line.split("）", 1)[1] if "）" in line else "")
            if code and m:
                if code not in found:
                    found[code] = judge(m.group(1), line, day)
                code = None
    return found


def confirmed_times(brain, day):
    """code -> HH:MM for the day. For each stock only the newest answer of AIアナリスト3号 that lists it decides; then the hand-written file, which wins."""
    today = date.fromisoformat(day)
    latest = {}
    for f in sorted(Path(brain, "Grok3号").glob("決算前監視_*.txt")):
        fd = file_day(f)
        if not fd or fd > today or (today - fd).days > CONFIRMED_DAYS:
            continue
        try:
            lines = f.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        except OSError:
            continue
        for c, hm in read_answer(lines, day).items():
            if c not in latest or (fd, f.name) >= latest[c][0]:
                latest[c] = ((fd, f.name), hm)
    out = {c: v[1] for c, v in latest.items() if v[1]}
    for it in dicts(load(Path(brain, "研究結果", "音声", "決算時刻_確認済み.json")).get("items")):
        t = str(it.get("time") or "")
        if it.get("date") == day and re.fullmatch(r"\d{2}:\d{2}", t) and valid_hm(t) and str(it.get("source") or "").startswith("https://"):
            out[str(it.get("code"))] = t
    return out


def earnings_today(files, brain, day):
    cal = load(Path(files, "public_feed", "earnings_calendar.json"))
    last = load(Path(files, "earnings_times_v1.json")).get("stocks")
    last = last if isinstance(last, dict) else {}
    sure = confirmed_times(brain, day)
    out, seen = [], set()
    for x in dicts(cal.get("calendar")):
        code = str(x.get("code"))
        if x.get("date") != day or code in seen or not (code in KEY or x.get("watched") is True or code in sure):
            continue
        seen.add(code)
        lp = last.get(code)
        prev = str(lp.get("last_at") or "") if isinstance(lp, dict) else ""
        prev = prev[11:16] if re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", prev) and valid_hm(prev[11:16]) else ""
        out.append({"code": code, "name": name_of(code, x.get("name")), "key": code in KEY, "sure": sure.get(code, ""), "prev": prev})
    return out


def announced(files, day):
    td = load(Path(files, "tdnet_today_v1.json"))
    if td.get("date") != day:
        return set()
    return {str(i.get("code")) for i in dicts(td.get("items")) if "決算短信" in str(i.get("title") or "") and "訂正" not in str(i.get("title") or "")}


def written_on(p, day):
    """OWNER 2026-11-08 「SOXの音声の注意は、シナリオの最新.txtが今日書かれた時だけ話すように直して」: True only when the file was
    last written on `day` (the PC's local date). A file that cannot be read is not today's."""
    try:
        return datetime.fromtimestamp(Path(p).stat().st_mtime).date().isoformat() == day
    except (OSError, ValueError, OverflowError):
        return False


def first_line(p):
    try:
        return Path(p).read_text(encoding="utf-8-sig", errors="replace").splitlines()[0]
    except (OSError, IndexError, ValueError):
        return ""


def say(brain, text, dry):
    """True when the voice took it, or when it timed out after the request went out (it may still be speaking, so not again)."""
    log = Path(brain, "研究結果", "音声")
    log.mkdir(parents=True, exist_ok=True)

    def note(t):
        with open(log / "話した記録.txt", "a", encoding="utf-8") as f:
            f.write(t + "\n")
    note("%s%s %s" % ("（試し）" if dry else "", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text))
    print(text)
    if dry:
        return True
    env = dict(os.environ, VOICE_NOTICE_URL=BRIDGE + urllib.parse.quote(text))
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_SEND],
                           env=env, capture_output=True, timeout=90)
    except subprocess.TimeoutExpired:
        note("  読み上げの返事待ちで時間切れ（話している途中かもしれないので、もう一度は話さない）")
        return True
    except OSError as e:
        note("  読み上げ失敗 %s" % type(e).__name__)
        return False
    body = r.stdout.decode("utf-8", "replace").strip()
    if r.returncode == 3:
        note("  読み上げの返事待ちで時間切れ（話している途中かもしれないので、もう一度は話さない）")
        return True
    if r.returncode != 0:
        note("  読み上げ失敗 %s" % (body[:120] or r.returncode))
        return False
    if "skipped" in body or "DISABLED" in body.upper():
        note("  読み上げはOFFでした %s" % body[:120])
    return True


def morning_text(files, brain, day):
    parts = ["おはようございます。今日の注意です。"]
    ev = load(Path(files, "public_feed", "event_calendar.json"))
    hi = [e for e in dicts(ev.get("events")) if e.get("date") == day and e.get("impact") == "高" and clip(e.get("title"))]
    for e in hi[:3]:
        t = str(e.get("time_jst") or "")
        when = hm_words(t) if re.fullmatch(r"\d{2}:\d{2}", t) and valid_hm(t) else clip(t)
        parts.append("%s%s。" % (when + "、" if when else "", clip(e.get("title"))))
    es = earnings_today(files, brain, day)
    alerts = [x for x in es if x["sure"] and alert_time(x["sure"])]
    for x in es:
        if x["sure"]:
            parts.append("%sの決算、%s%s。" % (x["name"], "場中の" if in_session(x["sure"]) else "昼休みの" if alert_time(x["sure"]) else "", hm_words(x["sure"])))
        elif x["key"]:
            parts.append("%sの決算、時刻は未確認。%s" % (x["name"], "前回は%sでした。" % hm_words(x["prev"]) if x["prev"] else ""))
    others = len([x for x in es if not x["sure"] and not x["key"]])
    if others:
        parts.append("ほかに、時刻が未確認の監視銘柄の決算が%d社あります。" % others)
    if alerts:
        parts.append("場中と昼休みの決算は、時刻を確かめた銘柄だけ、15分前と5分前にお知らせします。")
    if not hi and not es:
        parts.append("大きな予定と主な決算はありません。")
    m = first_line(Path(brain, "研究結果", "朝の段", "最新.txt"))
    if m.startswith(day) and len(m.split()) > 1:
        parts.append("朝の点数は%s。" % clip(m.split()[1]))
    sfile = Path(brain, "研究結果", "シナリオ", "最新.txt")
    sline = first_line(sfile)
    v = re.search(r"シナリオ：([^（／]+)", sline)
    # OWNER 2026-11-08 「戻りの天井（約11,350）の±3%に入ったか、底の線9,011か−40%の線8,781を割ったかを判定して、8:40の朝の音声で知らせ…
    # 『予測ではありません』と添える」: each caution of the 8:05 update (最新.txt 「／注意：…」) is said first, right after the greeting
    # 2026-11-08 audit: cut only the trailing 「（終値 …）」, so 「戻りの天井（約11,383）の±3%に入った」 is said whole
    cautions = [clip(re.sub(r"（終値[^）]*）\s*$", "", x.strip())) for x in re.findall(r"／注意：([^／\n]+)", sline)][:3] if written_on(sfile, day) else []
    if cautions:
        parts.insert(1, "注意です。SOXが、" + "、".join(cautions) + "。予測ではありません。")
    if v:
        parts.append("SOXのシナリオは、%s。" % clip(v.group(1)))
    a = Path(brain, "アナリスト報告", "地合い", "地合い_%s_0815.txt" % day.replace("-", ""))
    try:
        t = a.read_text(encoding="utf-8-sig", errors="replace") if a.is_file() else ""
    except OSError:
        t = ""
    d1, d2 = re.search(r"危なさ[：:]\s*(\S+)", t), re.search(r"^向き[：:]\s*(\S+)", t, re.M)
    if d1 and d2:
        parts.append("地合いの見立ては、危なさ%s、向きは%s。" % (clip(d1.group(1)), clip(d2.group(1))))
    end = "売買の判断はご自身でお願いします。"
    body = ""
    for p in parts:   # whole sentences only, and the closing words always stay
        if len(body) + len(p) + len(end) > MAX_TEXT:
            break
        body += p
    return body + end


def due(files, brain, day, now, done):
    """(key, text) to speak now. A minute that was missed still speaks up to 2 minutes late."""
    out = []
    t0 = datetime.strptime(day + " " + now, "%Y-%m-%d %H:%M")
    gone = announced(files, day)
    for x in earnings_today(files, brain, day):
        if not x["sure"] or not alert_time(x["sure"]) or x["code"] in gone:
            continue
        try:
            at = datetime.strptime(day + " " + x["sure"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
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
    if closed(files, day) or not valid_hm(now):   # OWNER 2026-11-08 「祝日は鳴らさない」
        return 0
    if "morning" in sys.argv:
        say(brain, morning_text(files, brain, day), dry)
        return 0
    if "watch" in sys.argv:
        if not ("08:45" <= now <= "15:30"):
            return 0
        state = Path(brain, "研究結果", "音声", "決算の知らせ_%s.json" % day.replace("-", ""))
        done = {x for x in load(state, list) if isinstance(x, str)}
        state.parent.mkdir(parents=True, exist_ok=True)
        for key, text in due(files, brain, day, now, done):
            if say(brain, text, dry):
                done.add(key)
                state.write_text(json.dumps(sorted(done)), encoding="utf-8")   # after each one, so a stop never repeats it
        return 0
    print("morning か watch を指定してください")
    return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
