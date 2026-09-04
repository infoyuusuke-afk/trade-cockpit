#!/usr/bin/env python3
"""Fail publication when the cockpit's core identity/price gates regress."""

import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def close_enough(a, b):
    a, b = float(a), float(b)
    return math.isclose(a, b, rel_tol=0, abs_tol=max(.01, abs(a) * .00001))


def main():
    data = load("data.json")
    kio = load("kioxia_5m_calendar.json")
    catalysts = load("kioxia_catalysts.json")
    kio_history = load("kioxia_prediction_history.json")
    fx_study = load("fx_statement_study.json")
    live = load("live_focus.json")
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    errors = []

    quality = data.get("quality_gate") or {}
    market_date = quality.get("market_date")
    if quality.get("status") not in {"合格", "停止"}:
        errors.append("quality_gate.status is missing")
    if quality.get("status") == "合格" and not market_date:
        errors.append("verified market_date is missing")

    top = data.get("precision_top5") or []
    if len(top) > 5:
        errors.append(f"precision_top5 has {len(top)} rows")
    stocks = data.get("stocks") or {}
    for item in top:
        name, code = str(item.get("name") or ""), str(item.get("code") or "")
        match = re.search(r"（([0-9A-Z]{3,5})）$", name)
        if not match or match.group(1) != code:
            errors.append(f"identity mismatch in TOP5: {name} / {code}")
            continue
        stock = stocks.get(name) or {}
        if not stock.get("quote_verified") or not stock.get("identity_verified"):
            errors.append(f"unverified quote entered TOP5: {name}")
        if stock.get("data_date") != market_date or item.get("data_date") != market_date:
            errors.append(f"mixed market date in TOP5: {name}")
        if item.get("chart_last_close") is None or stock.get("price") is None:
            errors.append(f"missing chart/price comparison: {name}")
        elif not close_enough(item["chart_last_close"], stock["price"]):
            errors.append(f"chart close differs from price: {name}")
        if item.get("executable") and not item.get("supply_verified"):
            errors.append(f"executable without verified credit supply: {name}")

    yen = data.get("strong_yen_top5") or {}
    yen_top = yen.get("candidates") or []
    if len(yen_top) > 5:
        errors.append(f"strong_yen_top5 has {len(yen_top)} rows")
    for item in yen_top:
        name, code = str(item.get("name") or ""), str(item.get("code") or "")
        match = re.search(r"（([0-9A-Z]{3,5})）$", name)
        stock = stocks.get(name) or {}
        if not match or match.group(1) != code:
            errors.append(f"identity mismatch in strong-yen TOP5: {name} / {code}")
        if not stock.get("quote_verified") or stock.get("data_date") != market_date:
            errors.append(f"unverified quote entered strong-yen TOP5: {name}")
        if item.get("executable") and not (
            item.get("supply_verified") and item.get("supply_improved")
        ):
            errors.append(f"strong-yen execution without supply improvement: {name}")

    if kio.get("name") != "キオクシアHD（285A）" or kio.get("ticker") != "285A.T":
        errors.append("Kioxia identity is not fixed to 285A.T")
    if catalysts.get("name") != "キオクシアHD（285A）" or catalysts.get("ticker") != "285A.T":
        errors.append("Kioxia catalyst identity is not fixed to 285A.T")
    if kio_history.get("ticker") != "285A.T":
        errors.append("Kioxia prediction history identity mismatch")
    for item in catalysts.get("items") or []:
        if not str(item.get("source_url") or "").startswith(("https://www.kioxia.com/", "https://www.kioxia-holdings.com/", "https://ssl4.eir-parts.net/")):
            errors.append("Kioxia catalyst uses a non-primary source")
        if not item.get("verified") and item.get("trade_use") != "確認待ち・売買利用禁止":
            errors.append("unverified Kioxia catalyst is tradable")
    if len(kio.get("gap_studies") or []) != 7 or not kio.get("ma_playbook"):
        errors.append("Kioxia GU/GD study or MA playbook is missing")
    decision = kio.get("decision") or {}
    for key in ("grade", "tradable", "agreement", "dispersion", "reason", "invalidate"):
        if key not in decision:
            errors.append(f"Kioxia decision.{key} is missing")
    fx_summary = fx_study.get("summary") or {}
    if int(fx_summary.get("sample") or 0) < int(fx_summary.get("minimum_sample") or 10) and float(fx_summary.get("signal_score") or 0) != 0:
        errors.append("small-sample FX statement statistics altered the ranking")
    dates = [x.get("date") for x in fx_study.get("events", [])]
    if len(dates) != len(set(dates)):
        errors.append("FX statements were double-counted on the same date")
    if any(not x.get("source") for x in fx_study.get("events", [])):
        errors.append("FX statement event without a source")
    live_rows = live.get("rows") or {}
    if len(live_rows) > 11:
        errors.append(f"live focus exceeds bounded universe: {len(live_rows)}")
    kio_live = live_rows.get("285A") or {}
    if kio_live.get("ticker") != "285A.T" or "キオクシア" not in kio_live.get("name", ""):
        errors.append("live Kioxia identity mismatch")
    for key in ("forecast_status", "monitor_status", "trade_signal", "signal_reason",
                "attention_state", "attention_reason", "signal_key", "voice_message"):
        if key not in kio_live:
            errors.append(f"live Kioxia monitor field is missing: {key}")
    if kio_live.get("trade_signal") not in {"見送り", "売買禁止", "押し目買い候補", "戻り売り候補"}:
        errors.append("live Kioxia trade signal is invalid")
    for code, row in live_rows.items():
        if row.get("verified") and (row.get("price") is None or not row.get("chart")):
            errors.append(f"verified live row lacks price/chart: {code}")
    for marker in ("AIトレードコクピット Ver.5.2", "データ品質ゲート", "精査TOP5", "kio-decision-grade", "円高恩恵銘柄 TOP5", "要人発言イベントスタディ", "ザラバ5分更新", "音声OFF", "cockpitSpeak", "予測対実績・5分監視", "次の注意時間", "発動価格（成行禁止）", "kio-trade-signal", "timedPath", "GU／GD幅別", "材料レーダー", "kio-setup-type", "kio-audit-hit"):
        if marker not in html:
            errors.append(f"index.html missing marker: {marker}")
    yen_tab = html.find('data-tab="strong-yen"')
    secondary_tabs = html.find('<details class="secondary-tabs"')
    if yen_tab < 0:
        errors.append("top navigation is missing the strong-yen tab")
    elif secondary_tabs >= 0 and yen_tab > secondary_tabs:
        errors.append("strong-yen tab was demoted into secondary navigation")
    if '"kioxia-calendar","strong-yen"' not in html or 's.id==="strong-yen-top5"' not in html:
        errors.append("strong-yen tab routing is missing")

    if errors:
        raise SystemExit("PUBLICATION BLOCKED\n- " + "\n- ".join(errors))
    print(
        f"validation passed: market_date={market_date}, "
        f"precision_top5={len(top)}, verified={quality.get('verified', 0)}"
    )


if __name__ == "__main__":
    main()
