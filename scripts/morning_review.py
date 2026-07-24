"""Persist the morning plan and audit it after the Tokyo close.

The audit is deliberately conservative: when daily data cannot establish
whether a stop or a target was reached first, the trade is excluded.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data.json"
PAGE = ROOT / "index.html"
SNAPSHOT = ROOT / "morning_snapshot.json"
HISTORY = ROOT / "paper_trade_history.json"
JST = ZoneInfo("Asia/Tokyo")


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def morning_snapshot(data: dict, now: datetime) -> dict:
    candidates = []
    for row in data.get("day_candidates", [])[:10]:
        plan = row.get("plan") or {}
        if not all(plan.get(k) is not None for k in ("entry", "stop", "target1", "target2")):
            continue
        candidates.append(
            {
                "name": row.get("name", ""),
                "ticker": row.get("ticker", ""),
                "side": row.get("side", "LONG"),
                "score": round(70 + min(25, max(0, float(row.get("day_score", 0)) * 3)), 0),
                "entry": plan["entry"],
                "stop": plan["stop"],
                "target1": plan["target1"],
                "target2": plan["target2"],
                "morning_price": row.get("price"),
            }
        )
    return {
        "date": now.date().isoformat(),
        "fixed_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "rule": "朝の発動価格を固定。寄り成りではなく、発動価格到達時だけ仮想約定。",
        "candidates": candidates,
    }


def audit_one(plan: dict, stock: dict) -> dict:
    side = plan.get("side", "LONG")
    entry, stop = float(plan["entry"]), float(plan["stop"])
    t1, t2 = float(plan["target1"]), float(plan["target2"])
    day = stock.get("intraday") or stock
    low, high = float(day.get("low", 0)), float(day.get("high", 0))
    close = float(day.get("close", stock.get("price", 0)))
    vwap = day.get("vwap")
    triggered = low <= entry <= high
    result, pnl = "未発動（見送り）", None
    if triggered:
        stop_hit = low <= stop if side == "LONG" else high >= stop
        t1_hit = high >= t1 if side == "LONG" else low <= t1
        t2_hit = high >= t2 if side == "LONG" else low <= t2
        if stop_hit and (t1_hit or t2_hit):
            result = "順序不明（成績除外）"
        elif stop_hit:
            result = "損切り"
            pnl = (stop - entry) if side == "LONG" else (entry - stop)
        elif t2_hit:
            result = "利確2到達"
            pnl = ((t1 - entry) + (t2 - entry)) / 2 if side == "LONG" else ((entry - t1) + (entry - t2)) / 2
        elif t1_hit:
            result = "利確1＋残り大引け"
            pnl = ((t1 - entry) + (close - entry)) / 2 if side == "LONG" else ((entry - t1) + (entry - close)) / 2
        else:
            result = "大引け決済"
            pnl = (close - entry) if side == "LONG" else (entry - close)
    risk = abs(entry - stop) or 1
    shares = 10 if entry >= 10000 else 100
    return {
        **plan,
        "triggered": triggered,
        "result": result,
        "close": close,
        "vwap": vwap,
        "pnl_yen": None if pnl is None else round(pnl * shares),
        "r": None if pnl is None else round(pnl / risk, 2),
        "shares": shares,
    }


def statistics(history: list[dict]) -> dict:
    trades = [x for x in history if x.get("pnl_yen") is not None]
    gains = sum(max(0, x["pnl_yen"]) for x in trades)
    losses = abs(sum(min(0, x["pnl_yen"]) for x in trades))
    pf = round(gains / losses, 2) if losses else (99.0 if gains else 0.0)
    wins = sum(x["pnl_yen"] > 0 for x in trades)
    avg_r = round(sum(x.get("r", 0) for x in trades) / len(trades), 2) if trades else 0
    ready = len(trades) >= 20 and pf >= 1.2 and avg_r > 0
    return {
        "count": len(trades),
        "wins": wins,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
        "pf": pf,
        "avg_r": avg_r,
        "pnl": sum(x["pnl_yen"] for x in trades),
        "decision": "少額の実戦検討" if ready else "検証継続・実弾見送り",
    }


def render(reviews: list[dict], stats: dict, message: str, provisional: bool = False) -> str:
    rows = []
    for x in reviews:
        pnl = "—" if x["pnl_yen"] is None else f'{x["pnl_yen"]:+,}円'
        r = "—" if x["r"] is None else f'{x["r"]:+.2f}R'
        rows.append(
            "<tr>"
            f"<td>{html.escape(x['name'])}</td>"
            f"<td>{html.escape(x['side'])} {x['score']:.0f}/100</td>"
            f"<td>{x['entry']:,.0f}<br><small>損切 {x['stop']:,.0f}</small></td>"
            f"<td>{x['target1']:,.0f} / {x['target2']:,.0f}</td>"
            f"<td><strong>{html.escape(x['result'])}</strong><br><small>{'前引け' if provisional else '終値'} {x['close']:,.0f}</small></td>"
            f"<td>{pnl}<br><small>{r}</small></td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="6">同日8:30版の固定スナップショットがないため検証不成立。候補成績には加算しません。</td></tr>'
    return f"""
