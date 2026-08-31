"""Create the Saturday review and add tab navigation to the generated cockpit."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "index.html"
DATA = ROOT / "data.json"
HISTORY = ROOT / "paper_trade_history.json"
WEEKLY = ROOT / "weekly_review.json"
JST = ZoneInfo("Asia/Tokyo")
START = "<!-- COCKPIT_TABS_START -->"
END = "<!-- COCKPIT_TABS_END -->"
WSTART = "<!-- WEEKLY_REVIEW_START -->"
WEND = "<!-- WEEKLY_REVIEW_END -->"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_weekly(now: datetime) -> dict:
    monday = (now.date() - timedelta(days=now.weekday())).isoformat()
    sunday = (now.date() + timedelta(days=6 - now.weekday())).isoformat()
    records = [
        x for x in load(HISTORY, [])
        if monday <= x.get("date", "") <= sunday and x.get("pnl_yen") is not None
    ]
    gains = sum(max(0, x["pnl_yen"]) for x in records)
    losses = abs(sum(min(0, x["pnl_yen"]) for x in records))
    pf = round(gains / losses, 2) if losses else (99.0 if gains else 0.0)
    wins = sum(x["pnl_yen"] > 0 for x in records)
    avg_r = round(sum(x.get("r", 0) for x in records) / len(records), 2) if records else 0
    data = load(DATA, {})
    indices = data.get("indices", {})
    nikkei = indices.get("日経平均", {})
    nasdaq = indices.get("NASDAQ", {})
    themes = data.get("themes", [])[:3]
    theme_names = [
        str(x.get("theme") or x.get("name") or x) if isinstance(x, dict) else str(x)
        for x in themes
    ]
    next_rules = [
        "8:00版の発動価格を抜くまで注文しない",
        "前場はVWAPとOR15が同方向の銘柄だけ",
        "1銘柄の最大損失を資金の0.5%以内に固定",
    ]
    if float(nikkei.get("from_ma20", 0)) < 0:
        next_rules.insert(0, "日経平均が20日線下ではロング数量を半分")
    if float(nasdaq.get("change_pct", 0)) < -1:
        next_rules.insert(0, "NASDAQ急落後は半導体の寄り付き飛び乗り禁止")
    return {
        "week": f"{monday}～{sunday}",
        "created_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "count": len(records),
        "wins": wins,
        "win_rate": round(wins / len(records) * 100, 1) if records else 0,
        "pf": pf,
        "avg_r": avg_r,
        "pnl": sum(x["pnl_yen"] for x in records),
        "best": sorted(records, key=lambda x: x["pnl_yen"], reverse=True)[:3],
        "worst": sorted(records, key=lambda x: x["pnl_yen"])[:3],
        "themes": theme_names,
        "next_rules": next_rules,
        "decision": "少額実戦候補" if len(records) >= 20 and pf >= 1.2 and avg_r > 0 else "仮想検証を継続",
    }


def weekly_html(w: dict) -> str:
    if not w:
        return f"{WSTART}<section id=\"weekly-review\"><h2>週間振り返り・来週戦略</h2><p>土曜日の集計後に表示します。</p></section>{WEND}"
    best = "".join(
        f"<li>{html.escape(x.get('name',''))}：{x.get('pnl_yen',0):+,}円（{x.get('r',0):+.2f}R）</li>"
        for x in w.get("best", [])
    ) or "<li>確定取引なし</li>"
    worst = "".join(
        f"<li>{html.escape(x.get('name',''))}：{x.get('pnl_yen',0):+,}円（{x.get('r',0):+.2f}R）</li>"
        for x in w.get("worst", [])
    ) or "<li>確定取引なし</li>"
    rules = "".join(f"<li>{html.escape(x)}</li>" for x in w.get("next_rules", []))
    themes = "・".join(html.escape(x) for x in w.get("themes", [])) or "更新待ち"
    return f"""{WSTART}
<section id="weekly-review" class="panel">
  <h2>週間振り返り・来週戦略</h2>
  <p>{html.escape(w['week'])}｜作成 {html.escape(w['created_at'])}</p>
  <div class="cards">
    <div class="card"><b>仮想取引</b><span>{w['count']}件</span></div>
    <div class="card"><b>勝率</b><span>{w['win_rate']:.1f}%</span></div>
    <div class="card"><b>PF</b><span>{w['pf']:.2f}</span></div>
    <div class="card"><b>平均R</b><span>{w['avg_r']:+.2f}R</span></div>
    <div class="card"><b>週間損益</b><span>{w['pnl']:+,}円</span></div>
    <div class="card"><b>実戦判定</b><span>{html.escape(w['decision'])}</span></div>
  </div>
  <div class="weekly-grid">
    <div><h3>良かった取引</h3><ul>{best}</ul></div>
    <div><h3>改善する取引</h3><ul>{worst}</ul></div>
    <div><h3>来週の注目テーマ</h3><p>{themes}</p></div>
    <div><h3>来週のルール</h3><ol>{rules}</ol></div>
  </div>
</section>
{WEND}"""


def tabs_block() -> str:
    return f"""{START}
