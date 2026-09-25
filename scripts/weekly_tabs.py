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
        return (
            f'{WSTART}<section id="weekly-review" class="card wide">'
            '<div class="pane-intro"><span>AI COCKPIT</span><h2>週間振り返り・来週戦略</h2>'
            '<p>土曜日の集計後に表示します。</p></div></section>'
            f'{WEND}'
        )

    def metric(label: str, value: str) -> str:
        return f'<span>{html.escape(label)}<b>{html.escape(value)}</b></span>'

    def review_card(x: dict, badge: str, css: str) -> str:
        ticker = str(x.get("ticker") or "").replace(".T", "")
        pnl = x.get("pnl_yen")
        r_value = x.get("r")
        pnl_text = "—" if pnl is None else f"{float(pnl):+,.0f}円"
        r_text = "—" if r_value is None else f"{float(r_value):+.2f}R"
        return (
            f'<article class="cc-card cc-card--{css}">'
            '<div class="cc-head"><div class="cc-identity">'
            f'<span class="cc-company">{html.escape(str(x.get("name") or ticker or "取引"))}</span>'
            f'<span class="cc-symbol">TSE:{html.escape(ticker or "—")}</span>'
            f'</div><span class="cc-badge">{html.escape(badge)}</span></div>'
            '<div class="cc-metrics-grid">'
            + metric("損益", pnl_text)
            + metric("R", r_text)
            + metric("ENTRY", str(x.get("entry") or x.get("simulated_fill") or "—"))
            + metric("結果", str(x.get("result") or "—"))
            + '</div>'
            f'<div class="cc-foot">{html.escape(str(x.get("date") or ""))} / '
            f'{html.escape(str(x.get("strategy_id") or "strategy未タグ"))}</div>'
            '</article>'
        )

    best = "".join(
        review_card(x, "BEST", "long" if float(x.get("pnl_yen") or 0) >= 0 else "short")
        for x in w.get("best", [])
    ) or (
        '<article class="cc-card cc-card--wait"><div class="cc-head">'
        '<div class="cc-identity"><span class="cc-company">確定取引なし</span>'
        '<span class="cc-symbol">AI COCKPIT</span></div><span class="cc-badge">—</span>'
        '</div></article>'
    )
    worst = "".join(
        review_card(x, "REVIEW", "short" if float(x.get("pnl_yen") or 0) < 0 else "wait")
        for x in w.get("worst", [])
    ) or best

    theme_text = "・".join(str(x) for x in w.get("themes", [])) or "更新待ち"
    rule_text = " / ".join(
        f"{i + 1}. {x}" for i, x in enumerate(w.get("next_rules", []))
    ) or "更新待ち"
    pnl = float(w.get("pnl") or 0)
    result_css = "long" if pnl > 0 else "short" if pnl < 0 else "wait"

    summary = (
        f'<article class="cc-card cc-card--{result_css}">'
        '<div class="cc-head"><div class="cc-identity"><span class="cc-company">週間成績</span>'
        '<span class="cc-symbol">AI COCKPIT</span></div>'
        f'<span class="cc-badge">{html.escape(str(w.get("decision") or "REVIEW"))}</span></div>'
        '<div class="cc-metrics-grid">'
        + metric("仮想取引", f'{int(w.get("count") or 0)}件')
        + metric("勝率", f'{float(w.get("win_rate") or 0):.1f}%')
        + metric("PF", f'{float(w.get("pf") or 0):.2f}')
        + metric("平均R", f'{float(w.get("avg_r") or 0):+.2f}R')
        + metric("週間損益", f'{int(w.get("pnl") or 0):+,}円')
        + '</div><div class="cc-foot">仮想検証/Shadowの集計で、実口座損益ではありません。</div>'
        '</article>'
    )
    theme_card = (
        '<article class="cc-card cc-card--wait"><div class="cc-head">'
        '<div class="cc-identity"><span class="cc-company">来週の注目テーマ</span>'
        '<span class="cc-symbol">THEME</span></div><span class="cc-badge">WATCH</span></div>'
        f'<div class="cc-catalyst">{html.escape(theme_text)}</div>'
        '<div class="cc-foot">テーマ候補であり、保有建玉ではありません。</div></article>'
    )
    rule_card = (
        '<article class="cc-card cc-card--wait"><div class="cc-head">'
        '<div class="cc-identity"><span class="cc-company">来週のルール</span>'
        '<span class="cc-symbol">RULES</span></div><span class="cc-badge">PLAN</span></div>'
        f'<div class="cc-catalyst">{html.escape(rule_text)}</div></article>'
    )

    return f"""{WSTART}
<section id="weekly-review" class="card wide">
  <div class="pane-intro"><span>AI COCKPIT</span><h2>週間振り返り・来週戦略</h2>
    <p>{html.escape(w['week'])}｜作成 {html.escape(w['created_at'])}</p>
  </div>
  <div class="cc-grid">{summary}{theme_card}{rule_card}</div>
  <h3>良かった取引</h3><div class="cc-grid">{best}</div>
  <h3>改善する取引</h3><div class="cc-grid">{worst}</div>
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
 <button class="cockpit-tab" data-tab="control">CONTROL</button>
 <button class="cockpit-tab active" data-tab="scalp">SCALP 5</button>
 <button class="cockpit-tab" data-tab="event-hot">EVENT 5</button>
 <button class="cockpit-tab" data-tab="ms2-live">REALTIME 5</button>
 <button class="cockpit-tab" data-tab="overnight">OVERNIGHT 5</button>
 <button class="cockpit-tab" data-tab="swing">SWING 5</button>
 <button class="cockpit-tab" data-tab="value">VALUE 5</button>
 <button class="cockpit-tab" data-tab="kioxia-calendar">KIOXIA</button>
 <button class="cockpit-tab" data-tab="events">注意</button>
 <details class="secondary-tabs"><summary>参考</summary>
  <button class="cockpit-tab" data-tab="research">RESEARCH</button>
  <button class="cockpit-tab" data-tab="strong-yen">円高恩恵TOP5</button><button class="cockpit-tab" data-tab="us-smr">対米投資・SMR</button>
  <button class="cockpit-tab" data-tab="investor-regime">主体レジーム</button><button class="cockpit-tab" data-tab="market">検証・除外</button>
  <button class="cockpit-tab" data-tab="correlation">相関</button><button class="cockpit-tab" data-tab="wick">下ヒゲ</button>
  <button class="cockpit-tab" data-tab="expansion">拡大</button><button class="cockpit-tab" data-tab="accumulation">大口</button>
  <button class="cockpit-tab" data-tab="policy">国策</button><button class="cockpit-tab" data-tab="weekly">週間</button>
 </details>
</nav>
<script src="opportunity_radar.js?v=v9-1" defer></script>
<script src="trade_control.js?v=v9-1" defer></script>
<script>
document.addEventListener("DOMContentLoaded",()=>{
 const main=document.querySelector("main"); if(!main)return;
 const policyTabs=["physical-ai","autonomous-driving","ai-drug-discovery","ai-semiconductor","defense-space","gx-power","quantum-computing"];
 const panes={}; ["control","scalp","event-hot","overnight","ms2-live","events","research","correlation","kioxia-calendar","strong-yen","us-smr","investor-regime","wick","expansion","swing","accumulation","value","policy",...policyTabs,"market","weekly"].forEach(k=>{const d=document.createElement("div");d.className="tab-pane"+(k==="scalp"?" active":"");d.dataset.pane=k;main.appendChild(d);panes[k]=d;});

 const scalpPanel=document.createElement("section");
 scalpPanel.className="card wide scalp-tv";
 scalpPanel.innerHTML='<div class="scalp-tv-toolbar"><div class="scalp-tv-title"><h2>SCALP 5</h2><span>1m / MS2 RSS</span></div><div class="scalp-tv-legend"><span>固定監視 <b>5銘柄</b></span><span>判定 <b>確定1分足</b></span></div></div><div id="scalp-fixed-5" class="scalp-strip"><div class="focus-empty">MS2 RSS接続待ち</div></div>';
 panes.scalp.appendChild(scalpPanel);

 const eventIntro=document.createElement("section");
 eventIntro.className="card wide";
 eventIntro.innerHTML='<h2>EVENT 5</h2><p class="sub">小型グロース・テーマ株・材料急騰・場中決算の初動監視枠。現時点では全市場の仕手化兆候／短期急騰スキャンを集約し、リアルタイム材料スキャナはこの枠へ接続します。</p>';
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
   else if(s.id==="data-quality-gate"){s.remove();return;}
   else if(s.id==="next-theme-radar")k="research";
   else if(s.id==="action-dashboard"||s.id==="watchlist-100"||s.id==="market-ranking-watch"||s.id==="tradingview-screener-watch"||s.id==="premarket-gap-ranking"||t.includes("IN点灯")||t.includes("準備点灯"))k="ms2-live";
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
 intros.control=["取引・建玉・成績","実発注ロック、建玉の接続状態、各タブの成績を一括確認。"];
 intros.research=["RESEARCH","ニュース・テーマ・需給・決算などを発掘し、条件を満たした候補だけ戦略タブへ昇格させる情報収集レイヤー。"];
 intros.correlation=["相関・先行／逆行銘柄","当日候補の方向を、連動株・逆相関株・米国先行株で確認。"];
 intros.events=["注意","重要イベント・市場警報・売買禁止条件を確認。"];
 intros["investor-regime"]=["投資主体別レジーム","JPX公式の当時利用可能な版だけで、銘柄タイプの追い風・逆風を判定。"];
 intros["kioxia-calendar"]=["KIOXIA","キオクシア専用。5分足カレンダー、MS2 RSS、時間帯統計を集約。"];
 intros["strong-yen"]=["円高恩恵銘柄 TOP5","円高感応度だけでなく、信用需給・当日資金流入・発動価格まで確認。"];
 intros["us-smr"]=["対米投資・SMR","政策発表と個社受注を区別し、事業化・需給・価格の確認順に監視。"];
 intros["ms2-live"]=["REALTIME 5","100銘柄をMS2 RSSで監視し、数十分〜数時間の候補を表示。"];
 intros.overnight=["OVERNIGHT 5","15時前後から採点し、翌朝GU/GDを狙う候補。15:25に銘柄と方向を固定。"];
 Object.entries(intros).forEach(([k,v])=>{if(!panes[k])return;const h=document.createElement("div");h.className="pane-intro";h.innerHTML='<span>AI COCKPIT</span><h2>'+v[0]+'</h2><p>'+v[1]+'</p>';panes[k].prepend(h);});

 // PTS / IR+PTS are event-discovery feeds, not execution-facing REALTIME 5.
 // Keep their existing IDs so the live loader continues updating them after
 // they are moved into EVENT 5.
 const ptsHead=document.querySelector(".pts-section-head");
 const ptsCards=document.getElementById("ms2-pts-cards");
 const irMeta=document.getElementById("ms2-ir-pts-meta");
 const irCards=document.getElementById("ms2-ir-pts-cards");
 const irHead=irMeta?.previousElementSibling?.tagName==="H3"?irMeta.previousElementSibling:null;
 if(ptsHead||ptsCards||irMeta||irCards){
   const eventFeeds=document.createElement("section");
   eventFeeds.id="event-overnight-feeds";
   eventFeeds.className="card wide";
   eventFeeds.innerHTML='<div class="pane-intro"><span>EVENT DISCOVERY</span><h2>夜間PTS・IR反応</h2><p>前夜から資金が動いた候補をEVENT 5へ集約。鮮度・流動性・材料確認を通らない候補は売買判断に使いません。</p></div>';
   [ptsHead,ptsCards,irHead,irMeta,irCards].filter(Boolean).forEach(el=>eventFeeds.appendChild(el));
   panes["event-hot"].appendChild(eventFeeds);
 }

 const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const num=v=>v==null||!Number.isFinite(Number(v))?null:Number(v);
 const yen=v=>num(v)==null?"—":Number(v).toLocaleString("ja-JP",{maximumFractionDigits:1});
 const pct=v=>num(v)==null?"—":((Number(v)>0?"+":"")+Number(v).toFixed(2)+"%");
 const signalView=(x,stale)=>{
   const raw=String(x?.signal||"監視");
   if(stale||raw.includes("市場時間外"))return {label:"CLOSED",cls:"wait"};
   if(raw.includes("売買禁止")||raw.includes("特別気配"))return {label:"BLOCK",cls:"block"};
   if(raw.includes("買い")||String(x?.raw_direction)==="BUY")return {label:"BUY",cls:"long"};
   if(raw.includes("空売り")||raw.includes("ショート")||String(x?.raw_direction)==="SELL")return {label:"SHORT",cls:"short"};
   return {label:"WAIT",cls:"wait"};
 };
 const sparkline=bars=>{
   const vals=(Array.isArray(bars)?bars:[]).slice(-36).map(b=>num(b?.c??b?.Close)).filter(v=>v!=null);
   if(vals.length<2)return '<svg viewBox="0 0 100 54" preserveAspectRatio="none"><line class="grid" x1="0" y1="27" x2="100" y2="27"/></svg>';
   const lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(hi-lo,0.0001);
   const pts=vals.map((v,i)=>((i/(vals.length-1))*100).toFixed(2)+","+(50-((v-lo)/span)*44).toFixed(2)).join(" ");
   return '<svg viewBox="0 0 100 54" preserveAspectRatio="none"><line class="grid" x1="0" y1="27" x2="100" y2="27"/><polyline class="line" points="'+pts+'"/></svg>';
 };
 // 共有カード生成（ユーザー依頼2026-09-19：SCALP 5・OVERNIGHT 5・EVENT 5で同じ銘柄カードにする）。
 // OVERNIGHT 5・EVENT 5はSCALP 5と違いライブMS2データの一部項目（ENTRY/STOP/T1・OR5・出来高加速等）を
 // 持たないため、無い項目は推測で埋めず「—」のまま表示する（既存のyen()/num()の未確認時「—」表示を踏襲）。
 window.renderScalpCard=(x,sv,tf)=>{
   const code=String(x.code||x.ticker||"").replace(".T","");
   const dir=sv.cls==="long"?"long":sv.cls==="short"?"short":sv.cls==="block"?"block":"wait";
   const isStaleCard=x?._stale===true;
   const fmt=v=>v==null||!Number.isFinite(Number(v))?null:Number(v).toLocaleString("ja-JP",{maximumFractionDigits:1});
   const range=(lo,hi)=>num(lo)>0&&num(hi)>0?fmt(lo)+" – "+fmt(hi):null;
   return window.renderCockpitCard({
     symbol:code,company:x.name,direction:dir,directionLabel:sv.label,
     freshness:isStaleCard?"stale":undefined,
     freshnessLabel:isStaleCard?"データ停止":undefined,
     failClosed:isStaleCard?"鮮度確認不可":false,
     price:x.price,changePct:x.change_pct,
     sparkline:x.bars_1m,sparklineLabel:"直近15分・1分足終値",
     entry:x.entry_price,stop:x.stop_price,target:x.target1,
     metrics:[
       {label:"時間軸",value:tf||"1m"},
       {label:"VWAP",value:fmt(x.vwap)},
       {label:"OR5",value:range(x.or5_low,x.or5_high)},
       {label:"OR15",value:range(x.or_low,x.or_high)},
       {label:"EMA 9/20",value:(num(x.ema9)!=null&&num(x.ema20)!=null)?fmt(x.ema9)+" / "+fmt(x.ema20):null},
       {label:"FLOW",value:x.flow_bias==null?null:esc(x.flow_bias)+"%"},
       {label:"VOLUME",value:x.volume_burst==null?null:esc(x.volume_burst)+"x"}
     ],
     foot:x.foot||""
   });
 };
 document.addEventListener("ms2RssUpdate",e=>{
   const d=e.detail||{},all=Array.isArray(d.all_targets)?d.all_targets:[],stale=d.stale!==false;
   const fixed=["285A.T","9984.T","8035.T","6920.T","6857.T"];
   const box=document.getElementById("scalp-fixed-5"); if(!box)return;
   const rows=fixed.map(t=>all.find(x=>String(x.ticker)===t)).filter(Boolean);
   box.innerHTML=rows.length?rows.map(x=>{
     const sv=signalView(x,stale);
     return window.renderScalpCard({...x,_stale:stale,foot:(x.signal||"監視")+' · '+(x.strategy||"条件待ち")},sv,"1m");
   }).join(""):'<div class="focus-empty">SCALP 5のMS2 RSSデータ待ち</div>';
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