<section class="panel morning-audit">
  <h2>④ 朝8:30版との答え合わせ・仮想トレード</h2>
  <p>{html.escape(message)}</p>
  <div class="cards">
    <div class="card"><b>累計検証</b><span>{stats['count']}件</span></div>
    <div class="card"><b>勝率</b><span>{stats['win_rate']:.1f}%</span></div>
    <div class="card"><b>PF</b><span>{stats['pf']:.2f}</span></div>
    <div class="card"><b>平均R</b><span>{stats['avg_r']:+.2f}R</span></div>
    <div class="card"><b>仮想損益</b><span>{stats['pnl']:+,}円</span></div>
    <div class="card"><b>実戦判定</b><span>{stats['decision']}</span></div>
  </div>
  <p><small>100株（1万円以上は10株）で計算。朝の発動価格到達時のみ約定。同日中に損切りと利確の両方へ触れ、順序を確定できない取引は除外。</small></p>
  <div class="table-wrap"><table><thead><tr><th>銘柄</th><th>朝評価</th><th>発動 / 損切</th><th>利確1 / 2</th><th>{'前場途中経過' if provisional else '大引け判定'}</th><th>{'仮含み損益' if provisional else '仮想損益'}</th></tr></thead><tbody>{body}</tbody></table></div>
</section>"""


def main() -> None:
    now = datetime.now(JST)
    data = load(DATA, {})
    is_midday = now.hour == 11
    is_close = now.hour >= 12 or "大引け" in data.get("phase", "")
    if not is_midday and not is_close:
        snap = morning_snapshot(data, now)
        save(SNAPSHOT, snap)
        data["morning_snapshot_fixed"] = snap
        save(DATA, data)
        return

    snap = load(SNAPSHOT, {})
    same_day = snap.get("date") == now.date().isoformat()
    stocks = data.get("stocks", {})
    reviews = []
    if same_day:
        for plan in snap.get("candidates", []):
            stock = stocks.get(plan["name"])
            if stock:
                reviews.append(audit_one(plan, stock))

    history = load(HISTORY, [])
    if is_close:
        history = [x for x in history if x.get("date") != now.date().isoformat()]
        history.extend({"date": now.date().isoformat(), **x} for x in reviews)
        history = history[-500:]
        save(HISTORY, history)
    stats = statistics(history)
    message = (
        f"朝{snap.get('fixed_at', '')}に固定した候補を、{'前場データで途中検証（正式成績には未加算）' if is_midday else '大引けデータで正式検証'}。"
        if same_day
        else "本日は同日8:30版の機械保存がないため、答え合わせは検証不成立。次回朝版から自動蓄積します。"
    )
    section = render(reviews, stats, message, provisional=is_midday)
    page = PAGE.read_text(encoding="utf-8")
    pattern = re.compile(r'<section[^>]*>\\s*<h2>④ 朝8(?::30)?候補のザラバ答え合わせ.*?</section>', re.S)
    if pattern.search(page):
        page = pattern.sub(section, page, count=1)
    else:
        page = page.replace("</main>", section + "\n</main>", 1)
    PAGE.write_text(page, encoding="utf-8")
    data["paper_trade_reviews"] = reviews
    data["paper_trade_stats"] = stats
    save(DATA, data)


if __name__ == "__main__":
    main()
