"""
multi_ticker_5m_calendar.py
Stage②の比較を「キオクシアだけ」から広げるための、複数銘柄向け5分足カレンダー収集。

対象銘柄: watch_top5.json の直近スナップショットに載っている銘柄 ＋ キオクシア(285A)。
（監視TOP5は日々入れ替わるため、この銘柄リストも実行の度に変わりうる。
 過去に集めた銘柄のデータは data/5m_calendars/<code>.json に残り続け、
 今日的に監視対象でなくなった銘柄の履歴も消さずに蓄積する設計。）

kioxia_calendar.py と異なり、5分足の高値・安値（ヒゲ）を保持したまま保存する。
stage2_backtest.py が使っていた「終値だけの近似」による構造的バイアスを、
今後この銘柄については解消できる（Kioxia自身の過去データはpathのみで別途保持）。

取得元: yfinance の interval="5m"（Yahoo Financeの制約で直近60日分のみ取得可能）。

出力: data/5m_calendars/<code>.json
  {
    "code": "285A", "ticker": "285A.T", "updated_at": "...",
    "days": [
      {"date": "2026-08-07", "type": "上昇トレンド",
       "bars": [{"t": "09:00", "o": 0.0, "h": 0.12, "l": -0.05, "c": 0.08, "v": 12345}, ...]}
      , ...
    ]
  }
  値は始値比リターン(%)。

制約（正直な申告）:
  - 開発環境にはyfinanceがインストールされておらず、ネットワーク的にもYahoo Financeへ
    到達できないため、このスクリプトは実地テストできていない。既存のkioxia_calendar.py
    （同じyf.download呼び出しパターンで実際に動いている）を参考に書いているが、
    導入後は必ずGitHub Actionsの実行ログとdata/5m_calendars/以下の中身を確認すること。
  - yfinanceの5分足は60日制限のため、監視対象が変わるたびに過去分を遡って取得することは
    できない。「今日から先」のデータを溜めていく前提。
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

JST = ZoneInfo("Asia/Tokyo")
OUT_DIR = Path("data/5m_calendars")
KIOXIA_CODE = "285A"


def load_watch_top5_codes() -> list[str]:
    codes = [KIOXIA_CODE]
    p = Path("watch_top5.json")
    if not p.exists():
        return codes
    data = json.loads(p.read_text(encoding="utf-8"))
    for item in data.get("top5", []):
        code = item.get("code")
        if code and code not in codes:
            codes.append(code)
    return codes


def to_ticker(code: str) -> str:
    return f"{code}.T"


def finite(v):
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def classify(day: pd.DataFrame) -> str:
    close = day["Close"].astype(float)
    open_ = float(day["Open"].iloc[0])
    last = float(close.iloc[-1])
    high_at = int(np.argmax(day["High"].astype(float).values))
    low_at = int(np.argmin(day["Low"].astype(float).values))
    ret = (last / open_ - 1) * 100
    vwap = ((day["High"] + day["Low"] + day["Close"]) / 3 * day["Volume"].fillna(0)).cumsum()
    vol = day["Volume"].fillna(0).cumsum().replace(0, np.nan)
    vwap_last = finite((vwap / vol).iloc[-1])
    if ret >= 1 and last > (vwap_last or last):
        return "上昇トレンド"
    if high_at <= 3 and ret <= -.5:
        return "寄り天"
    if low_at <= 3 and ret >= .5:
        return "寄り底"
    if ret <= -1 and last < (vwap_last or last):
        return "下落継続"
    return "レンジ"


def session_days(frame: pd.DataFrame):
    if frame.empty:
        return []
    idx = pd.to_datetime(frame.index)
    idx = idx.tz_localize("UTC").tz_convert(JST) if idx.tz is None else idx.tz_convert(JST)
    frame = frame.copy()
    frame.index = idx
    frame = frame.between_time("09:00", "15:30")
    return [(str(day), part.copy()) for day, part in frame.groupby(frame.index.date) if len(part) >= 3]


def day_bars(day: pd.DataFrame) -> list[dict]:
    """終値だけでなく高値・安値・出来高も保持した5分足バー列を返す（始値比%）。"""
    open_ = float(day["Open"].iloc[0])
    bars = []
    for ts, row in day.iterrows():
        o, h, l, c = (finite(row[k]) for k in ("Open", "High", "Low", "Close"))
        if None in (o, h, l, c) or open_ == 0:
            continue
        bars.append({
            "t": ts.strftime("%H:%M"),
            "o": round((o / open_ - 1) * 100, 3),
            "h": round((h / open_ - 1) * 100, 3),
            "l": round((l / open_ - 1) * 100, 3),
            "c": round((c / open_ - 1) * 100, 3),
            "v": int(finite(row.get("Volume")) or 0),
        })
    return bars


def collect_one(code: str):
    ticker = to_ticker(code)
    try:
        raw = yf.download(ticker, period="60d", interval="5m", auto_adjust=False, progress=False)
    except Exception as e:  # noqa: BLE001
        print(f"[{code}] 取得失敗: {e}")
        return None
    if raw is None or raw.empty:
        print(f"[{code}] データなし")
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    days = []
    for date, day in session_days(raw):
        days.append({
            "date": date,
            "type": classify(day),
            "bars": day_bars(day),
        })
    return {
        "code": code,
        "ticker": ticker,
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "days": days,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    codes = load_watch_top5_codes()
    for code in codes:
        result = collect_one(code)
        if result is None:
            continue
        out_path = OUT_DIR / f"{code}.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{code}] {len(result['days'])}日分を保存")


if __name__ == "__main__":
    main()
