"""Build the official-source event calendar used by the trading cockpit.

Dates that create actual order flow are kept separate from announcement and
effective dates.  Unknown dates are deliberately blocked from trade use.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "event_calendar.json"
JST = ZoneInfo("Asia/Tokyo")


SOURCES = {
    "boj": ("日本銀行・金融政策決定会合", "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"),
    "fomc": ("Federal Reserve・FOMC calendar", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    "cpi": ("U.S. BLS・CPI release schedule", "https://www.bls.gov/schedule/news_release/cpi.htm"),
    "jobs": ("U.S. BLS・Employment Situation", "https://www.bls.gov/schedule/news_release/empsit.htm"),
    "bea": ("U.S. BEA・release schedule", "https://www.bea.gov/news/schedule"),
    "jpx_holiday": ("JPX・Holiday Trading", "https://www.jpx.co.jp/english/derivatives/rules/holidaytrading/"),
    "jpx_cash": ("JPX・内国株の売買制度", "https://www.jpx.co.jp/english/equities/trading/domestic/01.html"),
    "jpx_last": ("JPX・先物オプション最終取引日", "https://www.jpx.co.jp/english/derivatives/rules/last-trading-day/"),
    "ftse": ("FTSE Russell・review timing", "https://www.lseg.com/en/ftse-russell/indices/ftseall-world"),
    "nikkei": ("日経平均プロフィル・Guidebook", "https://indexes.nikkei.co.jp/nkave/archives/file/nikkei_stock_average_guidebook_en.pdf"),
    "topix": ("JPX・TOPIX見直し", "https://www.jpx.co.jp/english/markets/indices/revisions-indices/02.html"),
    "msci": ("MSCI・Index Review", "https://www.msci.com/indexes/index-resources/index-review"),
}


def event(event_id: str, title: str, day: str | None, category: str, source: str,
          *, time_jst: str = "終日", status: str = "公式確認済み",
          impact: str = "中", flow: str = "双方向", action: str = "確認のみ",
          announcement: str = "—", effective: str = "—", base: str = "—",
          actual_flow: str | None = None, block: bool = False, note: str = "") -> dict:
    source_name, source_url = SOURCES[source]
    return {
        "id": event_id, "title": title, "date": day, "category": category,
        "time_jst": time_jst, "status": status, "impact": impact,
        "expected_flow": flow, "action": action,
        "announcement_date": announcement, "base_date": base,
        "flow_date": actual_flow or day or "未確定", "effective_date": effective,
        "trade_block": block, "note": note,
        "source_name": source_name, "source_url": source_url,
    }


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def build() -> dict:
    now = datetime.now(JST)
    today = now.date()
    e: list[dict] = []

    # Monthly SQ: the second Friday.  SQ flow occurs at the opening, not close.
    for month, label in [(9, "メジャーSQ"), (10, "月例SQ"), (11, "月例SQ"), (12, "メジャーSQ")]:
        d = nth_weekday(2026, month, calendar.FRIDAY, 2).isoformat()
        e.append(event(f"sq-{month}", label, d, "日本需給", "jpx_last",
            time_jst="寄り付き", impact="高" if month in (9, 12) else "中",
            flow="寄り付きに先物・オプション精算需給（方向は事前断定不可）",
            action="寄り成行禁止。OR15確定まで往復ピンタを警戒",
            note="第2金曜の規則計算。休場変更時はJPX最終売買日を再確認。"))

    for d, title, action in [
        ("2026-09-04", "米雇用統計（8月）", "持ち越し半導体の数量を抑える"),
        ("2026-10-02", "米雇用統計（9月）", "発表前の米金利・ドル円方向賭けを避ける"),
        ("2026-11-06", "米雇用統計（10月）", "発表前の持ち越しを再点検"),
        ("2026-12-04", "米雇用統計（11月）", "発表前の持ち越しを再点検"),
    ]:
        e.append(event("jobs-" + d, title, d, "米経済", "jobs", time_jst="21:30",
            impact="高", flow="ドル円・米金利・NASDAQ経由で翌営業日に波及", action=action))

    for d, title in [("2026-09-11", "米CPI（8月）"), ("2026-10-14", "米CPI（9月）"),
                     ("2026-11-10", "米CPI（10月）"), ("2026-12-10", "米CPI（11月）")]:
        e.append(event("cpi-" + d, title, d, "米経済", "cpi", time_jst="21:30",
            impact="高", flow="米金利・ドル円・グロースのボラティリティ拡大",
            action="発表直前の新規持ち越し禁止。翌朝は気配を再判定"))

    for d, title, time in [("2026-09-17", "FOMC・SEP", "03:00"),
                           ("2026-10-29", "FOMC", "03:00"),
                           ("2026-12-10", "FOMC・SEP", "04:00")]:
        e.append(event("fomc-" + d, title, d, "中央銀行", "fomc", time_jst=time,
            impact="高", flow="発表後の米株・金利・為替が東京寄りへ波及",
            action="前夜持ち越しを縮小。東京寄りはOR15とVWAPを再確認",
            note="表示日は日本時間の声明公表日（米会合最終日の翌暦日）。"))

    for start, end, outlook in [("2026-09-17", "2026-09-18", False),
                                ("2026-10-29", "2026-10-30", True),
                                ("2026-12-17", "2026-12-18", False)]:
        title = f"日銀金融政策決定会合（{start[5:]}～{end[5:]}）" + ("・展望レポート" if outlook else "")
        e.append(event("boj-" + end, title, end, "中央銀行", "boj", time_jst="会合終了後",
            impact="高", flow="銀行・不動産・輸出株、日経先物、円相場へ波及",
            action="結果前の方向決め打ち禁止。公表後に先物・ドル円を確認",
            base=start, effective=end))

    for d, title in [("2026-09-30", "米PCE（8月）"), ("2026-10-29", "米GDP速報・PCE（9月）"),
                     ("2026-11-25", "米GDP改定・PCE（10月）")]:
        e.append(event("bea-" + d, title, d, "米経済", "bea", time_jst="21:30",
            impact="中", flow="米金利とグロース評価へ影響", action="持ち越し時だけ警戒"))

    # Actual passive flow and index-effective dates are explicitly separate.
    for d in ("2026-09-18", "2026-12-18"):
        e.append(event("ftse-" + d, "FTSE四半期レビュー実施", d, "指数入替", "ftse",
            time_jst="大引け", impact="高", flow="採用買い・除外売りの引け需給",
            action="対象銘柄と公式変更一覧を確認できた場合だけ引け需給へ対応",
            actual_flow=d, effective="翌営業日から反映",
            note="FTSE公式の『第3金曜引け後に実施』に基づく。買い一方向ではない。"))

    e.append(event("nikkei-2026-10", "日経平均・定期見直し反映", "2026-09-30", "指数入替", "nikkei",
        time_jst="大引け", status="規則から算出・要公式再確認", impact="高",
        flow="採用候補買い・除外候補売りの引け需給",
        action="構成銘柄の公式発表を確認するまで売買禁止",
        announcement="公式発表待ち", actual_flow="2026-09-30", effective="2026-10-01",
        block=True, note="10月第1営業日反映から逆算した需給候補日。正式発表で解除する。"))

    e.append(event("topix-2026-10", "TOPIX第1回定期見直し", None, "指数入替", "topix",
        status="日付未確定・売買利用禁止", impact="高", flow="採用・除外の双方向",
        action="JPXの実施日・構成銘柄発表まで材料視しない", effective="2026年10月",
        block=True, note="2026年10月実施のみ公式確認。正確な需給日は未入力。"))
    e.append(event("msci-2026-11", "MSCI 11月Index Review", None, "指数入替", "msci",
        status="日付未確認・売買利用禁止", impact="高", flow="採用買い・除外売り",
        action="MSCI公式の発表日とeffective date確認後にのみ解禁",
        announcement="未確認", effective="未確認", block=True,
        note="推測の日付を表示しない。"))

    for d, title, action in [
        ("2026-08-31", "月末リバランス", "買い需要と決めつけない。引け板・先物・TOPIXを確認"),
        ("2026-09-30", "月末・四半期末リバランス", "日経入替候補と通常リバランスを分ける"),
        ("2026-10-30", "月末リバランス", "引けの双方向フローを警戒"),
        ("2026-11-30", "月末リバランス", "引けの双方向フローを警戒"),
        ("2026-12-30", "年末・大納会", "薄商いと手仕舞い需給を警戒"),
    ]:
        e.append(event("monthend-" + d, title, d, "月末需給", "jpx_cash",
            time_jst="大引け", status="営業日規則・方向未確定", impact="中",
            flow="年金・投信・先物の双方向フロー。買いとは限らない", action=action,
            note="需給の方向は当日の先物・現物乖離と引け板で確認。"))

    for d in ("2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12", "2026-11-03"):
        e.append(event("holiday-" + d, "日本株休場／先物祝日取引あり", d, "休場", "jpx_holiday",
            impact="中", flow="現物休場中も先物が海外材料を織り込む",
            action="次の現物寄りでギャップ拡大を想定。先物終値を確認"))
    e.append(event("holiday-2026-11-23", "日本株・先物とも休場", "2026-11-23", "休場", "jpx_holiday",
        impact="中", flow="海外材料を次営業日にまとめて織り込む", action="持ち越し日数を確認"))

    e.sort(key=lambda x: (x["date"] or "9999-99-99", x["time_jst"], x["title"]))
    upcoming = [x for x in e if x["date"] and x["date"] >= today.isoformat()]
    today_events = [x for x in e if x["date"] == today.isoformat()]
    high_today = [x for x in today_events if x["impact"] == "高"]
    blocked = [x for x in e if x["trade_block"]]
    return {
        "updated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "today": today.isoformat(),
        "today_level": "高警戒" if high_today else ("注意" if today_events else "通常"),
        "today_rule": "イベント由来の方向を決め打ちしない。発表・実需確認後にOR15/VWAPで再判定。" if today_events else "通常ルール。OR15・VWAP・需給を確認。",
        "today_events": today_events,
        "upcoming": upcoming,
        "unverified": blocked,
        "events": e,
        "source_policy": "公式一次資料のみ。推定日は取引ブロックし、発表日・需給日・反映日を分離。",
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
