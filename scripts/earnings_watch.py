"""scripts/earnings_watch.py

決算発表後の監視候補（docs/C-031-GPT_STRATEGY_ROADMAP.md P1「決算発表後の監視候補」、
第4節の仕様への対応）。

データ源はC-030で統合した`earnings_calendar.py`（`earnings_calendar.json`）に一本化する
（旧パイプラインは復活させない、ロードマップ第4節の明記事項）。出力を
pre_event_watch（発表前の参考監視）/post_event_bias（材料判定はできたが売買候補には
未達）/trade_candidate（LONG/SHORT/WAITまで判定）の3段階に分離する。

このファイルはC-032の`signal_contract.py`の共通スキーマ（`build_signal`）で
出力を組み立て、C-036の`regime_policy.py`が出す`market_regime.json`の確定地合いを
参照する。地合いが未反映（ワークフロー未実行）の間はUNKNOWN扱いとなり、
trade_candidateはWAITに留まる（架空の地合いで候補を出さない）。

正直な制約（実装時点で未接続・簡略化した部分）:
  - 発表内容の数値判定：ロードマップが求める g=(new-old)/abs(old) という実際の決算数値
    比較は未実装。TDnet開示PDF・決算短信本文からの財務数値抽出が必要で、今回は
    earnings_calendar.pyの既存キーワード分類（analysis.label: 発表済み好材料あり／
    警戒材料あり／関連開示を確認／未発表・期待判断の根拠不足）を代理指標として使う。
    表題ベースの分類であり、本文の数値そのものを見た判定ではないことを明示する。
  - PTS反応：本来はMS2 RSS PC側の実約定データ（C-028のIR動的追跡）が最も正確だが、
    クラウド側のこのスクリプトはPC側データに接続できない。yfinanceで取得できる
    直近の日次終値の変化を代理指標として使う（真のPTS約定データではない）。
  - 証券会社の売禁・在庫・借株費用・価格規制の確認は未接続。SHORT方向は判定ロジック
    自体は通っても、常にblock_reasonが付き最終的にはWAIT扱いとする（確認できない
    条件を満たしたことにしない）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import signal_contract as sc

ROOT = Path(__file__).resolve().parents[1]
EARNINGS_CALENDAR_PATH = ROOT / "earnings_calendar.json"
REGIME_PATH = ROOT / "market_regime.json"
OUT_PATH = ROOT / "earnings_watch.json"

REACTION_THRESHOLD_PCT = 2.0  # C-031-GPT第4節: 有効PTS>=+2%/-2%
LOOKBACK_DAYS = 2  # 発表から何日以内を「直近」として対象にするか（v1の簡易範囲）

BIAS_LABEL_MAP = {
    "発表済み好材料あり": "POSITIVE",
    "警戒材料あり": "NEGATIVE",
    "関連開示を確認": "NEUTRAL",
    "未発表・期待判断の根拠不足": "NEUTRAL",
}


def classify_material_proxy(label: Optional[str]) -> str:
    """earnings_calendar.pyのanalysis.labelをPOSITIVE/NEGATIVE/NEUTRALへ写像する代理指標。
    実際の決算数値比較ではない（ファイル先頭のdocstring参照）。"""
    return BIAS_LABEL_MAP.get(label, "NEUTRAL")


def classify_stage(bias: str, reaction_pct: Optional[float], regime: Optional[str]) -> tuple[str, str, list[str]]:
    """C-031-GPT第4節の3段階分類。戻り値: (stage, candidate_direction, block_reasons)。
    stage: pre_event_watch | post_event_bias | trade_candidate
    candidate_direction: LONG | SHORT | WAIT（方向として有望かどうかの参考値であり、
    実行可能なシグナルではない。実行可否は block_reasons の有無で判断する。
    例えばSHORTは売禁・在庫等が未確認のため、stage="trade_candidate"・
    candidate_direction="SHORT"でもblock_reasonsに"short_eligibility_unconfirmed"が
    必ず入る。呼び出し側はside="WAIT"固定でsignal_contract.build_signalへ渡すこと
    （entry/stopを持たないためLONG/SHORTのまま渡すとbuild_signalの検証で例外になる）。
    """
    if bias not in ("POSITIVE", "NEGATIVE"):
        return "pre_event_watch", "WAIT", ["bias_not_directional"]

    if reaction_pct is None:
        return "post_event_bias", "WAIT", ["reaction_data_insufficient"]

    if bias == "POSITIVE" and reaction_pct >= REACTION_THRESHOLD_PCT:
        candidate_side = "LONG"
    elif bias == "NEGATIVE" and reaction_pct <= -REACTION_THRESHOLD_PCT:
        candidate_side = "SHORT"
    else:
        # 材料の方向と反応が逆、または閾値未達。C-031-GPT: 逆反応はWAIT。
        return "post_event_bias", "WAIT", ["reaction_below_threshold_or_reversed"]

    if regime not in ("UP", "DOWN"):
        return "post_event_bias", "WAIT", ["regime_unknown"]
    if candidate_side == "LONG" and regime != "UP":
        return "post_event_bias", "WAIT", ["regime_not_up"]
    if candidate_side == "SHORT" and regime != "DOWN":
        return "post_event_bias", "WAIT", ["regime_not_down"]

    if candidate_side == "SHORT":
        # C-031-GPT第4節: 証券会社の対象商品・売禁・在庫・借株費用・価格規制適合が
        # 現在確認済みであることがSHORT候補の条件。この接続が無い間は確認できたことに
        # しない＝方向はSHORTのまま返すが、block_reasonsで実行不可を明示する。
        return "trade_candidate", "SHORT", ["short_eligibility_unconfirmed"]

    return "trade_candidate", candidate_side, []


def fetch_reaction_pct(ticker: str, event_date) -> Optional[float]:
    """発表日より前の直近終値を基準に、直近終値までの変化率(%)を代理指標として返す。
    真のPTS約定反応ではない（ファイル先頭のdocstring参照）。取得失敗時はNone。"""
    import yfinance as yf
    try:
        df = yf.download(ticker, period="15d", interval="1d", auto_adjust=False, progress=False)
        if df is None or len(df) < 2:
            return None
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = [c[0] for c in df.columns]
        closes = df["Close"]
        dates = [d.date() for d in df.index]
        before = [(d, c) for d, c in zip(dates, closes) if d < event_date]
        if not before:
            return None
        reference_close = float(before[-1][1])
        latest_close = float(closes.iloc[-1])
        if reference_close <= 0:
            return None
        return (latest_close / reference_close - 1) * 100
    except Exception:
        return None


def main():
    now = sc.now_jst()
    today = now.date()

    ec = {}
    if EARNINGS_CALENDAR_PATH.exists():
        try:
            ec = json.loads(EARNINGS_CALENDAR_PATH.read_text(encoding="utf-8"))
        except Exception:
            ec = {}
    calendar = ec.get("calendar", [])

    regime_data = {}
    if REGIME_PATH.exists():
        try:
            regime_data = json.loads(REGIME_PATH.read_text(encoding="utf-8"))
        except Exception:
            regime_data = {}
    confirmed_regime = regime_data.get("confirmed_regime")
    regime_updated_at = regime_data.get("updated_at")

    results = []
    for event in calendar:
        date_text = event.get("date")
        if not date_text:
            continue
        try:
            event_date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except Exception:
            continue
        if not (today - timedelta(days=LOOKBACK_DAYS) <= event_date <= today):
            continue

        analysis = event.get("analysis") or {}
        label = analysis.get("label")
        bias = classify_material_proxy(label)
        code = event.get("code")
        ticker = f"{code}.T" if code else None

        reaction_pct = None
        if bias in ("POSITIVE", "NEGATIVE") and ticker:
            reaction_pct = fetch_reaction_pct(ticker, event_date)

        stage, candidate_direction, block_reasons = classify_stage(bias, reaction_pct, confirmed_regime)

        # build_signalのsideは「具体的なentry/stopを伴う執行可能なシグナル」を表す契約のため、
        # このモジュールはentry/stop（デイトレTOP5のセットアップ判定、別のP1項目）をまだ
        # 持たない。candidate_directionは「方向としての有望さ」を示す参考メタデータとして
        # 別フィールドに残し、schema側のsideは常にWAITのまま出力する
        # （執行可能であるかのように見せない）。
        signal = sc.build_signal(
            horizon="EARNINGS_WATCH",
            code=code,
            side="WAIT",
            strategy_id="earnings_watch_v1",
            decision_asof=now,
            source_quality="proxy" if bias != "NEUTRAL" else "n/a",
            regime=confirmed_regime,
            flags=[stage],
            eligibility=stage,
            block_reasons=block_reasons,
            entry=None, stop=None, target=None,
            policy_version="v1",
        )
        results.append({
            "code": code,
            "name": event.get("name"),
            "event_date": date_text,
            "material_label": label,
            "material_bias_proxy": bias,
            "reaction_pct_proxy": round(reaction_pct, 2) if reaction_pct is not None else None,
            "stage": stage,
            "candidate_direction": candidate_direction,
            "signal": signal,
        })

    out = {
        "schema_version": "earnings-watch-1.0",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "regime_reference": {
            "confirmed_regime": confirmed_regime,
            "regime_updated_at": regime_updated_at,
            "note": "regime_policy.pyの実行ワークフロー未反映の間はnull（UNKNOWN扱い）になる",
        },
        "lookback_days": LOOKBACK_DAYS,
        "reaction_threshold_pct": REACTION_THRESHOLD_PCT,
        "note": ("material_bias_proxyはearnings_calendar.pyの表題キーワード分類による代理指標"
                 "（決算本文の数値比較ではない）。reaction_pct_proxyはyfinance日次終値ベースの"
                 "代理指標（真のPTS約定データではない）。SHORT方向はtrade_candidate段階まで"
                 "進んでも証券会社の売禁・在庫等が未確認のため常にWAIT。"),
        "candidates": results,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"earnings_watch.json written: {len(results)} candidates evaluated")


if __name__ == "__main__":
    main()
