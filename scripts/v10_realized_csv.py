"""Today's realized P&L from the OWNER's own Rakuten 実現損益 CSV (display only).

OWNER 2026-11-02 「楽天のCSVで確定損益を出す形にする」: the 実口座 今日の確定損益 card's own estimate (no costs) differed
from Rakuten's figure. The OWNER saves Rakuten's realized_pl(JP)_*.csv into a folder on this
PC; RuntimeDir/realized_csv_config.json ({"folder": "..."}, PC only, never in the repo) names it. The newest
realized_pl(JP)*.csv there is read, only the rows whose 約定日 is today are summed (実現損益[円] as Rakuten wrote it,
costs included), and RuntimeDir/realized_csv_today_v1.json gets the total and the long (売埋 / 売付) / short (買埋)
split. No prices, names or rows are written, nothing leaves this PC. real_submit_allowed is false.
"""
import csv
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
SCHEMA = "100b-v10-realized-csv-v1"
CONFIG_FILE = "realized_csv_config.json"
OUT_FILE = "realized_csv_today_v1.json"
NAME = re.compile(r"^realized_pl\(JP\).*\.csv$", re.IGNORECASE)


def _yen(v):
    s = str(v or "").replace(",", "").replace("円", "").replace("+", "").strip()
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def _day(v):
    d = re.findall(r"\d+", str(v or ""))
    return "%04d-%02d-%02d" % tuple(int(x) for x in d[:3]) if len(d) >= 3 else None


def _text(raw):
    for enc in ("utf-8-sig", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", errors="replace")


def summarize(raw, day):
    """Sum today's rows of one CSV. Returns the summary (no row details)."""
    rows = list(csv.reader(io.StringIO(_text(raw))))
    head = next((i for i, r in enumerate(rows) if "約定日" in [c.strip() for c in r] and any("実現損益" in c for c in r)), None)
    if head is None:
        return {"state": "FORMAT_UNKNOWN"}
    cols = [c.strip() for c in rows[head]]
    i_day = cols.index("約定日")
    i_pl = next(i for i, c in enumerate(cols) if c.startswith("実現損益"))
    i_kind = cols.index("取引") if "取引" in cols else None
    out = {"state": "OK", "yen": 0, "n": 0, "long": {"yen": 0, "n": 0}, "short": {"yen": 0, "n": 0}, "other": {"yen": 0, "n": 0},
           "unreadable": 0, "latest_trade_day": None}
    for r in rows[head + 1:]:
        if len(r) <= max(i_day, i_pl):
            continue
        d = _day(r[i_day])
        if d and (out["latest_trade_day"] is None or d > out["latest_trade_day"]):
            out["latest_trade_day"] = d
        if d != day:
            continue
        y = _yen(r[i_pl])
        if y is None:
            out["unreadable"] += 1
            continue
        kind = r[i_kind].strip() if i_kind is not None and len(r) > i_kind else ""
        side = "short" if "買埋" in kind else ("long" if ("売埋" in kind or "売付" in kind) else "other")
        out[side]["yen"] += y
        out[side]["n"] += 1
        out["yen"] += y
        out["n"] += 1
    if out["n"] == 0:
        out["state"] = "NO_TODAY_ROWS"
    return out


def build(runtime, *, now=None):
    """Write RuntimeDir/realized_csv_today_v1.json from the newest CSV in the configured folder. Returns the view."""
    now = (now or datetime.now(timezone.utc)).astimezone(JST)
    day = now.date().isoformat()
    view = {"schema_version": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "day": day, "state": "NOT_CONFIGURED",
            "source": "楽天 実現損益CSV（手数料・金利など込み、楽天の計算のまま）", "real_submit_allowed": False, "trade_instruction": False}
    try:
        with open(os.path.join(str(runtime), CONFIG_FILE), encoding="utf-8-sig") as f:
            folder = json.load(f).get("folder")
    except (OSError, ValueError, AttributeError):
        folder = None
    if folder and os.path.isdir(folder):
        files = [os.path.join(folder, n) for n in os.listdir(folder) if NAME.match(n)]
        files = [p for p in files if os.path.isfile(p)]
        if not files:
            view["state"] = "NO_CSV"
        else:
            newest = max(files, key=os.path.getmtime)
            saved = datetime.fromtimestamp(os.path.getmtime(newest), JST)
            with open(newest, "rb") as f:
                raw = f.read(32 * 1024 * 1024)
            view.update(summarize(raw, day))
            view["csv_saved_at"] = saved.isoformat(timespec="seconds")
            if view["state"] == "NO_TODAY_ROWS" and saved.date().isoformat() < day:
                view["state"] = "CSV_OLD"
    elif folder:
        view["state"] = "FOLDER_MISSING"
    out = os.path.join(str(runtime), OUT_FILE)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False)
    os.replace(tmp, out)
    return view
