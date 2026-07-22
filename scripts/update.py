
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo("Asia/Tokyo")

def fetch(ticker):
    try:
        df = yf.download(ticker, period="3mo", interval="1d", auto_adjust=False, progress=False, threads=False)
        if df.empty:
            return {"ok": False}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        close = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) > 1 else close
        chg = (close / prev - 1) * 100 if prev else 0
        r5 = (close / float(df["Close"].iloc[-6]) - 1) * 100 if len(df) >= 6 else None
        r20 = (close / float(df["Close"].iloc[-21]) - 1) * 100 if len(df) >= 21 else None
        vol = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0
        avg = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns else 0
        rvol = vol / avg if avg else None
        score = (2 if chg > 1 else 1 if chg > 0 else -1)
        score += 2 if r5 is not None and r5 > 3 else 1 if r5 is not None and r5 > 0 else 0
        score += 2 if r20 is not None and r20 > 8 else 1 if r20 is not None and r20 > 0 else 0
        score += 1 if rvol is not None and rvol > 1.3 else 0
        return {"ok": True, "price": round(close,2), "change_pct": round(chg,2),
                "ret5": None if r5 is None else round(r5,2),
                "ret20": None if r20 is None else round(r20,2),
                "rvol": None if rvol is None else round(rvol,2),
                "score": score}
    except Exception:
        return {"ok": False}

def verdict(r, afternoon):
    if not r.get("ok"): return "取得不能"
    if afternoon:
        if r["score"] >= 5 and r["change_pct"] > 0: return "持ち越し候補"
        if r["score"] <= 0 or r["change_pct"] < -2: return "持ち越し回避"
        return "監視継続"
    if r["score"] >= 5: return "寄り後の押し目監視"
    if r["score"] >= 2: return "VWAP確認後に監視"
    return "見送り優先"

def main():
    now = datetime.now(JST)
    afternoon = now.hour >= 12
    phase = "引け前15:00版" if afternoon else "朝8:30版"
    wl = json.loads((ROOT/"watchlist.json").read_text(encoding="utf-8"))
    indices = {k: fetch(v) for k,v in wl["indices"].items()}
    stocks = {k: fetch(v) for k,v in wl["stocks"].items()}
    data = {"updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"), "phase": phase,
            "indices": indices, "stocks": stocks}
    (ROOT/"data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    idx_rows = "".join(f"<tr><td>{k}</td><td>{v.get('price','—')}</td><td>{v.get('change_pct','—')}%</td><td>{v.get('ret5','—')}%</td></tr>" for k,v in indices.items())
    ranked = sorted(stocks.items(), key=lambda x: x[1].get("score",-999), reverse=True)
    stk_rows = "".join(f"<tr><td>{k}</td><td>{v.get('price','—')}</td><td>{v.get('change_pct','—')}%</td><td>{v.get('ret5','—')}%</td><td>{v.get('ret20','—')}%</td><td>{v.get('rvol','—')}</td><td>{verdict(v,afternoon)}</td></tr>" for k,v in ranked)
    checks = ["大引け前のVWAP位置","日足の上ヒゲ・出来高","翌営業日の決算・材料","持ち越し時の逆指値候補","PTSで初動確認"] if afternoon else ["先物とドル円の方向","GU/GD幅","寄り後5分の出来高","VWAPの上下","IFO注文の準備"]
    li = "".join(f"<li>{x}</li>" for x in checks)

    html = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="900"><title>AIトレードコクピット</title><style>
body{{margin:0;background:#0b0f14;color:#edf2f7;font-family:Segoe UI,Yu Gothic,sans-serif}}header{{padding:16px 20px;background:#080b10;border-bottom:1px solid #2b3542;display:flex;justify-content:space-between}}main{{padding:16px;display:grid;grid-template-columns:1fr 1.6fr;gap:16px}}.card{{background:#121923;border:1px solid #2b3542;border-radius:12px;padding:14px;overflow:auto}}table{{width:100%;border-collapse:collapse;min-width:620px}}th,td{{padding:10px;border-bottom:1px solid #2b3542;text-align:right}}th:first-child,td:first-child{{text-align:left}}.tag{{background:#f5c842;color:#111;padding:7px 11px;border-radius:999px;font-weight:800}}@media(max-width:900px){{main{{grid-template-columns:1fr}}}}</style></head><body>
<header><div><h1>AIトレードコクピット</h1><div>毎日8:30・15:00 自動更新</div></div><div><span class="tag">{phase}</span><div>{data['updated_at']}</div></div></header>
<main><section class="card"><h2>地合いサマリー</h2><table><tr><th>指標</th><th>現在値</th><th>前日比</th><th>5日</th></tr>{idx_rows}</table></section>
<section class="card"><h2>監視銘柄ランキング</h2><table><tr><th>会社名＋コード</th><th>価格</th><th>前日比</th><th>5日</th><th>20日</th><th>RVOL</th><th>判定</th></tr>{stk_rows}</table></section>
<section class="card"><h2>確認ポイント</h2><ul>{li}</ul></section>
<section class="card"><h2>注意</h2><p>価格・出来高・モメンタムによる一次判定です。板、歩み値、VWAP、ニュース、決算、信用需給を確認して最終判断してください。</p></section></main></body></html>"""
    (ROOT/"index.html").write_text(html, encoding="utf-8")

if __name__ == "__main__":
    main()
