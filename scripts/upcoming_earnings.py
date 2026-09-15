"""
upcoming_earnings.py

ユーザー依頼「明日以降の当日注目を浴びそうな決算銘柄を、ChatGPTと方向を検討しながら
AIコクピットに実装してほしい」への対応。

データソース: JPX（東証）公式「翌営業日決算発表予定会社」
  https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html
  （認証不要・毎営業日17時頃更新・上場会社からの連絡に基づく公式情報）

正直な制約（表示前に必ず理解しておくこと）:
- JPXのこのページは「翌営業日」分のみを提供しており、2日以上先の確定リストは
  無料の公式ソースからは取得できない。「明日以降」という依頼のうち、確実に
  取得できるのは実質「翌営業日」分のみ。
- 対象は3月期・9月期決算会社の本決算・四半期決算のみ（JPXの説明どおり）。
  全上場企業の決算を網羅するものではなく、四半期末のタイミング次第で
  「該当銘柄なし」の日も多い（季節性がある）。
- direction（方向性スコア）は「決算内容そのものの予測」では断じてない。
  直近5日/20日の株価モメンタムのみに基づく仮説的な参考値で、増減益・ガイダンス・
  市場コンセンサスは一切考慮していない。決算の中身によって株価は逆方向に
  動くことが普通にある。
- resolved_n（結果が判明した予想件数）がMIN_N件に達するまでは
  reliability_report.pyと同じ考え方で「試運転・検証中」と明記し、
  的中率が確立した手法であるかのような表示はしない。
- ChatGPTとの「予想」はこのスクリプト単体では完結しない。ここで作る銘柄リストと
  モメンタムレーンを docs/AI_SHARED_SHEET.md 経由でChatGPTへ共有し、決算内容・
  会社側ガイダンス等を踏まえた定性的な検討コメントを別途依頼する運用とする。
"""
from __future__ import annotations

import io
import json
import re
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - requirements.txtに常時含まれる想定
    yf = None

JST = timezone(timedelta(hours=9))
URL = "https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html"
OUT = Path("upcoming_earnings.json")
LOG_PATH = Path("data/earnings_predictions_log.json")
WATCHLIST_PATH = Path("ms2_live/watchlist_100.json")
MIN_N = 20  # 銘柄横断で件数が貯まりやすいため既存のreliability_report.py(n=30)より緩めの暫定値。試運転扱いは同じ考え方で維持する。

CODE_RE = re.compile(r"\b(\d{4}|\d{3}[A-Z])\b")


DIAGNOSTICS: list[dict] = []


def record(stage: str, **details) -> None:
    item = {"stage": stage, **details}
    DIAGNOSTICS.append(item)
    print("[earnings] " + json.dumps(item, ensure_ascii=False), flush=True)


def save_evidence(name: str, html: str) -> None:
    path = Path("artifacts/upcoming-earnings") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def fetch_html(url: str) -> str:
    record("jpx_http", status="started", url=url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (trade-cockpit-earnings-check/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        save_evidence("raw.html", html)
        record("jpx_http", status="success", http_status=resp.status, characters=len(html))
        return html


def fetch_html_rendered(url: str) -> str:
    """JPXのページはJavaScriptで表を描画するため、素のHTMLだけでは0件抽出になることが
    margin_caution_check.py の実行結果で既に確認済み。同じPlaywrightフォールバックを使う。"""
    record("playwright", status="started", url=url)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if response is None or not response.ok:
            raise RuntimeError(f"Playwright HTTP error: {response.status if response else 'no response'}")
        page.wait_for_timeout(2_000)
        html = page.content()
        browser.close()
        save_evidence("rendered.html", html)
        record("playwright", status="success", http_status=response.status, characters=len(html))
        return html


def parse_companies(html: str) -> list[dict]:
    record("pandas.read_html", status="started")
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError as exc:
        record("pandas.read_html", status="no_tables", exception=type(exc).__name__, message=str(exc))
        return []
    record("pandas.read_html", status="success", tables=len(tables))
    companies: list[dict] = []
    for df in tables:
        cols = [str(c) for c in df.columns]
        if not any("コード" in c for c in cols):
            continue
        code_col = next((c for c in cols if "コード" in c), None)
        name_col = next((c for c in cols if "会社名" in c or "銘柄" in c), None)
        if code_col is None or name_col is None:
            continue
        for _, row in df.iterrows():
            code_val = str(row.get(code_col, "")).strip()
            m = CODE_RE.search(code_val)
            if not m:
                continue
            companies.append({"code": m.group(1), "name": str(row.get(name_col, "")).strip()})
    record("parse_companies", status="success", companies=len(companies))
    return companies


def load_watch_universe() -> set[str]:
    """既存の100銘柄ウォッチリストのコード集合。『注目を浴びそう』の目安の一つとして使う。"""
    if not WATCHLIST_PATH.exists():
        return set()
    try:
        data = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8"))
        codes = set()
        for _, v in data.get("stocks", {}).items():
            ticker = str(v.get("ticker", ""))
            codes.add(ticker.split(".")[0])
        return codes
    except Exception:
        return set()


def momentum_lean(code: str) -> dict:
    """直近モメンタムに基づく仮説的な方向レーン。決算内容そのものの予測ではない。"""
    if yf is None:
        return {"available": False, "reason": "yfinance未導入"}
    ticker = code + ".T"
    try:
        raw = yf.download(ticker, period="30d", interval="1d", auto_adjust=False, progress=False)
        if raw is None or raw.empty or len(raw) < 6:
            return {"available": False, "reason": "価格データ不足"}
        closes = raw["Close"].dropna()
        if hasattr(closes, "squeeze"):
            closes = closes.squeeze()
        last = float(closes.iloc[-1])
        ret5 = (last / float(closes.iloc[-6]) - 1) * 100 if len(closes) >= 6 else None
        ret20 = (last / float(closes.iloc[-21]) - 1) * 100 if len(closes) >= 21 else None
        lean_source = ret5 if ret5 is not None else ret20
        if lean_source is None:
            direction = "中立"
        elif lean_source >= 2:
            direction = "上昇レーン（モメンタムのみ・決算内容は未考慮）"
        elif lean_source <= -2:
            direction = "下落レーン（モメンタムのみ・決算内容は未考慮）"
        else:
            direction = "中立"
        return {
            "available": True,
            "last_close": round(last, 1),
            "return_5d_pct": round(ret5, 2) if ret5 is not None else None,
            "return_20d_pct": round(ret20, 2) if ret20 is not None else None,
            "momentum_direction": direction,
        }
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)}


