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
        df = yf.download(ticker, period="3mo", interval="1d", auto_adjust=False,
                         progress=False, threads=False)
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
        score = 2 if chg > 1 else 1 if chg > 0 else -1
        score += 2 if r5 is not None and r5 > 3 else 1 if r5 is not None and r5 > 0 else 0
        score += 2 if r20 is not None and r20 > 8 else 1 if r20 is not None and r20 > 0 else 0
        score += 1 if rvol is not None and rvol > 1.3 else 0
        return {"ok": True, "price": round(close, 2), "change_pct": round(chg, 2),
                "ret5": None if r5 is None else round(r5, 2),
                "ret20": None if r20 is None else round(r20, 2),
                "rvol": None if rvol is None else round(rvol, 2), "score": score}
    except Exception:
        return {"ok": False}


def n(v, suffix=""):
    return "取得不能" if v is None else f"{v:,}{suffix}"


def color(v):
    return "up" if isinstance(v, (int, float)) and v > 0 else "down" if isinstance(v, (int, float)) and v < 0 else ""


def main():
    now = datetime.now(JST)
    afternoon = now.hour >= 12
    phase = "大引け前15:00版" if afternoon else "寄り付き前8:30版"
    wl = json.loads((ROOT / "watchlist.json").read_text(encoding="utf-8"))
    indices = {k: fetch(v) for k, v in wl["indices"].items()}
    stocks = {k: fetch(v) for k, v in wl["stocks"].items()}
    ranked = sorted(stocks.items(), key=lambda x: x[1].get("score", -999), reverse=True)
    data = {"updated_at": now.strftime("%Y-%m-%d %H:%M:%S JST"), "phase": phase,
            "indices": indices, "stocks": stocks}
    (ROOT / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    idx_rows = ""
    for name, r in indices.items():
        chg = r.get("change_pct")
        trend = "上向き" if isinstance(chg, (int, float)) and chg > .3 else "下向き" if isinstance(chg, (int, float)) and chg < -.3 else "横ばい"
        idx_rows += f'<tr><td>{name}</td><td>{n(r.get("price"))}</td><td class="{color(chg)}">{n(chg, "%")}</td><td>{trend}</td></tr>'

    day_rows = ""
    for name, r in ranked[:5]:
        p = r.get("price")
        if not r.get("ok") or not p:
            day_rows += f"<tr><td>{name}</td><td colspan='6'>取得不能・見送り</td></tr>"
            continue
        entry = round(p * .997, 0)
        stop = round(p * .985, 0)
        target = round(p * 1.02, 0)
        shares = 100 if p < 10000 else 10
        loss = int((entry - stop) * shares)
        decision = "押し目監視" if r["score"] >= 5 else "VWAP確認" if r["score"] >= 2 else "見送り優先"
        day_rows += f"<tr><td>{name}</td><td>{n(p)}</td><td>{n(entry)}</td><td>{n(stop)}</td><td>{n(target)}</td><td>{shares}</td><td>{decision}<br><small>最大損失目安 {loss:,}円</small></td></tr>"

    swing = [(k, v) for k, v in ranked if v.get("ok") and 1800 <= v.get("price", 0) <= 12000][:5]
    swing_rows = "".join(
        f'<tr><td>{k}</td><td>{n(v.get("price"))}</td><td class="{color(v.get("change_pct"))}">{n(v.get("change_pct"), "%")}</td><td>{n(v.get("ret20"), "%")}</td><td>{"押し目候補" if v.get("score",0)>=3 else "形を確認"}</td></tr>'
        for k, v in swing) or "<tr><td colspan='5'>条件に合う銘柄なし</td></tr>"

    themes = [
        ("半導体・AI", "SOXと東京エレク・アドバンテストを確認"),
        ("防衛・重工", "三菱重工業・IHIの出来高を確認"),
        ("電線・データセンター", "フジクラ・古河電工の押し目を確認"),
        ("円安関連", "ドル円と輸出株の連動を確認"),
        ("内需・サービス", "ラウンドワンの需給と反発を確認"),
    ]
    theme_rows = "".join(f"<tr><td>{i}</td><td>{a}</td><td>{b}</td></tr>" for i, (a, b) in enumerate(themes, 1))
    vix = indices.get("VIX", {}).get("price")
    usd = indices.get("ドル円", {}).get("price")
    nikkei = indices.get("日経平均", {}).get("price")
    range_text = "取得不能"
    if isinstance(nikkei, (int, float)):
        range_text = f"{round(nikkei * .985):,.0f}円 ～ {round(nikkei * 1.015):,.0f}円"
    risk = "警戒" if isinstance(vix, (int, float)) and vix >= 20 else "通常警戒"
    timing_title = "引け前チェック" if afternoon else "寄り付き前チェック"
    timing_items = ["VWAP位置と大引けの気配", "上ヒゲ・出来高・決算予定", "持ち越しは逆指値を先に決める", "PTSと翌営業日の材料確認"] if afternoon else ["先物・米指数・SOXを確認", "為替・金利・VIXを確認", "GU/GD幅と板・歩み値を確認", "寄り後5分は出来高を観察", "IFO注文を準備してから入る"]
    timing_li = "".join(f"<li>✅ {x}</li>" for x in timing_items)
    strategy = "強い銘柄の押し目を優先。VWAPを割ったら撤退。" if not afternoon else "大引けの需給を確認。持ち越しは少数に絞る。"

    html = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="900"><title>AIトレードコクピット</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#05070a;color:#f4f7fa;font-family:"Segoe UI","Yu Gothic",sans-serif;font-size:13px}}header{{padding:10px 12px;border-bottom:2px solid #526274;background:#030405;display:flex;justify-content:space-between;align-items:center;gap:12px}}h1{{margin:0;font-size:25px;letter-spacing:.03em}}h2{{font-size:17px;margin:0 0 7px;color:#d9e8ff;border-bottom:1px solid #405064;padding-bottom:5px}}.sub{{color:#aebdcb;margin-top:4px}}.headright{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:flex-end}}.tag{{background:#ffe86b;color:#111;padding:7px 11px;border-radius:6px;font-weight:900}}.range{{border:1px solid #ddca41;border-radius:6px;overflow:hidden;display:flex;font-weight:800}}.range b{{background:#fff3a2;color:#161616;padding:7px 10px}}.range span{{background:#18180c;color:#ffe86b;padding:7px 10px}}main{{padding:6px;display:grid;grid-template-columns:1.16fr .95fr 1.08fr;gap:6px}}.card{{background:linear-gradient(180deg,#151d27,#0e141c);border:1px solid #73808c;border-radius:6px;padding:7px;overflow:auto;box-shadow:0 2px 7px #0008}}.wide{{grid-column:span 2}}table{{width:100%;border-collapse:collapse;white-space:normal}}th{{background:#1b2a39;color:#f3f7fb}}th,td{{border:1px solid #485664;padding:6px 5px;text-align:right;vertical-align:middle}}th:first-child,td:first-child{{text-align:left}}tr:nth-child(even) td{{background:#111923}}.up{{color:#52e46f;font-weight:900}}.down{{color:#ff6262;font-weight:900}}small{{color:#bac6d2}}ul{{padding-left:17px;line-height:1.65;margin:3px 0}}.warning{{color:#ffe66d}}.quote{{font-size:17px;font-weight:900;line-height:1.55}}footer{{padding:8px 12px;color:#aeb8c2;border-top:1px solid #33404b;display:flex;justify-content:space-between}}@media(max-width:1150px){{main{{grid-template-columns:1fr 1fr}}}}@media(max-width:720px){{header{{align-items:flex-start;flex-direction:column}}main{{grid-template-columns:1fr}}.wide{{grid-column:span 1}}table{{min-width:520px}}}}
</style></head><body>
<header><div><h1>AIトレードコクピット</h1><div class="sub">毎日8:30・15:00自動更新／15分ごとに画面再読み込み</div></div><div class="headright"><div class="range"><b>本日の想定レンジ（日経平均）</b><span>{range_text}</span></div><div><span class="tag">{phase}</span><div class="sub">{data["updated_at"]}</div></div></div></header>
<main>
<section class="card"><h2>① 地合いサマリー</h2><table><tr><th>指標</th><th>現在値</th><th>前日比</th><th>方向</th></tr>{idx_rows}</table></section>
<section class="card"><h2>② 当日の狙い目業種 TOP5</h2><table><tr><th>順位</th><th>業種</th><th>注目ポイント</th></tr>{theme_rows}</table></section>
<section class="card"><h2>③ デイトレ候補 TOP5</h2><table><tr><th>会社名＋コード</th><th>価格</th><th>入口目安</th><th>IFO損切り</th><th>利確目安</th><th>株数</th><th>判定</th></tr>{day_rows}</table><p class="warning">※価格は日足からの機械的目安。板・歩み値・VWAP確認後に判断。</p></section>
<section class="card"><h2>④ 決算持ち越し確認</h2><table><tr><th>確認項目</th><th>判断</th></tr><tr><td>当日・翌営業日の決算</td><td>証券会社・適時開示で要確認</td></tr><tr><td>PTS初動</td><td>大引け後に要確認</td></tr><tr><td>最大投資額</td><td>1銘柄に集中しない</td></tr><tr><td>持ち越し条件</td><td>決算日・逆指値・最大損失を確認</td></tr></table><p class="warning">架空の決算日や予測値は表示しません。</p></section>
<section class="card"><h2>⑤ スイング候補 TOP5</h2><table><tr><th>会社名＋コード</th><th>価格</th><th>前日比</th><th>20日</th><th>判断</th></tr>{swing_rows}</table></section>
<section class="card"><h2>⑥ リスク・イベント・需給</h2><table><tr><th>項目</th><th>状態</th></tr><tr><td>VIX</td><td>{n(vix)}／{risk}</td></tr><tr><td>ドル円</td><td>{n(usd)}</td></tr><tr><td>信用・空売り</td><td>証券会社画面で最終確認</td></tr><tr><td>決算・経済イベント</td><td>当日カレンダーを確認</td></tr><tr><td>SNS・ニュース</td><td>初動と事実確認を優先</td></tr></table></section>
<section class="card wide"><h2>⑦ 本日のトレード戦略まとめ</h2><ul><li>✅ {strategy}</li><li>✅ 値がさ株は株数を抑え、最大損失を先に固定</li><li>✅ 材料・ニュース・信用需給は発注前に最終確認</li><li>✅ 深追いせず、見送ることも正しい判断</li></ul><h2>本日のキーワード</h2><p class="warning">半導体・AI／防衛・重工／電線・データセンター／ドル円／VIX</p></section>
<section class="card"><h2>⑧ メンタルチェック</h2><ul><li>□ エントリー条件を守る</li><li>□ 損切りを先延ばしにしない</li><li>□ 利益目標を決めて欲張らない</li><li>□ 負けを取り戻す取引をしない</li></ul></section>
<section class="card"><h2>{timing_title}</h2><ul>{timing_li}</ul></section>
<section class="card"><h2>AI 今日のひとこと</h2><p class="quote">「相場は毎日違う。だからこそ、ルールと準備があなたを守る。」</p></section>
</main><footer><span>本レポートは情報提供目的であり、投資助言ではありません。</span><span>更新日時：{data["updated_at"]}</span></footer></body></html>'''
    (ROOT / "index.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
