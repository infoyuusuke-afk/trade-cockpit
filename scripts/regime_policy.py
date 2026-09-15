"""scripts/regime_policy.py

地合い共通判定エンジン（docs/C-031-GPT_STRATEGY_ROADMAP.md P1「地合い共通判定」、
第3節の仕様への対応）。

このファイルは「判定ロジック（純粋関数・外部通信なし）」と「main()のデータ取得・
状態永続化」を分離している。前者はtests/test_regime_policy.pyで合成データにより
検証済み。後者（yfinance経由のTOPIX 5分足取得・監視母集団のブレッドス計算）は
実行環境依存であり、GitHub Actions上での実行結果が実質的な初検証になる。

正直な制約（実装時点で未接続の部分）:
  - HIGH_VOL: 実装済み（直近60営業日の同時間帯5分リターン分布の95%点との比較）。
  - RATE_SHOCK: 未実装（米/日10年金利の日次変化データを別途接続する必要がある）。
    常にFalseを返す。
  - POLICY_EVENT: 未実装（関税・輸出規制等の確認済み発表の分類が必要）。常にFalseを返す。
  - breadth（固定監視母集団の前日比上昇比率）: 本来はMS2 RSSのPC側ライブ気配を使うのが
    最も正確だが、GitHub Actions（クラウド側）はPC側のリアルタイムデータに接続できない。
    このv1では ms2_live/watchlist_100.json の100銘柄をyfinanceの日次終値で代替計算する
    （実行タイミングの終値に対する当日値のみ・真の日中5分足ブレッドスではない、
    という制約を明示する）。真の日中ブレッドスが必要になった場合は、MS2 RSS側から
    このクラウド側へブレッドス値だけを公開する仕組みを別途検討する。
  - TOPIXの日中系列は 1306.T（NEXT FUNDS TOPIX連動型上場投信）で代替する
    （watchlist_100.jsonの既存の慣習と同じ）。真の指数系列そのものではない。
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
STATE_PATH = ROOT / "data" / "regime_state.json"
OUT_PATH = ROOT / "market_regime.json"
EVENT_CALENDAR_PATH = ROOT / "event_calendar.json"
WATCHLIST_PATH = ROOT / "ms2_live" / "watchlist_100.json"

TOPIX_PROXY_TICKER = "1306.T"  # watchlist_100.jsonの慣習と同じ代替ティッカー

MIN_HOLD_MINUTES = 15
CONFIRM_COUNT = 2  # 10分（5分足2回連続）

# C-031-GPT第3節: 状態ごとに許可するセットアップとリスク倍率。
REGIME_POLICY = {
    "UP": {"allowed": ["LONG_TREND", "LONG_PULLBACK"], "watch_only": ["SHORT"], "risk_multiplier": 1.0},
    "DOWN": {"allowed": ["SHORT_TREND", "SHORT_BOUNCE"], "watch_only": ["LONG"], "risk_multiplier": 0.5},
    "RANGE": {"allowed": [], "watch_only": ["LONG", "SHORT"], "risk_multiplier": 0.0},
    "UNKNOWN": {"allowed": [], "watch_only": [], "risk_multiplier": 0.0},
    "EVENT_LOCK": {"allowed": [], "watch_only": [], "risk_multiplier": 0.0},
}


def classify_base_regime(price: Optional[float], vwap: Optional[float],
                          ema20_last3: list[float], breadth_up_ratio: Optional[float],
                          data_ok: bool = True) -> str:
    """C-031-GPT第3節の基礎地合い判定（UP/DOWN/RANGE/UNKNOWN）。
    ema20_last3は直近3本の5分EMA20値（古い→新しい順）。
    必須値・完成5分足3本・ブレッドスのいずれかが欠けていればUNKNOWN
    （架空の値で埋めない）。
    """
    if not data_ok or price is None or vwap is None or breadth_up_ratio is None:
        return "UNKNOWN"
    if len(ema20_last3) < 3 or any(v is None for v in ema20_last3):
        return "UNKNOWN"
    ema_rising = ema20_last3[0] < ema20_last3[1] < ema20_last3[2]
    ema_falling = ema20_last3[0] > ema20_last3[1] > ema20_last3[2]
    if price > vwap and ema_rising and breadth_up_ratio >= 60:
        return "UP"
    if price < vwap and ema_falling and breadth_up_ratio <= 40:
        return "DOWN"
    return "RANGE"


def event_lock_active(events: list[dict], decision_asof: datetime) -> tuple[bool, Optional[str]]:
    """C-031-GPT第5節: Aランクイベントの通知時点T-10分〜T+15分は新規停止（EVENT_LOCK）。
    scheduled_at_utcを持たない（時刻確度がexactでない）イベントは対象にしない
    （架空の時刻を基準にロックしない）。"""
    for e in events:
        if e.get("tier") != "A":
            continue
        scheduled = e.get("scheduled_at_utc")
        if not scheduled:
            continue
        try:
            t = datetime.fromisoformat(scheduled)
        except ValueError:
            continue
        if t - timedelta(minutes=10) <= decision_asof <= t + timedelta(minutes=15):
            return True, e.get("event_id")
    return False, None


def high_vol_active(current_abs_return_pct: Optional[float],
                     historical_same_slot_abs_returns_pct: list[float]) -> bool:
    """C-031-GPT第3節: 完成5分足リターンの絶対値が、直近60営業日の同時間帯分布の
    95百分位を超えたらHIGH_VOL。履歴が無ければFalse（未検証をtrue扱いしない）。"""
    if current_abs_return_pct is None or len(historical_same_slot_abs_returns_pct) < 20:
        return False
    sorted_hist = sorted(historical_same_slot_abs_returns_pct)
    idx = min(len(sorted_hist) - 1, int(len(sorted_hist) * 0.95))
    threshold = sorted_hist[idx]
    return current_abs_return_pct > threshold


def rate_shock_active() -> bool:
    """未実装。米/日10年金利の日次変化データの接続が必要（正直な未接続の明示）。"""
    return False


def policy_event_active() -> bool:
    """未実装。関税・輸出規制等の確認済み発表の分類が必要（正直な未接続の明示）。"""
    return False


def resolve_raw_regime(base_regime: str, event_locked: bool, high_vol: bool) -> str:
    """C-031-GPT第3節: 優先順＝データ/売買不可ゲート＞EVENT_LOCK＞HIGH_VOL＞UP/DOWN/RANGE。
    HIGH_VOLは別regimeへ置き換えず、フラグとして基礎地合いに重ねる想定だが、
    optional_flagsで表現するためbase_regime自体は変えない（呼び出し側はoutputの
    flagsを見てリスク倍率を追加で絞る）。UNKNOWN/EVENT_LOCKだけがbase_regimeを
    上書きする特別扱い。"""
    if base_regime == "UNKNOWN":
        return "UNKNOWN"
    if event_locked:
        return "EVENT_LOCK"
    return base_regime


def apply_hysteresis(state: dict, raw_regime: str, decision_asof: datetime,
                      min_hold_minutes: int = MIN_HOLD_MINUTES,
                      confirm_count: int = CONFIRM_COUNT) -> dict:
    """C-031-GPT第3節: 通常切替は同じ新判定が2回連続（10分）で成立してから、
    最短保持15分。UNKNOWN・EVENT_LOCKへの切替は即時。解除は必須値が正常かつ
    2回連続正常が必要（=通常切替ルールへ戻るだけで良い。次にUP/DOWN/RANGEが
    2回連続で出れば通常ルートで切り替わる）。既存保有のストップは緩めない
    （このモジュールはポジション管理を持たないため対象外）。
    """
    confirmed = state.get("confirmed_regime")

    if raw_regime in ("UNKNOWN", "EVENT_LOCK"):
        if confirmed != raw_regime:
            return {
                "confirmed_regime": raw_regime, "confirmed_at": decision_asof.isoformat(),
                "candidate_regime": None, "candidate_streak": 0, "candidate_first_at": None,
            }
        return state

    if confirmed is None:
        return {
            "confirmed_regime": raw_regime, "confirmed_at": decision_asof.isoformat(),
            "candidate_regime": None, "candidate_streak": 0, "candidate_first_at": None,
        }

    if raw_regime == confirmed:
        return {
            "confirmed_regime": confirmed, "confirmed_at": state.get("confirmed_at"),
            "candidate_regime": None, "candidate_streak": 0, "candidate_first_at": None,
        }

    confirmed_at = datetime.fromisoformat(state["confirmed_at"])
    held_minutes = (decision_asof - confirmed_at).total_seconds() / 60
    if held_minutes < min_hold_minutes:
        # 最短保持時間内は切替候補としてもカウントしない（安全側）。
        return state

    new_state = dict(state)
    if state.get("candidate_regime") == raw_regime:
        new_state["candidate_streak"] = state.get("candidate_streak", 0) + 1
    else:
        new_state["candidate_regime"] = raw_regime
        new_state["candidate_streak"] = 1
        new_state["candidate_first_at"] = decision_asof.isoformat()

    if new_state["candidate_streak"] >= confirm_count:
        return {
            "confirmed_regime": raw_regime, "confirmed_at": decision_asof.isoformat(),
            "candidate_regime": None, "candidate_streak": 0, "candidate_first_at": None,
        }
    return new_state


def resolve_policy(confirmed_regime: str, high_vol: bool) -> dict:
    """確定地合いとHIGH_VOLフラグから、許可セットアップとリスク倍率を返す。
    HIGH_VOL中は「上表と0.5の小さい方」（C-031-GPT第3節）。"""
    base = REGIME_POLICY.get(confirmed_regime, REGIME_POLICY["UNKNOWN"])
    risk_multiplier = base["risk_multiplier"]
    if high_vol:
        risk_multiplier = min(risk_multiplier, 0.5)
    return {
        "allowed": list(base["allowed"]),
        "watch_only": list(base["watch_only"]),
        "risk_multiplier": risk_multiplier,
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"confirmed_regime": None, "confirmed_at": None,
                "candidate_regime": None, "candidate_streak": 0, "candidate_first_at": None}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"confirmed_regime": None, "confirmed_at": None,
                "candidate_regime": None, "candidate_streak": 0, "candidate_first_at": None}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_topix_intraday():
    """TOPIX代替(1306.T)の当日5分足を取得し、現在値・当日VWAP・直近3本の5分EMA20を返す。
    取得失敗時はNoneを返す（呼び出し側はUNKNOWNとして扱う）。"""
    import yfinance as yf
    try:
        df = yf.download(TOPIX_PROXY_TICKER, period="5d", interval="5m",
                          auto_adjust=False, progress=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = [c[0] for c in df.columns]
        today = df.index[-1].date()
        today_df = df[df.index.date == today]
        if len(today_df) < 3:
            return None
        typical = (today_df["High"] + today_df["Low"] + today_df["Close"]) / 3
        cum_vol = today_df["Volume"].cumsum()
        cum_tpv = (typical * today_df["Volume"]).cumsum()
        vwap_series = cum_tpv / cum_vol.replace(0, float("nan"))
        vwap = float(vwap_series.iloc[-1])
        price = float(today_df["Close"].iloc[-1])
        ema20 = today_df["Close"].ewm(span=20, adjust=False).mean()
        ema20_last3 = [float(v) for v in ema20.tail(3).tolist()]
        return {"price": price, "vwap": vwap, "ema20_last3": ema20_last3,
                "fetched_at": sc.now_jst()}
    except Exception:
        return None


def fetch_breadth_up_ratio():
    """watchlist_100.jsonの銘柄について、yfinance日次終値で前日比上昇比率を計算する。
    正直な制約: 真の日中ブレッドスではなく、直近取得できた日次終値ベースの近似
    （ファイル先頭のdocstring参照）。取得できた銘柄が80%未満ならNoneを返す
    （C-031-GPT第3節のUNKNOWN条件: 母集団の80%以上のデータ不足）。"""
    import yfinance as yf
    if not WATCHLIST_PATH.exists():
        return None
    watch = json.loads(WATCHLIST_PATH.read_text(encoding="utf-8-sig"))
    codes = [v.get("ticker") for v in watch.get("stocks", {}).values() if v.get("ticker")]
    if not codes:
        return None
    up = 0
    counted = 0
    for ticker in codes:
        try:
            df = yf.download(ticker, period="5d", interval="1d", auto_adjust=False, progress=False)
            if df is None or len(df) < 2:
                continue
            closes = df["Close"]
            if hasattr(closes, "squeeze"):
                closes = closes.squeeze()
            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            counted += 1
            if last > prev:
                up += 1
        except Exception:
            continue
    if counted < len(codes) * 0.8:
        return None
    return (up / counted) * 100 if counted else None


def main():
    now = sc.now_jst()
    events = []
    if EVENT_CALENDAR_PATH.exists():
        try:
            events = json.loads(EVENT_CALENDAR_PATH.read_text(encoding="utf-8")).get("events", [])
        except Exception:
            events = []

    topix = fetch_topix_intraday()
    breadth = fetch_breadth_up_ratio()
    data_ok = topix is not None

    base_regime = classify_base_regime(
        price=topix["price"] if topix else None,
        vwap=topix["vwap"] if topix else None,
        ema20_last3=topix["ema20_last3"] if topix else [],
        breadth_up_ratio=breadth,
        data_ok=data_ok,
    )
    locked, lock_event_id = event_lock_active(events, now)
    # HIGH_VOLは60日同時間帯分布の履歴が必要（このv1は履歴未蓄積のため常にFalse。
    # data/regime_5m_history.jsonl等への蓄積は次のステップ）。
    high_vol = False
    raw_regime = resolve_raw_regime(base_regime, locked, high_vol)

    state = load_state()
    new_state = apply_hysteresis(state, raw_regime, now)
    save_state(new_state)

    policy = resolve_policy(new_state["confirmed_regime"], high_vol)

    out = {
        "schema_version": "market-regime-1.0",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
        "topix_proxy_ticker": TOPIX_PROXY_TICKER,
        "data_quality": {
            "topix": "ok" if topix else "missing",
            "breadth": "ok" if breadth is not None else "missing",
        },
        "raw_inputs": {
            "price": topix["price"] if topix else None,
            "vwap": topix["vwap"] if topix else None,
            "ema20_last3": topix["ema20_last3"] if topix else None,
            "breadth_up_ratio_pct": breadth,
        },
        "base_regime": base_regime,
        "flags": {
            "event_lock": locked,
            "event_lock_id": lock_event_id,
            "high_vol": high_vol,
            "rate_shock": rate_shock_active(),
            "policy_event": policy_event_active(),
        },
        "confirmed_regime": new_state["confirmed_regime"],
        "confirmed_at": new_state["confirmed_at"],
        "candidate_regime": new_state["candidate_regime"],
        "candidate_streak": new_state["candidate_streak"],
        "policy": policy,
        "note": ("breadthはyfinance日次終値ベースの近似（真の日中ブレッドスではない）。"
                 "HIGH_VOL/RATE_SHOCK/POLICY_EVENTは一部未実装（ファイル先頭コメント参照）。"
                 "trading_enabledは常にFalse相当（本モジュールは発注判断そのものを出力しない）。"),
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"market_regime.json written: confirmed_regime={new_state['confirmed_regime']}")


if __name__ == "__main__":
    main()