def load_log() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_log(log: list[dict]) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_pending(log: list[dict]) -> list[dict]:
    """target_dateを過ぎた過去の予想について、実際の値動きを取得し的中判定を確定する。"""
    if yf is None:
        return log
    today = datetime.now(JST).date()
    for entry in log:
        if entry.get("status") != "pending":
            continue
        try:
            target = datetime.strptime(entry["target_date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if target >= today:
            continue  # まだ結果が出る日を迎えていない
        ticker = entry["code"] + ".T"
        try:
            raw = yf.download(ticker, period="10d", interval="1d", auto_adjust=False, progress=False)
            if raw is None or raw.empty:
                continue
            raw = raw[raw.index.date >= target]
            if len(raw) < 2:
                continue
            before = float(raw["Close"].iloc[0])
            after = float(raw["Close"].iloc[1])
            actual_pct = (after / before - 1) * 100
            actual_direction = "上昇" if actual_pct > 0.5 else ("下落" if actual_pct < -0.5 else "中立")
            predicted = entry.get("momentum_direction", "")
            hit = (
                ("上昇" in predicted and actual_direction == "上昇")
                or ("下落" in predicted and actual_direction == "下落")
                or (predicted == "中立" and actual_direction == "中立")
            )
            entry["status"] = "resolved"
            entry["actual_return_pct"] = round(actual_pct, 2)
            entry["actual_direction"] = actual_direction
            entry["hit"] = hit
        except Exception:  # noqa: BLE001
            continue
    return log


def main():
    DIAGNOSTICS.clear()
    record("main", status="started")
    fetch_error = None
    companies: list[dict] = []
    try:
        html = fetch_html(URL)
        companies = parse_companies(html)
        if not companies:
            record("fallback", status="triggered", reason="raw HTML yielded zero companies")
            html = fetch_html_rendered(URL)
            companies = parse_companies(html)
        else:
            record("fallback", status="skipped", reason="raw HTML yielded companies")
        if not companies:
            if "翌営業日の開示予定会社はございません" not in html:
                raise RuntimeError("No companies parsed and JPX explicit no-company notice not found")
            record("source_result", status="confirmed_empty", reason="JPX explicit no-company notice")
        else:
            record("source_result", status="success", companies=len(companies))
    except Exception as e:  # noqa: BLE001
        fetch_error = f"{type(e).__name__}: {e}"
        record("source_result", status="failed", exception=type(e).__name__, message=str(e))
        traceback.print_exc()

    watch_universe = load_watch_universe()
    tomorrow = (datetime.now(JST) + timedelta(days=1)).strftime("%Y-%m-%d")

    picks = []
    log = load_log()
    existing_keys = {(e.get("code"), e.get("target_date")) for e in log}
    for c in companies:
        momentum = momentum_lean(c["code"])
        watched = c["code"] in watch_universe
        picks.append({
            "code": c["code"],
            "name": c["name"],
            "target_date": tomorrow,
            "in_existing_watchlist": watched,
            **momentum,
        })
        key = (c["code"], tomorrow)
        if key not in existing_keys and momentum.get("available"):
            log.append({
                "code": c["code"],
                "name": c["name"],
                "target_date": tomorrow,
                "logged_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
                "momentum_direction": momentum.get("momentum_direction"),
                "return_5d_pct": momentum.get("return_5d_pct"),
                "status": "pending",
            })

    log = resolve_pending(log)
    save_log(log)

    resolved = [e for e in log if e.get("status") == "resolved"]
    n = len(resolved)
    hits = sum(1 for e in resolved if e.get("hit"))
    hit_rate = round(hits / n * 100, 1) if n else None

    out = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": URL,
        "source_note": (
            "JPX公式『翌営業日決算発表予定会社』。3月期・9月期決算会社の本決算・四半期決算のみが対象。"
            "2日以上先の確定リストは無料の公式ソースからは取得できない。"
        ),
        "fetch_error": fetch_error,
        "diagnostics": DIAGNOSTICS,
        "target_date": tomorrow,
        "picks": picks,
        "direction_score_note": (
            "momentum_directionは決算内容そのものの予測ではなく、直近5日/20日の株価モメンタムのみに基づく"
            "仮説的な参考値。ChatGPTへ別途この銘柄リストを共有し、決算内容・ガイダンスを踏まえた定性的な"
            "検討コメントを依頼する運用とする。"
        ),
        "validation": {
            "resolved_n": n,
            "hit_rate_pct": hit_rate,
            "min_n_threshold": MIN_N,
            "status": "参考値（要検証）" if n >= MIN_N else "試運転・検証中（サンプル不足）",
        },
    }
    record("json_output", status="success", files=[str(OUT), str(LOG_PATH)],
           picks=len(picks), prediction_records=len(log))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if fetch_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
