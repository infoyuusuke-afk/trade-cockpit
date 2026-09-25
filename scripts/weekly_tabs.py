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
    return START + """
<style>
.cockpit-tabs{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:2px;padding:5px 7px;background:#131722f2;border-bottom:1px solid #2a2e39;backdrop-filter:blur(10px);overflow-x:auto}
.cockpit-brand{display:flex;align-items:baseline;gap:7px;padding:0 10px 0 4px;margin-right:4px;border-right:1px solid #2a2e39;font-weight:700;font-size:14px;letter-spacing:-.01em;color:#d1d4dc;white-space:nowrap}
.cockpit-brand small{font-size:10px;font-weight:700;color:#089981;background:#131722;border:1px solid #2a2e39;padding:2px 6px;border-radius:4px;letter-spacing:0}
.cockpit-brand small.status-warn{color:#f7a600;background:#2a2315;border-color:#6b5426}
.cockpit-brand small.status-error{color:#f23645;background:#32191d;border-color:#6f2730}
.cockpit-tab{border:0;border-radius:4px;background:transparent;color:#9ba3af;padding:9px 12px;font-weight:700;white-space:nowrap;cursor:pointer}
.cockpit-tab:hover{background:#1e222d;color:#d1d4dc}.cockpit-tab.active{color:#fff;background:#2962ff}
.cockpit-tab.event-alert{color:#fff;background:#f23645;box-shadow:none}
.secondary-tabs{margin-left:auto;white-space:nowrap}.secondary-tabs summary{cursor:pointer;color:#9ba3af;padding:9px 10px;border-radius:4px}.secondary-tabs summary:hover{background:#1e222d;color:#d1d4dc}.secondary-tabs[open]{display:flex;gap:2px}
.tab-pane{display:none}.tab-pane.active{display:block}
/* Card-first contract: every pane except KIOXIA is a card surface. */
.tab-pane:not([data-pane="kioxia-calendar"]){display:none;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;align-items:start}
.tab-pane:not([data-pane="kioxia-calendar"]).active{display:grid}
.tab-pane:not([data-pane="kioxia-calendar"])>.pane-intro{grid-column:1/-1}
.tab-pane:not([data-pane="kioxia-calendar"])>section{margin:0!important;min-width:0;border-radius:8px!important;overflow:hidden}
.tab-pane:not([data-pane="kioxia-calendar"])>section.wide{grid-column:auto!important;width:auto!important}
.tab-pane:not([data-pane="kioxia-calendar"]) iframe,
.tab-pane:not([data-pane="kioxia-calendar"]) canvas,
.tab-pane:not([data-pane="kioxia-calendar"]) .tv-lightweight-charts{display:none!important}
.tab-pane:not([data-pane="kioxia-calendar"]) table{width:100%;font-size:11px}
.tab-pane:not([data-pane="kioxia-calendar"]) section>table,
.tab-pane:not([data-pane="kioxia-calendar"]) section>h3+table{display:none!important}
.tab-pane:not([data-pane="kioxia-calendar"]) section:has(>table):not(:has(.scalp-strip)):not(:has(.ms2-live-grid))::after{content:"詳細データはカード化移行中";display:block;padding:12px;color:#9AA0AA;font-size:11px;border-top:1px solid #22252A}
.tab-pane:not([data-pane="kioxia-calendar"]) details table{display:table!important}
.tab-pane:not([data-pane="kioxia-calendar"]) .weekly-grid{grid-template-columns:1fr}
@media(max-width:720px){.tab-pane:not([data-pane="kioxia-calendar"]){grid-template-columns:1fr}}
.weekly-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.weekly-grid>div{background:#131722;border:1px solid #2a2e39;border-radius:6px;padding:14px}
.scalp-tv{background:#050506!important;border:1px solid #22252A!important;border-radius:8px!important;padding:0!important;overflow:hidden!important;color:#E8EAED}
.scalp-tv-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 14px;border-bottom:1px solid #22252A;background:#090A0C}
.scalp-tv-title{display:flex;align-items:center;gap:10px}.scalp-tv-title h2{margin:0!important;padding:0!important;border:0!important;color:#E8EAED!important;font-size:15px!important}.scalp-tv-title span{font-size:11px;color:#9AA0AA}
.scalp-tv-legend{display:flex;gap:12px;font-size:11px;color:#9AA0AA}.scalp-tv-legend b{color:#E8EAED}
.scalp-strip{display:grid;grid-template-columns:repeat(5,minmax(205px,1fr));gap:10px;background:#050506;padding:10px}
.scalp-card{position:relative;background:#090A0C;border:1px solid #22252A;border-radius:8px;min-height:280px;padding:14px;overflow:hidden}
.scalp-card.long{box-shadow:inset 0 2px 0 #089981}.scalp-card.short{box-shadow:inset 0 2px 0 #f23645}.scalp-card.wait{box-shadow:inset 0 2px 0 #33363c}.scalp-card.block{box-shadow:inset 0 2px 0 #c98a1f}
.scalp-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.scalp-symbol{min-width:0}.scalp-symbol strong{display:block;color:#E8EAED;font-size:13px;font-weight:600;line-height:1.25;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.scalp-symbol small{display:block;color:#9AA0AA;font-size:10.5px;margin-top:3px}
.scalp-signal{font-size:10.5px;font-weight:800;padding:4px 8px;border-radius:999px;background:#0E1013;color:#9AA0AA;border:1px solid #22252A}.long .scalp-signal{background:#0d2b23;color:#1fc79a;border-color:#164536}.short .scalp-signal{background:#341418;color:#f0616c;border-color:#4a1f24}.block .scalp-signal{background:#2c2110;color:#d9a13f;border-color:#4a3a1c}.wait .scalp-signal{background:#0E1013;color:#9AA0AA}
.scalp-price-row{display:flex;align-items:flex-end;justify-content:space-between;gap:8px;margin-top:14px}.scalp-price{font-size:26px;font-weight:700;letter-spacing:-.02em;color:#E8EAED}.scalp-change{font-size:12px;font-weight:700}.scalp-change.up{color:#1fc79a}.scalp-change.down{color:#f0616c}.scalp-change.flat{color:#9AA0AA}
.scalp-spark{height:54px;margin:8px -2px 6px}.scalp-spark svg{width:100%;height:54px;display:block}.scalp-spark .grid{stroke:#22252A;stroke-width:1}.scalp-spark .line{fill:none;stroke:#4d5b68;stroke-width:2;vector-effect:non-scaling-stroke}
.scalp-order{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:#22252A;border:1px solid #22252A;border-radius:6px;overflow:hidden;margin:8px 0}.scalp-order span{background:#0E1013;padding:7px 6px;font-size:9.5px;color:#9AA0AA}.scalp-order b{display:block;margin-top:3px;font-size:12px;color:#E8EAED;font-weight:600}.scalp-order .stop b{color:#f0616c}.scalp-order .target b{color:#1fc79a}
.scalp-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;background:#22252A;border:1px solid #22252A;border-radius:6px;overflow:hidden}.scalp-metrics span{background:#0E1013;padding:7px 6px;font-size:9.5px;color:#9AA0AA}.scalp-metrics b{display:block;margin-top:3px;font-size:11px;color:#E8EAED;font-weight:600}
.scalp-foot{margin-top:8px;color:#9AA0AA;font-size:9.5px;line-height:1.4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:1250px){.scalp-strip{grid-template-columns:repeat(3,minmax(205px,1fr))}}
@media(max-width:850px){.scalp-strip{grid-template-columns:repeat(2,minmax(205px,1fr))}}
@media(max-width:560px){.scalp-strip{grid-template-columns:1fr}}
</style>
<nav class="cockpit-tabs" aria-label="コクピット表示切替">
 <span class="cockpit-brand">AIトレードコクピット<small id="cockpit-status">Ver.5.4</small></span>
 <button class="cockpit-tab active" data-tab="scalp">SCALP 5</button>
 <button class="cockpit-tab" data-tab="event-hot">急騰5 / MOMENTUM 5</button>
 <button class="cockpit-tab" data-tab="ms2-live">REALTIME 5</button>
 <button class="cockpit-tab" data-tab="overnight">OVERNIGHT 5</button>
 <button class="cockpit-tab" data-tab="swing">SWING 5</button>
 <button class="cockpit-tab" data-tab="value">VALUE 5</button>
 <button class="cockpit-tab" data-tab="kioxia-calendar">KIOXIA</button>
 <button class="cockpit-tab" data-tab="events">注意</button>
 <details class="secondary-tabs"><summary>参考</summary>
  <button class="cockpit-tab" data-tab="strong-yen">円高恩恵TOP5</button><button class="cockpit-tab" data-tab="us-smr">対米投資・SMR</button>
  <button class="cockpit-tab" data-tab="investor-regime">主体レジーム</button><button class="cockpit-tab" data-tab="market">検証・除外</button>
  <button class="cockpit-tab" data-tab="correlation">相関</button><button class="cockpit-tab" data-tab="wick">下ヒゲ</button>
  <button class="cockpit-tab" data-tab="expansion">拡大</button><button class="cockpit-tab" data-tab="accumulation">大口</button>
  <button class="cockpit-tab" data-tab="policy">国策</button><button class="cockpit-tab" data-tab="weekly">週間</button>
 </details>
</nav>
<script>
document.addEventListener("DOMContentLoaded",()=>{
 const main=document.querySelector("main"); if(!main)return;
 const policyTabs=["physical-ai","autonomous-driving","ai-drug-discovery","ai-semiconductor","defense-space","gx-power","quantum-computing"];
 const panes={}; ["scalp","event-hot","overnight","ms2-live","events","correlation","kioxia-calendar","strong-yen","us-smr","investor-regime","wick","expansion","swing","accumulation","value","policy",...policyTabs,"market","weekly"].forEach(k=>{const d=document.createElement("div");d.className="tab-pane"+(k==="scalp"?" active":"");d.dataset.pane=k;main.appendChild(d);panes[k]=d;});

 const scalpPanel=document.createElement("section");
 scalpPanel.className="card wide scalp-tv";
 scalpPanel.innerHTML='<div class="scalp-tv-toolbar"><div class="scalp-tv-title"><h2>SCALP 5</h2><span>1m / MS2 RSS</span></div><div class="scalp-tv-legend"><span>固定監視 <b>5銘柄</b></span><span>判定 <b>確定1分足</b></span></div></div><div id="scalp-fixed-5" class="scalp-strip"><div class="focus-empty">MS2 RSS接続待ち</div></div>';
 panes.scalp.appendChild(scalpPanel);

 const eventIntro=document.createElement("section");
 eventIntro.className="card wide";
 eventIntro.innerHTML='<h2>急騰5 / MOMENTUM 5</h2><p class="sub">全市場の価格・出来高・売買代金の加速から急騰候補を先に検出する監視枠。材料・ニュースは後段で確認し、未確認でも急騰候補から除外せず「材料未確認」と表示します。</p>';
 panes["event-hot"].appendChild(eventIntro);

 [...main.querySelectorAll(":scope > section")].forEach(s=>{
   if(s===scalpPanel||s===eventIntro)return;
   const t=(s.querySelector("h2")?.textContent||"").trim();
   let k="market";
   if(s.id==="ms2-live-top5")k="ms2-live";
   else if(s.id==="overnight-top5")k="overnight";
   else if(s.dataset.policyTab)k=s.dataset.policyTab;
   else if(s.id==="event-calendar"||t.includes("市場警報"))k="events";
   else if(s.id==="correlation-monitor")k="correlation";
   else if(s.id==="kioxia-5m-calendar")k="kioxia-calendar";
   else if(s.id==="strong-yen-top5")k="strong-yen";
   else if(s.id==="us-smr-watch")k="us-smr";
   else if(s.id==="investor-regime")k="investor-regime";
   else if(s.id==="speculative-theme-monitor"||t.includes("短期急騰期待"))k="event-hot";
   else if(s.id==="data-quality-gate"||s.id==="next-theme-radar"||s.id==="watchlist-100"||s.id==="market-ranking-watch"||s.id==="tradingview-screener-watch"||s.id==="premarket-gap-ranking"||t.includes("IN点灯")||t.includes("準備点灯"))k="ms2-live";
   else if(s.id==="action-dashboard"){ s.remove(); return; }
   else if(s.id==="lower-wick-reversal"||t.includes("下ヒゲ吸収反転"))k="wick";
   else if(t.includes("BB上方エクスパンション"))k="expansion";
   else if(s.id==="weekly-review"||t.includes("週間振り返り"))k="weekly";
   else if(s.id==="large-lot-accumulation"||t.includes("大口買い集め"))k="accumulation";
   else if(s.id==="dividend-rights-watch"||s.id==="buyback-watch"||t.includes("月足・週足反転")||t.includes("50週線")||t.includes("200日線"))k="value";
   else if(t.includes("秋田AI")||t.includes("群馬・茂倉沢")||t.includes("シリコンフォトニクス")||t.includes("当日資金流入テーマ")||s.id==="sector-rotation"||s.id==="policy-priority-overview")k="policy";
   else if(t.includes("安定上昇")||t.includes("52週新高値")||t.includes("過熱監視")||t.includes("持ち越し")||t.includes("AIスイング"))k="swing";
   panes[k].appendChild(s);
 });

 const intros={wick:["最優先・下ヒゲ吸収反転","売り吸収→終値回復→次足上抜けの順で発動。"],expansion:["当日エクスパンション","BB収縮から出来高を伴う拡大が期待できる銘柄。"],swing:["SWING 5","数日〜数週間。デイトレ・オーバーナイト後も強さが継続する候補を確認。"],accumulation:["大口仕込み","出来高・OBV・安値切上げから吸収と蓄積を監視。"],value:["VALUE 5","長期バリュー・高配当・自社株買い・長期反転候補をまとめて確認。"],policy:["国策テーマ・実戦優先順位","政府資料、会社公式、業績寄与、信用需給を分離して確認。"],"physical-ai":["フィジカルAI","本体・AI制御・主要ロボット部品だけを厳格選定。"],"autonomous-driving":["自動運転","社会実装・自動運転ソフト・高精度地図を優先。"],"ai-drug-discovery":["AI創薬","AI創薬を会社公式で事業化している銘柄だけ。"],"ai-semiconductor":["AI・半導体基盤","メモリ、製造装置、テスト、先端SoCに限定。"],"defense-space":["防衛・宇宙","防衛装備、宇宙推進、衛星・官公庁案件を確認。"],"gx-power":["GX・電力基盤","送配電、蓄電池、パワー半導体、電力網。"],"quantum-computing":["量子・先端計算","事業寄与が小さい間は長期研究枠として扱う。"],market:["市場・検証","地合い、答え合わせ、補助分析を確認。"],weekly:["週間レビュー","週末検証と翌週の改善ルール。"]};
 intros.correlation=["相関・先行／逆行銘柄","当日候補の方向を、連動株・逆相関株・米国先行株で確認。"];
 intros.events=["注意","重要イベント・市場警報・売買禁止条件を確認。"];
 intros["investor-regime"]=["投資主体別レジーム","JPX公式の当時利用可能な版だけで、銘柄タイプの追い風・逆風を判定。"];
 intros["kioxia-calendar"]=["KIOXIA","キオクシア専用。5分足カレンダー、MS2 RSS、時間帯統計を集約。"];
 intros["strong-yen"]=["円高恩恵銘柄 TOP5","円高感応度だけでなく、信用需給・当日資金流入・発動価格まで確認。"];
 intros["us-smr"]=["対米投資・SMR","政策発表と個社受注を区別し、事業化・需給・価格の確認順に監視。"];
 intros["ms2-live"]=["REALTIME 5","100銘柄をMS2 RSSで監視し、数十分〜数時間の候補を表示。"];
 intros.overnight=["OVERNIGHT 5","15時前後から採点し、翌朝GU/GDを狙う候補。15:25に銘柄と方向を固定。"];
 Object.entries(intros).forEach(([k,v])=>{if(!panes[k])return;const h=document.createElement("div");h.className="pane-intro";h.innerHTML='<span>AI COCKPIT</span><h2>'+v[0]+'</h2><p>'+v[1]+'</p>';panes[k].prepend(h);});

 const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const num=v=>v==null||!Number.isFinite(Number(v))?null:Number(v);
 const yen=v=>num(v)==null?"—":Number(v).toLocaleString("ja-JP",{maximumFractionDigits:1});
 const pct=v=>num(v)==null?"—":((Number(v)>0?"+":"")+Number(v).toFixed(2)+"%");
 let latestLiveFeed=null;
 const liveSnapshot=(d,ticker)=>{
   if(!d||d.stale!==false)return null;
   const x=(Array.isArray(d.all_targets)?d.all_targets:[]).find(v=>String(v?.ticker||"")===String(ticker||""));
   if(!x)return null;
   const canonical=Number(x.live_price);
   const legacy=Number(x.price);
   const price=(x.live_quote_valid===true&&Number.isFinite(canonical))?canonical:
     (x.live_quote_valid==null&&Number.isFinite(legacy)?legacy:NaN);
   if(!Number.isFinite(price))return null;
   return {...x,price,live_price:price,live_quote_valid:true,live_observed_at:x.live_observed_at||d.live_observed_at||d.updated_at,live_source:x.live_source||d.source||"MarketSpeed II RSS",session_state:x.session_state||d.session_state||d.market_session_state||d.market_state};
 };
 window.cockpitLiveSnapshot=ticker=>liveSnapshot(latestLiveFeed,ticker);
 document.addEventListener("ms2RssUpdate",e=>{latestLiveFeed=e.detail||null;});
 const signalView=(x,stale)=>{
   const raw=String(x?.signal||"監視");
   if(stale||raw.includes("市場時間外"))return {label:"CLOSED",cls:"wait"};
   if(raw.includes("売買禁止")||raw.includes("特別気配"))return {label:"BLOCK",cls:"block"};
   if(raw.includes("買い")||String(x?.raw_direction)==="BUY")return {label:"BUY",cls:"long"};
   if(raw.includes("空売り")||raw.includes("ショート")||String(x?.raw_direction)==="SELL")return {label:"SHORT",cls:"short"};
   return {label:"WAIT",cls:"wait"};
 };
 // 共有カード生成（ユーザー依頼2026-09-19：SCALP 5・OVERNIGHT 5・急騰5 / MOMENTUM 5で同じ銘柄カードにする）。
 // OVERNIGHT 5・急騰5 / MOMENTUM 5はSCALP 5と違いライブMS2データの一部項目（ENTRY/STOP/T1・OR5・出来高加速等）を
 // 持たないため、無い項目は推測で埋めず「—」のまま表示する（既存のyen()/num()の未確認時「—」表示を踏襲）。
 window.renderScalpCard=(x,sv,tf)=>{
   const chg=x.change_pct==null?null:num(x.change_pct),chgCls=chg==null?"flat":(chg>0?"up":chg<0?"down":"flat");
   const code=String(x.code||x.ticker||"").replace(".T","");
   const or5=(num(x.or5_low)>0&&num(x.or5_high)>0)?yen(x.or5_low)+" – "+yen(x.or5_high):"—";
   const or15=(num(x.or_low)>0&&num(x.or_high)>0)?yen(x.or_low)+" – "+yen(x.or_high):"—";
   const ema=(num(x.ema9)!=null&&num(x.ema20)!=null)?yen(x.ema9)+" / "+yen(x.ema20):"—";
   const flow=x.flow_bias==null?"—":esc(x.flow_bias)+"%";
   const vol=x.volume_burst==null?"—":esc(x.volume_burst)+"x";
   const verified=num(x.price)>0&&x.live_quote_valid!==false;
   const observed=x.live_observed_at||x.observed_at||x.updated_at||"時刻未確認";
   const source=x.live_source||x.source||"MS2 RSS";
   const session=x.session_state||x.market_session_state||x.market_state||"SESSION未確認";
   const proof=verified?'<div class="live-state-proof"><b>MS2 LIVE</b><span>'+esc(session)+'</span><span>観測 '+esc(observed)+'</span><small>'+esc(source)+'</small></div>':'<div class="live-state-proof"><b>LIVE DATA INVALID</b><span>現在値は表示しません</span></div>';
   return '<article class="scalp-card '+sv.cls+(verified?' live-verified':' live-invalid')+'"><div class="scalp-head"><div class="scalp-symbol"><strong>'+esc(x.name)+'</strong><small>TSE:'+esc(code)+' · '+esc(tf||"1m")+'</small></div><span class="scalp-signal">'+esc(sv.label)+'</span></div><div class="scalp-price-row"><div class="scalp-price">'+yen(x.price)+'</div><div class="scalp-change '+chgCls+'">'+pct(x.change_pct)+'</div></div>'+proof+'<div class="scalp-order"><span class="entry">ENTRY<b>'+yen(x.entry_price)+'</b></span><span class="stop">STOP<b>'+yen(x.stop_price)+'</b></span><span class="target">T1<b>'+yen(x.target1)+'</b></span></div><div class="scalp-metrics"><span>VWAP<b>'+yen(x.vwap)+'</b></span><span>OR5<b>'+or5+'</b></span><span>OR15<b>'+or15+'</b></span><span>EMA 9 / 20<b>'+ema+'</b></span><span>FLOW<b>'+flow+'</b></span><span>VOLUME<b>'+vol+'</b></span></div><div class="scalp-foot">'+esc(x.foot||"")+'</div></article>';
 };
 document.addEventListener("ms2RssUpdate",e=>{
   const d=e.detail||{},all=Array.isArray(d.all_targets)?d.all_targets:[],stale=d.stale!==false;
   const fixed=["285A.T","9984.T","8035.T","6920.T","6857.T"];
   const box=document.getElementById("scalp-fixed-5"); if(!box)return;
   const rows=fixed.map(t=>({ticker:t,row:liveSnapshot(d,t)}));
   box.innerHTML=rows.map(({ticker,row:x})=>{
     if(!x)return window.renderScalpCard({ticker,name:ticker.replace(".T",""),price:null,foot:"LIVE DATA INVALID / 現在値は表示しません"},{label:"INVALID",cls:"block"},"1m");
     const sv=signalView(x,false);
     return window.renderScalpCard({...x,foot:(x.signal||"監視")+' · '+(x.strategy||"条件待ち")},sv,"1m");
   }).join("");
 });

 document.querySelectorAll(".cockpit-tab").forEach(b=>b.onclick=()=>{
   document.querySelectorAll(".cockpit-tab").forEach(x=>x.classList.toggle("active",x===b));
   document.querySelectorAll(".tab-pane").forEach(x=>x.classList.toggle("active",x.dataset.pane===b.dataset.tab));
   localStorage.setItem("cockpitTabV5",b.dataset.tab);
   if(b.dataset.tab==="kioxia-calendar"&&window.kioChart)requestAnimationFrame(()=>requestAnimationFrame(()=>window.kioChart.timeScale().fitContent()));
 });
 const requested=new URLSearchParams(location.search).get("live")==="1"?"scalp":null;
 const saved=requested||localStorage.getItem("cockpitTabV5"); if(saved)document.querySelector('.cockpit-tab[data-tab="'+saved+'"]')?.click();

 fetch("event_calendar.json?t="+Date.now()).then(r=>r.json()).then(d=>{
   const b=document.querySelector('.cockpit-tab[data-tab="events"]');
   if(d.today_level!=="通常"){b.classList.add("event-alert");b.textContent="⚠ 注意";}
 }).catch(()=>{});
 fetch("signals.json?t="+Date.now()).then(r=>r.json()).then(d=>{
   const badge=document.getElementById("cockpit-status"); if(!badge)return;
   const todayJst=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
   const nowHm=new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date());
   const weekdayJst=new Intl.DateTimeFormat("en-US",{timeZone:"Asia/Tokyo",weekday:"short"}).format(new Date());
   const isWeekend=weekdayJst==="Sat"||weekdayJst==="Sun";
   const updatedAt=String(d.updated_at||"");
   const isToday=updatedAt.slice(0,10)===todayJst;
   let cls="status-ok",title="正常稼働中／最終更新 "+(updatedAt||"不明");
   if(!isToday&&!isWeekend){
     if(nowHm<"08:20"){cls="status-warn";title="本日の初回更新前（前営業日分を表示中）／最終更新 "+(updatedAt||"不明");}
     else{cls="status-error";title="更新停止の疑い／最終更新 "+(updatedAt||"不明");}
   }
   badge.classList.remove("status-ok","status-warn","status-error");
   badge.classList.add(cls);
   badge.title=title;
 }).catch(()=>{});
});
</script>
""" + END

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