<style>
.cockpit-tabs{{position:sticky;top:0;z-index:30;display:flex;gap:8px;padding:10px;background:#07111fdd;backdrop-filter:blur(10px);overflow-x:auto}}
.cockpit-tab{{border:1px solid #35506d;background:#102238;color:#b9cbe0;border-radius:10px;padding:10px 16px;font-weight:700;white-space:nowrap;cursor:pointer}}
.cockpit-tab.active{{color:#07111f;background:#52e0c4;border-color:#52e0c4}}
.tab-pane{{display:none}}.tab-pane.active{{display:block}}
.weekly-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.weekly-grid>div{{background:#0c1b2d;border:1px solid #243b55;border-radius:12px;padding:14px}}
</style>
<nav class="cockpit-tabs" aria-label="コクピット表示切替">
 <button class="cockpit-tab active" data-tab="daytrade">当日デイトレ</button>
 <button class="cockpit-tab" data-tab="wick">下ヒゲ反転</button>
 <button class="cockpit-tab" data-tab="expansion">エクスパンション</button>
 <button class="cockpit-tab" data-tab="swing">短期スイング</button>
 <button class="cockpit-tab" data-tab="accumulation">大口仕込み</button>
 <button class="cockpit-tab" data-tab="longterm">長期反転</button>
 <button class="cockpit-tab" data-tab="dividend">配当権利前</button>
 <button class="cockpit-tab" data-tab="buyback">自社株買い</button>
 <button class="cockpit-tab" data-tab="policy">国策テーマ</button>
 <button class="cockpit-tab" data-tab="market">市場・検証</button>
 <button class="cockpit-tab" data-tab="weekly">週間レビュー</button>
</nav>
<script>
document.addEventListener("DOMContentLoaded",()=>{{
 const main=document.querySelector("main"); if(!main)return;
 const panes={{}}; ["daytrade","wick","expansion","swing","accumulation","longterm","dividend","buyback","policy","market","weekly"].forEach(k=>{{const d=document.createElement("div");d.className="tab-pane"+(k==="daytrade"?" active":"");d.dataset.pane=k;main.appendChild(d);panes[k]=d;}});
 [...main.querySelectorAll(":scope > section")].forEach(s=>{{
   const t=(s.querySelector("h2")?.textContent||"").trim();
   let k="market";
   if(s.id==="action-dashboard"||s.id==="day-ifo-orders"||t.startsWith("③ ")||t.includes("IN点灯")||t.includes("準備点灯"))k="daytrade";
   else if(s.id==="lower-wick-reversal"||t.includes("下ヒゲ吸収反転"))k="wick";
   else if(t.includes("BB上方エクスパンション")||t.includes("短期急騰期待")||t.includes("テーマ仕手化兆候"))k="expansion";
   else if(s.id==="weekly-review"||t.includes("週間振り返り"))k="weekly";
   else if(s.id==="large-lot-accumulation"||t.includes("大口買い集め"))k="accumulation";
   else if(s.id==="dividend-rights-watch")k="dividend";
   else if(s.id==="buyback-watch")k="buyback";
   else if(t.includes("月足・週足反転")||t.includes("50週線")||t.includes("200日線"))k="longterm";
   else if(t.includes("秋田AI")||t.includes("群馬・茂倉沢")||t.includes("シリコンフォトニクス")||t.includes("当日資金流入テーマ")||s.id==="sector-rotation")k="policy";
   else if(t.includes("安定上昇")||t.includes("52週新高値")||t.includes("過熱監視")||t.includes("持ち越し")||t.includes("AIスイング"))k="swing";
   panes[k].appendChild(s);
 }});
 const intros={{daytrade:["当日デイトレ","需給改善済みの最大5銘柄。実戦対象は上位1～3銘柄。"],wick:["最優先・下ヒゲ吸収反転","売り吸収→終値回復→次足上抜けの順で発動。"],expansion:["当日エクスパンション","BB収縮から出来高を伴う拡大が期待できる銘柄。"],swing:["短期スイング","信用需給を主軸に、押し目・新高値・持ち越しを選別。"],accumulation:["大口仕込み","出来高・OBV・安値切上げから吸収と蓄積を監視。"],longterm:["長期右肩上がり・反転","50週線・200日線・月週足反転と需給改善が重なる銘柄。"],dividend:["配当権利前・上下期待","権利前上昇と権利落ち下落を需給付きで監視。"],buyback:["自社株買い監視","実施期間・残り余力・出来高影響と需給改善を確認。"],policy:["国策監視テーマ","防衛・宇宙・原子力・GX・AI半導体・先端素材を需給付きで監視。"],market:["市場・検証","地合い、警報、答え合わせ、決算リスクを確認。"],weekly:["週間レビュー","週末検証と翌週の改善ルール。"]}};
 Object.entries(intros).forEach(([k,v])=>{{const h=document.createElement("div");h.className="pane-intro";h.innerHTML=`<span>SUPPLY IMPROVEMENT REQUIRED</span><h2>${{v[0]}}</h2><p>${{v[1]}}</p>`;panes[k].prepend(h);}});
 document.querySelectorAll(".cockpit-tab").forEach(b=>b.onclick=()=>{{
   document.querySelectorAll(".cockpit-tab").forEach(x=>x.classList.toggle("active",x===b));
   document.querySelectorAll(".tab-pane").forEach(x=>x.classList.toggle("active",x.dataset.pane===b.dataset.tab));
   localStorage.setItem("cockpitTabV5",b.dataset.tab);
 }});
 const saved=localStorage.getItem("cockpitTabV5"); if(saved)document.querySelector(`.cockpit-tab[data-tab="${{saved}}"]`)?.click();
}});
</script>
{END}"""


def main() -> None:
    now = datetime.now(JST)
    weekly = load(WEEKLY, {})
    if now.weekday() == 5:
        weekly = build_weekly(now)
        save(WEEKLY, weekly)
    page = PAGE.read_text(encoding="utf-8")
    page = re.sub(re.escape(START) + r".*?" + re.escape(END), "", page, flags=re.S)
    page = re.sub(re.escape(WSTART) + r".*?" + re.escape(WEND), "", page, flags=re.S)
    page = page.replace("</head>", tabs_block() + "\n</head>", 1)
    page = page.replace("</main>", weekly_html(weekly) + "\n</main>", 1)
    PAGE.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
