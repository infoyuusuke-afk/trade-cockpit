#!/usr/bin/env python3
"""JPX investor-flow point-in-time store and regime engine.

The public dashboard must fail closed: values are never invented, publication
time is the first successful observation of an official file, and a decision
may only use revisions observed by that decision time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")
ARCHIVE = ROOT / "data" / "jpx_investor"
MANIFEST = ARCHIVE / "manifest.json"
OUTPUT = ROOT / "investor_regime.json"
MODEL_VERSION = "investor-regime-1.1.0"

EQUITY_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/investor-type/index.html"
DERIVATIVE_PAGE = "https://www.jpx.co.jp/markets/statistics-derivatives/sector/index.html"

SUBJECT_ALIASES = {
    "foreign": ("海外投資家", "外国人"),
    "individual_cash": ("個人現金", "個人（現金）", "個人現金取引"),
    "individual_margin": ("個人信用", "個人（信用）", "個人信用取引"),
    "business_corporations": ("事業法人",),
    "investment_trusts": ("投資信託", "投信"),
    "trust_banks": ("信託銀行",),
    "proprietary": ("自己計", "証券自己", "自己"),
    "life_insurance": ("生保", "生命保険"),
    "non_life_insurance": ("損保", "損害保険"),
}
SUBJECT_LABELS = {
    "foreign": "海外", "individual_cash": "個人現金",
    "individual_margin": "個人信用", "business_corporations": "事業法人",
    "investment_trusts": "投資信託", "trust_banks": "信託銀行",
    "proprietary": "証券自己", "life_insurance": "生保",
    "non_life_insurance": "損保",
}


def iso(dt: datetime) -> str:
    return dt.astimezone(JST).isoformat(timespec="seconds")


def parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=JST)


def select_asof(records: list[dict], decision_at: datetime, dataset: str | None = None) -> dict | None:
    """Return the newest revision actually obtainable at decision_at."""
    eligible = []
    for row in records:
        if dataset and row.get("dataset") != dataset:
            continue
        try:
            observed = parse_dt(row["retrieved_at"])
        except (KeyError, TypeError, ValueError):
            continue
        if observed <= decision_at:
            eligible.append(row)
    return max(eligible, key=lambda r: (r.get("period_end", ""), r["retrieved_at"], r.get("revision", 0)), default=None)


def safe_z(current: float | None, history: Iterable[float | None], minimum: int = 13) -> float | None:
    values = [float(x) for x in history if x is not None and math.isfinite(float(x))]
    if current is None or len(values) < minimum:
        return None
    sd = statistics.stdev(values)
    if sd == 0:
        return None
    return round((float(current) - statistics.mean(values)) / sd, 4)


def signed_streak(values: list[float | None]) -> int | None:
    vals = [v for v in values if v is not None]
    if not vals or vals[-1] == 0:
        return None
    sign = 1 if vals[-1] > 0 else -1
    count = 0
    for value in reversed(vals):
        if value == 0 or (1 if value > 0 else -1) != sign:
            break
        count += 1
    return sign * count


def subject_metrics(weekly: list[dict], subject: str) -> dict:
    rows = sorted(weekly, key=lambda r: r.get("period_end", ""))
    nets = [r.get("subjects", {}).get(subject, {}).get("net") for r in rows]
    current = nets[-1] if nets else None
    previous = nets[-2] if len(nets) >= 2 else None
    z = safe_z(current, nets[-52:])
    prior_z = safe_z(previous, nets[-53:-1]) if len(nets) >= 2 else None

    def cumulative(window: int):
        vals = [x for x in nets[-window:] if x is not None]
        return sum(vals) if len(vals) == min(window, len(nets)) and vals else None

    def mean_and_deviation(window: int):
        vals = [x for x in nets[-window:] if x is not None]
        if not vals or len(vals) != min(window, len(nets)) or current is None:
            return None, None
        mean = statistics.mean(vals)
        return mean, current - mean

    gross = rows[-1].get("subjects", {}).get(subject, {}).get("gross") if rows else None
    market_turnover = rows[-1].get("market_turnover") if rows else None
    reversal = None
    if current is not None and previous is not None and current * previous < 0:
        reversal = "売→買" if current > 0 else "買→売"
    mean4, dev4 = mean_and_deviation(4)
    mean13, dev13 = mean_and_deviation(13)
    mean52, dev52 = mean_and_deviation(52)
    return {
        "subject": subject, "label": SUBJECT_LABELS[subject], "net": current,
        "previous_week_change": None if current is None or previous is None else current - previous,
        "cumulative_4w": cumulative(4), "cumulative_13w": cumulative(13),
        "cumulative_52w": cumulative(52),
        "mean_4w": mean4, "deviation_from_mean_4w": dev4,
        "mean_13w": mean13, "deviation_from_mean_13w": dev13,
        "mean_52w": mean52, "deviation_from_mean_52w": dev52,
        "z52": z,
        "flow_impulse": None if z is None or prior_z is None else round(z - prior_z, 4),
        "streak_weeks": signed_streak(nets), "reversal": reversal,
        "turnover_share_pct": None if gross is None or not market_turnover else round(gross / market_turnover * 100, 4),
        "nikkei225_alignment": None,
        "topix_alignment": None,
    }


def detect_regime(metrics: dict[str, dict], futures_alignment: dict | None = None) -> dict:
    """Transparent rule engine. Missing evidence lowers confidence."""
    f = metrics.get("foreign", {})
    cash = metrics.get("individual_cash", {})
    credit = metrics.get("individual_margin", {})
    corp = metrics.get("business_corporations", {})
    trust = metrics.get("trust_banks", {})
    candidates: list[tuple[str, float, list[str]]] = []

    def z(row): return row.get("z52")
    def imp(row): return row.get("flow_impulse")
    if z(f) is not None and z(f) >= 1 and f.get("net", 0) > 0:
        candidates.append(("FOREIGN RISK-ON", 3 + min(z(f), 3), ["海外買越", f"海外Z {z(f):+.2f}"]))
    if f.get("reversal") == "売→買" and imp(f) is not None and imp(f) > 0:
        candidates.append(("FOREIGN RE-ENTRY", 3 + min(imp(f), 3), ["海外が売越から買越へ反転", f"IMPULSE {imp(f):+.2f}"]))
    domestic = [x for x in (corp, trust) if x.get("net") is not None and x["net"] > 0]
    if len(domestic) == 2:
        candidates.append(("DOMESTIC SUPPORT", 4, ["事業法人と信託銀行がともに買越"]))
    if cash.get("reversal") == "売→買":
        candidates.append(("RETAIL REVERSAL", 3, ["個人現金が売越から買越へ反転"]))
    if z(credit) is not None and z(credit) >= 1 and credit.get("net", 0) > 0:
        candidates.append(("CREDIT SPECULATION", 3 + min(z(credit), 3), ["個人信用の買越が過熱", f"信用Z {z(credit):+.2f}"]))
    if f.get("net") is not None and f["net"] < 0 and cash.get("net") is not None and cash["net"] > 0:
        candidates.append(("DISTRIBUTION", 4, ["海外売越・個人現金買越の組合せ"]))
    risk_off_count = sum(1 for x in (f, trust) if x.get("net") is not None and x["net"] < 0)
    if risk_off_count == 2:
        candidates.append(("RISK-OFF", 4, ["海外と信託銀行がともに売越"]))
    if f.get("streak_weeks", 0) and f["streak_weeks"] >= 3 and z(credit) is not None and z(credit) >= 1.5:
        candidates.append(("LATE RISK-ON", 4, ["海外買越継続後に信用買いが過熱"]))

    if futures_alignment and futures_alignment.get("available"):
        aligned = futures_alignment.get("aligned")
        for i, (name, score, reasons) in enumerate(candidates):
            if name.startswith("FOREIGN"):
                candidates[i] = (name, score + (1 if aligned else -1), reasons + ["海外現物/先物 " + ("整合" if aligned else "不整合")])

    available = sum(1 for x in metrics.values() if x.get("net") is not None)
    if not candidates:
        return {"name": "判定不能" if available < 3 else "MIXED", "confidence": 0 if available < 3 else min(45, 20 + available * 2), "reasons": ["必要データ不足" if available < 3 else "単一レジームの条件未達"]}
    name, strength, reasons = max(candidates, key=lambda x: x[1])
    confidence = min(95, round(35 + available * 4 + strength * 5))
    return {"name": name, "confidence": confidence, "reasons": reasons}


def type_preferences(regime_name: str) -> tuple[list[str], list[str]]:
    table = {
        "FOREIGN RISK-ON": (["大型・高流動性", "半導体・電機・重工・金融", "TOPIX相対強度"], ["低流動性・信用買い過熱"]),
        "FOREIGN RE-ENTRY": (["大型・海外売上", "20日高値接近", "高売買代金"], ["寄り付き急騰・VWAP割れ"]),
        "DOMESTIC SUPPORT": (["低PBR・高ROE", "自社株買い", "大型バリュー"], ["業績裏付けのない高PER"]),
        "RETAIL REVERSAL": (["中小型・出来高加速", "グロース反転"], ["信用倍率悪化"]),
        "CREDIT SPECULATION": (["短期モメンタム（監視限定）"], ["信用買い急増・長い上髭"]),
        "DISTRIBUTION": (["低β・高流動性", "SHORTはVWAP/OR15確認"], ["高βグロースの押し目買い"]),
        "RISK-OFF": (["低β・ディフェンシブ", "SHORT候補"], ["半導体・高PER・信用買い過熱"]),
        "LATE RISK-ON": (["利確優先", "押し目確認後のみ"], ["高値追い・出来高過熱"]),
    }
    return table.get(regime_name, ([], []))


def score_with_regime(base_score: float, fit_points: float | None, sensitivity_points: float | None) -> dict:
    """One 30-point block prevents regime/sensitivity double counting."""
    fit = None if fit_points is None else max(0.0, min(20.0, float(fit_points)))
    sensitivity = None if sensitivity_points is None else max(0.0, min(10.0, float(sensitivity_points)))
    # Unknown components do not become zero observations; reserve the points.
    available = (fit or 0) + (sensitivity or 0)
    score = round(max(0, min(100, float(base_score) * 0.70 + available)), 1)
    return {"score": score, "base_70": round(float(base_score) * .70, 1), "regime_fit_20": fit, "sensitivity_10": sensitivity, "coverage": round((70 + (20 if fit is not None else 0) + (10 if sensitivity is not None else 0))), "learning_status": "学習不足" if sensitivity is None else "利用可"}


def directional_return(side: str, entry: float, exit_price: float, cost_bps: float = 0) -> float:
    raw = (exit_price / entry - 1) if side.upper() == "LONG" else (entry / exit_price - 1)
    return raw - cost_bps / 10000.0


def independent_week_count(dates: Iterable[str], horizon_days: int) -> int:
    unique = sorted({pd.Timestamp(x).date() for x in dates})
    kept = []
    for day in unique:
        if not kept or (day - kept[-1]).days >= max(7, horizon_days):
            kept.append(day)
    return len(kept)


def performance_metrics(samples: list[dict], horizon_days: int, minimum_weeks: int = 26) -> dict:
    """Evaluate one horizon without treating overlapping labels as independent."""
    usable = [x for x in samples if x.get("date") and x.get("return") is not None]
    usable.sort(key=lambda x: x["date"])
    independent = []
    last = None
    for row in usable:
        day = pd.Timestamp(row["date"]).date()
        if last is None or (day - last).days >= max(7, horizon_days):
            independent.append(row); last = day
    returns = [float(x["return"]) for x in independent]
    if len(returns) < minimum_weeks:
        return {"status": "学習不足", "sample_count": len(usable),
                "independent_weeks": len(returns), "minimum_weeks": minimum_weeks}
    gains = sum(x for x in returns if x > 0)
    losses = abs(sum(x for x in returns if x < 0))
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for ret in returns:
        equity *= 1 + ret
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
    return {"status": "利用可", "sample_count": len(usable),
            "independent_weeks": len(returns),
            "win_rate_pct": round(sum(x > 0 for x in returns) / len(returns) * 100, 2),
            "average_return_pct": round(statistics.mean(returns) * 100, 3),
            "profit_factor": None if losses == 0 else round(gains / losses, 3),
            "mfe_pct": _mean_optional(independent, "mfe"),
            "mae_pct": _mean_optional(independent, "mae"),
            "max_drawdown_pct": round(max_dd * 100, 3)}


def _mean_optional(rows: list[dict], key: str) -> float | None:
    values = [float(x[key]) for x in rows if x.get(key) is not None]
    return round(statistics.mean(values) * 100, 3) if values else None


def learn_sensitivity(flow: list[dict], returns: list[dict], subject: str,
                      minimum_weeks: int = 26, half_life_weeks: int = 26) -> dict:
    """Point-in-time weighted slope of excess return on subject flow Z.

    Caller must pass only observations available before the prediction date.
    """
    ret_by_date = {x.get("period_end"): x for x in returns}
    pairs = []
    for row in sorted(flow, key=lambda x: x.get("period_end", "")):
        result = ret_by_date.get(row.get("period_end"))
        z = row.get("subjects", {}).get(subject, {}).get("z52")
        excess = result.get("excess_return") if result else None
        if z is not None and excess is not None:
            pairs.append((float(z), float(excess)))
    if len(pairs) < minimum_weeks:
        return {"status": "学習不足", "sample_count": len(pairs), "beta": None,
                "minimum_weeks": minimum_weeks}
    weights = [math.exp(-math.log(2) * (len(pairs)-1-i) / half_life_weeks) for i in range(len(pairs))]
    sw = sum(weights); mx = sum(w*x for w,(x,_) in zip(weights,pairs))/sw
    my = sum(w*y for w,(_,y) in zip(weights,pairs))/sw
    den = sum(w*(x-mx)**2 for w,(x,_) in zip(weights,pairs))
    if den == 0:
        return {"status": "標準偏差ゼロ", "sample_count": len(pairs), "beta": None}
    beta = sum(w*(x-mx)*(y-my) for w,(x,y) in zip(weights,pairs))/den
    return {"status": "利用可", "sample_count": len(pairs), "beta": round(beta, 6),
            "half_life_weeks": half_life_weeks}


def _load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    try: return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception: return []


def _fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "TradeCockpit-JPX-PointInTime/1.0"})
    return urlopen(req, timeout=30).read()


def discover_official_files(page_url: str, extensions: tuple[str, ...]) -> list[str]:
    html = _fetch(page_url).decode("utf-8", "replace")
    links = re.findall(r'''href=["']([^"']+)["']''', html, re.I)
    return list(dict.fromkeys(urljoin(page_url, x) for x in links if x.lower().split("?", 1)[0].endswith(extensions)))


def _period_from_name(url: str) -> tuple[str | None, str | None]:
    dates = re.findall(r"20\d{6}", url)
    if len(dates) >= 2:
        return f"{dates[-2][:4]}-{dates[-2][4:6]}-{dates[-2][6:]}", f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}"
    # Legacy JPX weekly files use YYMMDD before the announced YYYYMMDD
    # filename migration.  Restrict matches to standalone six-digit tokens.
    short_dates = re.findall(r"(?<!\d)(\d{6})(?!\d)", url)
    if len(short_dates) >= 2:
        start, end = short_dates[-2:]
        return f"20{start[:2]}-{start[2:4]}-{start[4:]}", f"20{end[:2]}-{end[2:4]}-{end[4:]}"
    return None, None


def archive_official_files(now: datetime) -> list[dict]:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    known = {(r.get("source_url"), r.get("sha256")) for r in manifest}
    specs = [("equity", EQUITY_PAGE, (".xls", ".xlsx")), ("derivative", DERIVATIVE_PAGE, (".csv",))]
    for dataset, page, extensions in specs:
        try: links = discover_official_files(page, extensions)
        except Exception: continue
        for url in links[:12]:
            try: blob = _fetch(url)
            except Exception: continue
            digest = hashlib.sha256(blob).hexdigest()
            if (url, digest) in known: continue
            start, end = _period_from_name(url)
            if not end: continue
            suffix = Path(url.split("?", 1)[0]).suffix.lower()
            target = ARCHIVE / f"{dataset}_{end}_{digest[:12]}{suffix}"
            target.write_bytes(blob)
            revisions = [r for r in manifest if r.get("dataset") == dataset and r.get("period_end") == end]
            manifest.append({"dataset": dataset, "period_start": start, "period_end": end,
                "retrieved_at": iso(now), "published_confirmed_at": iso(now),
                "revision": len(revisions) + 1, "sha256": digest,
                "source_url": url, "local_file": str(target.relative_to(ROOT))})
            known.add((url, digest))
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _num(value):
    if value is None or (isinstance(value, float) and math.isnan(value)): return None
    text = str(value).replace(",", "").replace("▲", "-").strip()
    try: return float(text)
    except ValueError: return None


def parse_equity_workbook(path: Path, period_end: str) -> dict | None:
    """Parse JPX sheets conservatively; ambiguous rows remain missing."""
    try: sheets = pd.read_excel(path, sheet_name=None, header=None)
    except Exception: return None
    subjects: dict[str, dict] = {}
    market_turnover = None
    for frame in sheets.values():
        grid = frame.fillna("").astype(str)
        for ri, row in grid.iterrows():
            joined = " ".join(row.tolist()).replace(" ", "")
            key = next((k for k, aliases in SUBJECT_ALIASES.items() if any(a in joined for a in aliases)), None)
            if not key: continue
            nums = [_num(x) for x in row.tolist()]
            nums = [x for x in nums if x is not None]
            if len(nums) < 2: continue
            # Official layouts place sales/buys/net adjacently. Require the
            # third value to equal buy-sales within rounding tolerance.
            found = None
            for i in range(len(nums) - 2):
                sell, buy, net = nums[i:i+3]
                if abs((buy - sell) - net) <= max(2, abs(net) * .002):
                    found = (sell, buy, net)
            if found:
                sell, buy, net = found
                subjects[key] = {"sell": sell, "buy": buy, "net": net, "gross": sell + buy}
    if not subjects: return None
    return {"period_end": period_end, "subjects": subjects, "market_turnover": market_turnover}


def parse_derivative_csv(path: Path, period_end: str) -> dict | None:
    """Read overseas Nikkei 225 futures conservatively from JPX CSV.

    JPX changed the derivatives CSV layout in April 2026, so this parser uses
    header meaning rather than column position and returns missing when a
    required header cannot be identified.
    """
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return None
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return None
    header_index = next((i for i, row in enumerate(rows[:12])
                         if any("投資部門" in str(x) for x in row)
                         and any("売" in str(x) for x in row)
                         and any("買" in str(x) for x in row)), None)
    if header_index is None:
        return None
    header = [str(x).replace(" ", "") for x in rows[header_index]]

    def column(*terms):
        return next((i for i, name in enumerate(header)
                     if any(term in name for term in terms)), None)

    subject_col = column("投資部門")
    product_col = column("商品", "銘柄", "取引対象")
    sell_col = column("売り取引高", "売取引高", "売り", "売")
    buy_col = column("買い取引高", "買取引高", "買い", "買")
    net_col = column("差引", "ネット")
    if None in (subject_col, product_col, sell_col, buy_col):
        return None
    sell_total = buy_total = 0.0
    matched = 0
    for row in rows[header_index + 1:]:
        if max(subject_col, product_col, sell_col, buy_col) >= len(row):
            continue
        joined_subject = str(row[subject_col]).replace(" ", "")
        product = str(row[product_col]).replace(" ", "")
        if not any(x in joined_subject for x in ("海外", "外国")):
            continue
        if "日経225" not in product and "日経平均" not in product:
            continue
        sell, buy = _num(row[sell_col]), _num(row[buy_col])
        if sell is None or buy is None:
            continue
        if net_col is not None and net_col < len(row):
            net = _num(row[net_col])
            if net is not None and abs((buy - sell) - net) > max(2, abs(net) * .002):
                continue
        sell_total += sell
        buy_total += buy
        matched += 1
    if not matched:
        return None
    return {"period_end": period_end, "sell": sell_total, "buy": buy_total,
            "net": buy_total - sell_total, "matched_rows": matched}


def build_output(now: datetime, decision_at: datetime | None = None, fetch: bool = True) -> dict:
    manifest = archive_official_files(now) if fetch else _load_manifest()
    decision_at = decision_at or now
    chosen = select_asof(manifest, decision_at, "equity")
    weekly = []
    for record in manifest:
        if record.get("dataset") != "equity" or parse_dt(record["retrieved_at"]) > decision_at: continue
        parsed = parse_equity_workbook(ROOT / record["local_file"], record["period_end"])
        if parsed: weekly.append(parsed)
    # Keep only the newest observable revision for each week.
    weekly_by_end = {x["period_end"]: x for x in weekly}
    weekly = [weekly_by_end[k] for k in sorted(weekly_by_end)]
    metrics = {key: subject_metrics(weekly, key) for key in SUBJECT_ALIASES}
    derivative = select_asof(manifest, decision_at, "derivative")
    parsed_futures = None
    if derivative:
        parsed_futures = parse_derivative_csv(ROOT / derivative["local_file"], derivative["period_end"])
    foreign_net = metrics.get("foreign", {}).get("net")
    futures_net = parsed_futures.get("net") if parsed_futures else None
    futures = {
        "available": parsed_futures is not None,
        "status": "接続済み" if parsed_futures else ("CSV形式確認待ち" if derivative else "先物公式CSV未取得"),
        "source": derivative.get("source_url") if derivative else None,
        "period_end": derivative.get("period_end") if derivative else None,
        "retrieved_at": derivative.get("retrieved_at") if derivative else None,
        "foreign_nikkei225_futures_net": futures_net,
        "aligned": None if foreign_net is None or futures_net is None or foreign_net == 0 or futures_net == 0 else foreign_net * futures_net > 0,
    }
    regime = detect_regime(metrics, futures)
    tailwind, avoid = type_preferences(regime["name"])
    observed_weeks = len(weekly)
    output = {
        "model_version": MODEL_VERSION, "generated_at": iso(now), "decision_at": iso(decision_at),
        "source": {"equity_page": EQUITY_PAGE, "derivative_page": DERIVATIVE_PAGE,
            "definition_page": "https://www.jpx.co.jp/markets/statistics-equities/investor-type/07.html",
            "publication_rule": "毎週第4営業日15:30。実取得確認時刻を利用し、予定時刻では解禁しない。"},
        "asof": {"period_end": chosen.get("period_end") if chosen else None,
            "retrieved_at": chosen.get("retrieved_at") if chosen else None,
            "revision": chosen.get("revision") if chosen else None,
            "sha256": chosen.get("sha256") if chosen else None},
        "connection": {"equity": "接続済み" if weekly else "未取得", "derivative": futures["status"],
            "observed_weeks": observed_weeks},
        "regime": regime, "subjects": list(metrics.values()), "foreign_futures_alignment": futures,
        "learning": {"status": "利用可" if observed_weeks >= 52 else "学習不足",
            "minimum_independent_weeks": 26, "recent_window_weeks": 52,
            "time_decay_half_life_weeks": 26, "walk_forward": True,
            "overlap_guard": "翌日/3日/5日は各ホライズンで非重複週を別集計",
            "individual_stock_sensitivity": "未接続"},
        "stock_feature_schema": {
            "connected_existing": ["sector", "turnover", "volume_acceleration", "20d_high_position", "VWAP", "EMA", "OR15", "ATR", "margin_ratio", "margin_balance_change", "institutional_short"],
            "requires_verified_connection": ["size_bucket", "market_cap", "beta", "nikkei225_relative_strength", "topix_relative_strength", "growth_value", "ROE", "PBR", "buyback", "foreign_ownership", "overseas_sales", "lending_balance"],
            "policy": "未取得特徴はゼロ補完せず、採点にも使用しない。",
        },
        "type_filter": {"status": "利用可" if regime["name"] not in ("判定不能",) else "未適用",
            "tailwind": tailwind, "avoid": avoid, "note": "週次主体データは上位フィルターであり、ザラバ発動サインではありません。"},
        "warnings": ["市場全体集計から個別銘柄の買い主体を断定しません。", "欠測はゼロ補完しません。"],
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


if __name__ == "__main__":
    build_output(datetime.now(JST))
