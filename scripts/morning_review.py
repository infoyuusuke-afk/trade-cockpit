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


def price_text(value) -> str:
    value = float(value)
    return f"{value:,.1f}" if abs(value - round(value)) >= .05 else f"{value:,.0f}"


def morning_snapshot(data: dict, now: datetime) -> dict:
    candidates = []
    source = data.get("day_ifo_candidates") or data.get("day_candidates", [])
    for row in source[:5]:
        plan = row.get("plan") or {
            "entry": row.get("trigger"),
            "entry_limit": row.get("entry_limit"),
            "stop": row.get("stop"),
            "target1": row.get("target1"),
            "target2": row.get("target2"),
        }
        if not all(plan.get(k) is not None for k in ("entry", "stop", "target1", "target2")):
            continue
        if plan.get("entry_limit") is None:
            plan["entry_limit"] = plan["entry"]
        fallback_score = 70 + min(
            25, max(0, float(row.get("day_score", 0)) * 3)
        )
        candidates.append(
            {
                "name": row.get("name", ""),
                "ticker": row.get("ticker", ""),
                "side": row.get("side", "LONG"),
                "score": round(float(row.get("score", fallback_score)), 0),
                "entry": plan["entry"],
                "entry_limit": plan["entry_limit"],
                "stop": plan["stop"],
                "target1": plan["target1"],
                "target2": plan["target2"],
                "morning_price": row.get("price", row.get("entry_limit")),
            }
        )
    return {
        "date": now.date().isoformat(),
        "fixed_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "rule": (
            "朝の5銘柄と価格を固定。8:55気配が買い指値上限以内なら"
            "100株IFOを手入力し、発動価格到達時だけ仮想約定。"
        ),
        "candidates": candidates,
    }


def audit_one(plan: dict, stock: dict) -> dict:
    side = plan.get("side", "LONG")
    trigger, stop = float(plan["entry"]), float(plan["stop"])
    entry = float(plan.get("entry_limit", trigger))
    t1, t2 = float(plan["target1"]), float(plan["target2"])
    day = stock.get("intraday") or stock
    low, high = float(day.get("low", 0)), float(day.get("high", 0))
    close = float(day.get("close", stock.get("price", 0)))
    vwap = day.get("vwap")
    triggered = (
        high >= trigger and low <= entry
        if side == "LONG"
        else low <= trigger and high >= entry
    )
    result, pnl = "未発動（見送り）", None
    if triggered:
        stop_hit = low <= stop if side == "LONG" else high >= stop
        t1_hit = high >= t1 if side == "LONG" else low <= t1
        if stop_hit and t1_hit:
            result = "順序不明（成績除外）"
        elif stop_hit:
            result = "IFO損切り"
            pnl = (stop - entry) if side == "LONG" else (entry - stop)
        elif t1_hit:
            result = "IFO利確1"
            pnl = (t1 - entry) if side == "LONG" else (entry - t1)
        else:
            result = "時点評価・未決済"
            pnl = (close - entry) if side == "LONG" else (entry - close)
    risk = abs(entry - stop) or 1
    shares = 100
    return {
        **plan,
        "entry": trigger,
        "entry_limit": entry,
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


def render(reviews: list[dict], stats: dict, message: str) -> str:
    rows = []
    for x in reviews:
        pnl = "—" if x["pnl_yen"] is None else f'{x["pnl_yen"]:+,}円'
        r = "—" if x["r"] is None else f'{x["r"]:+.2f}R'
        rows.append(
            "<tr>"
            f"<td>{html.escape(x['name'])}</td>"
            f"<td>{html.escape(x['side'])} {x['score']:.0f}/100</td>"
            f"<td>{price_text(x['entry'])}<br><small>上限 {price_text(x['entry_limit'])}／損切 {price_text(x['stop'])}</small></td>"
            f"<td>{price_text(x['target1'])}<br><small>参考 {price_text(x['target2'])}</small></td>"
            f"<td><strong>{html.escape(x['result'])}</strong><br><small>時点値 {price_text(x['close'])}</small></td>"
            f"<td>{pnl}<br><small>{r}</small></td>"
            "</tr>"
        )
    body = "".join(rows) or '<tr><td colspan="6">同日8:00版の固定スナップショットがないため検証不成立。候補成績には加算しません。</td></tr>'
    return f"""
<section class="panel morning-audit">
  <h2>④ 朝8:00版との答え合わせ・仮想トレード</h2>
  <p>{html.escape(message)}</p>
  <div class="cards">
    <div class="card"><b>累計検証</b><span>{stats['count']}件</span></div>
    <div class="card"><b>勝率</b><span>{stats['win_rate']:.1f}%</span></div>
    <div class="card"><b>PF</b><span>{stats['pf']:.2f}</span></div>
    <div class="card"><b>平均R</b><span>{stats['avg_r']:+.2f}R</span></div>
    <div class="card"><b>仮想損益</b><span>{stats['pnl']:+,}円</span></div>
    <div class="card"><b>実戦判定</b><span>{stats['decision']}</span></div>
  </div>
  <p><small>全銘柄100株、買い指値上限を仮想約定値として保守的に計算。IFOは利確1または損切りで全株決済。同じ期間内に両方へ触れて順序を確定できない取引は成績から除外。</small></p>
  <div class="table-wrap"><table><thead><tr><th>銘柄</th><th>朝評価</th><th>発動 / 上限 / 損切</th><th>IFO利確 / 参考利確2</th><th>時点判定</th><th>仮想損益</th></tr></thead><tbody>{body}</tbody></table></div>
</section>"""


def main() -> None:
    now = datetime.now(JST)
    data = load(DATA, {})
    phase = data.get("phase", "")
    is_review = now.hour >= 11 or "前場検証" in phase or "大引け検証" in phase
    if not is_review:
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
    history = [x for x in history if x.get("date") != now.date().isoformat()]
    history.extend({"date": now.date().isoformat(), **x} for x in reviews)
    history = history[-500:]
    save(HISTORY, history)
    stats = statistics(history)
    checkpoint = "前場時点" if "前場検証" in phase or now.hour < 15 else "大引け"
    message = (
        f"朝{snap.get('fixed_at', '')}に固定した5銘柄を、{checkpoint}データで検証。"
        if same_day
        else "本日は同日8:00版の機械保存がないため、答え合わせは検証不成立。次回朝版から自動蓄積します。"
    )
    section = render(reviews, stats, message)
    page = PAGE.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<section[^>]*>\s*<h2>④ 朝8(?::(?:00|30))?'
        r'(?:候補のザラバ答え合わせ|版との答え合わせ・仮想トレード).*?</section>',
        re.S,
    )
    page = pattern.sub("", page)
    page = page.replace("</main>", section + "\n</main>", 1)
    PAGE.write_text(page, encoding="utf-8")
    data["paper_trade_reviews"] = reviews
    data["paper_trade_stats"] = stats
    save(DATA, data)


if __name__ == "__main__":
    main()
