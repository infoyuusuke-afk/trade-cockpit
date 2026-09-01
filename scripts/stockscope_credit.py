#!/usr/bin/env python3
"""Collect public Kioxia credit-supply figures from StockScope.

The collector only reads the public issue page.  It does not sign in, use a
subscriber session, or attempt to unlock paid indicators.  If the page shape
or dates are inconsistent, the previous verified file is kept unchanged.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "credit_supply.json"
URL = "https://stockscope.app/en/issues/285A"
JST = timezone(timedelta(hours=9))


def field(text: str, name: str, kind=float):
    match = re.search(rf'{re.escape(name)}\\?":(\\?"[^"\\]+\\?"|-?\d+(?:\.\d+)?)', text)
    if not match:
        raise ValueError(f"missing StockScope field: {name}")
    raw = match.group(1).replace('\\"', '"')
    if raw.startswith('"'):
        return raw.strip('"')
    return kind(raw)


def chart_history(text: str, title: str) -> tuple[dict[str, int], dict[str, int]]:
    # React streams the completed chart as an escaped JSON fragment near the
    # end of the HTML.  Work on the last occurrence to avoid the loading shell.
    plain = text.replace('\\"', '"')
    pos = plain.rfind(f'"title":"{title}"')
    if pos < 0:
        raise ValueError(f"missing chart: {title}")
    fragment = plain[pos:pos + 7000]
    series = re.findall(
        r'"name":"(Standardized margin|Negotiable margin)","data":\[(.*?)\]',
        fragment,
        flags=re.S,
    )
    parsed: dict[str, dict[str, int]] = {}
    for name, data in series[:2]:
        parsed[name] = {
            date: int(value)
            for date, value in re.findall(r'"x":"(\d{4}-\d{2}-\d{2})","y":(\d+)', data)
        }
    if set(parsed) != {"Standardized margin", "Negotiable margin"}:
        raise ValueError(f"incomplete chart series: {title}")
    return parsed["Standardized margin"], parsed["Negotiable margin"]


def phase(buy_change_pct: float, sell_change_pct: float) -> tuple[str, str, str]:
    if buy_change_pct <= -5 and sell_change_pct >= 5:
        return "改善", "戻り売り圧力が軽減", "買い残減少・売り残増加"
    if buy_change_pct >= 5 and sell_change_pct <= 0:
        return "悪化", "戻り売り優先・踏み上げ決め打ち禁止", "買い残増加・売り残減少"
    return "中立", "価格確認を優先", "信用残の方向が混在"


def main() -> None:
    request = Request(URL, headers={"User-Agent": "Mozilla/5.0 AI-Trade-Cockpit/1.0"})
    with urlopen(request, timeout=30) as response:
        html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")

    date = field(html, "current_margin_trade_volume_date", str)
    prev_date = field(html, "prev_margin_trade_volume_date", str)
    buy = int(field(html, "current_long_margin_trade_volume", float))
    sell = int(field(html, "current_short_margin_trade_volume", float))
    prev_buy = int(field(html, "prev_long_margin_trade_volume", float))
    prev_sell = int(field(html, "prev_short_margin_trade_volume", float))
    buy_diff = int(field(html, "long_margin_trade_volume_diff", float))
    sell_diff = int(field(html, "short_margin_trade_volume_diff", float))
    buy_diff_pct = float(field(html, "long_margin_trade_volume_diff_rate", float)) * 100
    sell_diff_pct = float(field(html, "short_margin_trade_volume_diff_rate", float)) * 100

    if buy - prev_buy != buy_diff or sell - prev_sell != sell_diff:
        raise ValueError("StockScope current/previous balance validation failed")
    if not buy > 0 or not sell > 0 or not math.isfinite(buy / sell):
        raise ValueError("StockScope returned invalid balances")

    buy_std, buy_neg = chart_history(html, "Margin buying breakdown")
    sell_std, sell_neg = chart_history(html, "Margin selling breakdown")
    history = []
    all_dates = sorted(set(buy_std) & set(buy_neg) & set(sell_std) & set(sell_neg))
    for d in all_dates:
        b, s = buy_std[d] + buy_neg[d], sell_std[d] + sell_neg[d]
        history.append({
            "date": d,
            "buy_balance": b,
            "sell_balance": s,
            "ratio": round(b / s, 2) if s else None,
            "standardized_buy": buy_std[d],
            "negotiable_buy": buy_neg[d],
            "standardized_sell": sell_std[d],
            "negotiable_sell": sell_neg[d],
        })
    if not history or history[-1]["date"] != date or history[-1]["buy_balance"] != buy:
        raise ValueError("StockScope chart/summary date validation failed")
    for idx, row in enumerate(history):
        if idx:
            prior = history[idx - 1]
            row["buy_change"] = row["buy_balance"] - prior["buy_balance"]
            row["sell_change"] = row["sell_balance"] - prior["sell_balance"]
            b_pct = row["buy_change"] / prior["buy_balance"] * 100
            s_pct = row["sell_change"] / prior["sell_balance"] * 100
            row["phase"] = phase(b_pct, s_pct)[0]
        else:
            row["buy_change"], row["sell_change"], row["phase"] = None, None, "履歴起点"

    supply_phase, trade_bias, reason = phase(buy_diff_pct, sell_diff_pct)
    now = datetime.now(JST)
    payload = {
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": "StockScope（株ビジョン）公開需給ページ",
        "source_url": URL,
        "stocks": {
            "285A": {
                "name": "キオクシアホールディングス",
                "margin_date": date,
                "retrieved_date": now.date().isoformat(),
                "previous_margin_date": prev_date,
                "margin_buy_balance": buy,
                "margin_buy_change_1w": buy_diff,
                "margin_buy_change_1w_pct": round(buy_diff_pct, 2),
                "margin_sell_balance": sell,
                "margin_sell_change_1w": sell_diff,
                "margin_sell_change_1w_pct": round(sell_diff_pct, 2),
                "credit_ratio": round(buy / sell, 2),
                "margin_buy_change_4w_pct": round((buy / history[0]["buy_balance"] - 1) * 100, 2) if len(history) >= 5 else None,
                "institutional_short_change_pct": None,
                "institutional_buyback_firms": None,
                "supply_phase": supply_phase,
                "trade_bias": trade_bias,
                "verified": True,
                "source_url": URL,
                "history": history,
                "note": f"{reason}。StockScopeの合計値と制度／一般内訳を照合済み。機関空売りは公表遅延があるため別判定。",
            }
        },
        "schema": {
            "margin_buy_change_1w_pct": "信用買い残の前週比（%）",
            "margin_buy_change_4w_pct": "信用買い残の4週変化（%）",
            "credit_ratio": "信用倍率",
            "institutional_short_change_pct": "機関空売り残高の変化（%）。未取得は推定しない",
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
