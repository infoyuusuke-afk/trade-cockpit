(()=>{
  "use strict";

  const TAB_LABELS={
    control:"CONTROL",scalp:"SCALP 5","event-hot":"EVENT 5","ms2-live":"REALTIME 5",
    overnight:"OVERNIGHT 5",swing:"SWING 5",value:"VALUE 5","kioxia-calendar":"KIOXIA",
    events:"注意",correlation:"相関","strong-yen":"円高恩恵","us-smr":"対米投資・SMR",
    "investor-regime":"主体レジーム",wick:"下ヒゲ",expansion:"拡大",accumulation:"大口",
    policy:"国策","physical-ai":"フィジカルAI","autonomous-driving":"自動運転",
    "ai-drug-discovery":"AI創薬","ai-semiconductor":"AI半導体","defense-space":"防衛・宇宙",
    "gx-power":"GX・電力","quantum-computing":"量子",market:"市場・検証",weekly:"週間"
  };
  const TRADE_TABS=new Set(["scalp","event-hot","ms2-live","overnight","swing","value","kioxia-calendar"]);

  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const money=v=>Number.isFinite(Number(v))?(Number(v)>=0?"+":"")+Number(v).toLocaleString("ja-JP")+"円":"—";
  const pct=v=>Number.isFinite(Number(v))?Number(v).toFixed(1)+"%":"—";
  const rfmt=v=>Number.isFinite(Number(v))?(Number(v)>=0?"+":"")+Number(v).toFixed(2)+"R":"—";

  function metricCard(title,badge,metrics,foot,cls="wait"){
    return '<article class="cc-card cc-card--'+cls+'">'+
      '<div class="cc-head"><div class="cc-identity"><span class="cc-company">'+esc(title)+'</span>'+
      '<span class="cc-symbol">AI COCKPIT</span></div><span class="cc-badge">'+esc(badge)+'</span></div>'+
      '<div class="cc-metrics-grid">'+metrics.filter(x=>x&&x[1]!=null).map(x=>'<span>'+esc(x[0])+'<b>'+esc(x[1])+'</b></span>').join("")+'</div>'+
      (foot?'<div class="cc-foot">'+esc(foot)+'</div>':"")+
      '</article>';
  }

  function classifyRecord(x){
    const explicit=String(x?.cockpit_tab||x?.tab||"").trim();
    if(explicit&&TAB_LABELS[explicit])return explicit;
    const s=String(x?.strategy_id||"").toLowerCase();
    if(s==="day_rank_long"||s==="day_short_mvp")return "ms2-live";
    if(s.includes("scalp"))return "scalp";
    if(s.includes("overnight")||s.includes("hold"))return "overnight";
    if(s.includes("swing"))return "swing";
    if(s.includes("value")||s.includes("dividend")||s.includes("buyback"))return "value";
    if(s.includes("kioxia")||s.includes("285a"))return "kioxia-calendar";
    if(s.includes("event")||s.includes("material")||s.includes("ir_"))return "event-hot";
    return null;
  }

  const resultExitReason=x=>{
    const explicit=String(x?.exit_reason||"").trim();
    if(explicit)return explicit;
    const map={"未発動（見送り）":"NOT_TRIGGERED","順序不明（成績除外）":"AMBIGUOUS_EXCLUDED","IFO損切り":"STOP","IFO利確1":"TARGET1","IFO利確2":"TARGET2","時点評価・未決済":"OPEN_MARK","大引け決済":"EOD"};
    return map[String(x?.result||"").trim()]||"UNKNOWN";
  };
  const isRealized=x=>{
    const reason=resultExitReason(x);
    if(["OPEN_MARK","NOT_TRIGGERED","AMBIGUOUS_EXCLUDED","UNKNOWN",""].includes(reason))return false;
    return Number.isFinite(Number(x?.pnl_yen));
  };
  const classifyMode=x=>{
    let raw=String(x?.execution_mode||x?.trade_mode||x?.mode||"").trim().toLowerCase();
    const aliases={paper:"shadow","paper_trade":"shadow","paper-trade":"shadow",sim:"shadow",simulation:"shadow",live:"real",broker:"real",historical:"backtest"};
    raw=aliases[raw]||raw;
    return ["real","shadow","backtest"].includes(raw)?raw:"unknown";
  };

  function computeStats(rows){
    const done=rows.filter(isRealized).slice().sort((a,b)=>String(a?.date||"").localeCompare(String(b?.date||""))||String(a?.signal_time||"").localeCompare(String(b?.signal_time||"")));
    if(!done.length)return null;
    const wins=done.filter(x=>Number(x.pnl_yen)>0).length;
    const gains=done.reduce((a,x)=>a+Math.max(0,Number(x.pnl_yen)||0),0);
    const losses=Math.abs(done.reduce((a,x)=>a+Math.min(0,Number(x.pnl_yen)||0),0));
    const rRows=done.filter(x=>Number.isFinite(Number(x?.r??x?.R)));
    let equity=0,peak=0,maxDD=0;
    done.forEach(x=>{equity+=Number(x.pnl_yen)||0;peak=Math.max(peak,equity);maxDD=Math.min(maxDD,equity-peak);});
    const modeSet=[...new Set(rows.map(classifyMode))];
    return {
      count:done.length,
      wins,
      winRate:wins/done.length*100,
      pnl:done.reduce((a,x)=>a+(Number(x.pnl_yen)||0),0),
      pf:losses>0?gains/losses:null,
      pfStatus:losses>0?"FINITE":gains>0?"NO_LOSSES":"NO_GAIN_NO_LOSS",
      avgR:rRows.length?rRows.reduce((a,x)=>a+Number(x.r??x.R),0)/rRows.length:null,
      maxDD,
      openMark:rows.filter(x=>resultExitReason(x)==="OPEN_MARK").length,
      mode:modeSet.length===1?modeSet[0]:"mixed"
    };
  }

  function performanceHtml(tab,stats,unclassified){
    const label=TAB_LABELS[tab]||tab;
    if(!TRADE_TABS.has(tab)){
      return metricCard(label+" 成績","参考タブ",[
        ["損益集計","対象外"],["売買実績","—"]
      ],"このタブは現在、売買戦略の成績集計対象ではありません。","wait");
    }
    if(!stats){
      return metricCard(label+" 成績","未接続",[
        ["取引件数","—"],["勝率","—"],["PF","—"],["平均R","—"],["損益","—"]
      ],"このタブ名に紐づく実績タグがまだありません。0件とは解釈しません。","block");
    }
    const cls=stats.pnl>0?"long":stats.pnl<0?"short":"wait";
    const modeLabel=stats.mode==="shadow"?"SHADOW":stats.mode==="real"?"REAL":stats.mode==="backtest"?"BACKTEST":stats.mode==="unknown"?"MODE不明":"MIXED MODE";
    return metricCard(label+" 成績",modeLabel,[
      ["確定取引",stats.count+"件"],["勝率",pct(stats.winRate)],["PF",stats.pf==null?(stats.pfStatus==="NO_LOSSES"?"損失なし":"—"):stats.pf.toFixed(2)],
      ["平均R",rfmt(stats.avgR)],["損益",money(stats.pnl)],["最大DD",money(stats.maxDD)],["未決済評価",stats.openMark+"件"]
    ],"確定済み実績だけを集計。OPEN_MARKは損益・勝敗へ混ぜません。未分類履歴 "+unclassified+"件も除外。",cls);
  }

  function executionHtml(exec,runtime){
    const known=!!exec;
    const realAllowed=exec?.real_submit_allowed===true;
    const brokerConnected=exec?.broker_positions_connected===true;
    const brokerCount=brokerConnected&&Number.isFinite(Number(exec?.broker_position_count))
      ? String(exec.broker_position_count)+"件":"未接続";
    const shadowConnected=exec?.shadow_positions_connected===true;
    const shadowCount=shadowConnected&&Number.isFinite(Number(exec?.shadow_open_position_count))
      ? String(exec.shadow_open_position_count)+"件":"未接続";
    const cls=realAllowed?"short":"block";
    return metricCard("取引・建玉コントロール",realAllowed?"REAL ORDER ON":"REAL ORDER LOCKED",[
      ["実発注",known?(realAllowed?"ON":"OFF固定"):"状態取得不能"],
      ["実建玉",brokerCount],
      ["Shadow建玉",shadowCount],
      ["実注文経路",exec?.real_order_route||"UNKNOWN"],
      ["Runtime",runtime?.fail_closed===false?"監視稼働":"FAIL-CLOSED"]
    ],brokerConnected
      ?"実建玉はブローカー照合済みです。"
      :"ブローカー建玉は未接続です。『0件』ではありません。現在のAI Cockpitは実発注を許可していません。",cls);
  }

  function ensureSummarySection(pane,tab){
    let section=pane.querySelector(":scope > .cc-tab-owner-summary");
    if(section)return section;
    section=document.createElement("section");
    section.className="card wide cc-tab-owner-summary";
    section.innerHTML='<div class="cc-grid"><div data-tab-performance>成績読込中...</div><div data-execution-control>実行状態読込中...</div></div>';
    const intro=pane.querySelector(":scope > .pane-intro");
    if(intro)intro.insertAdjacentElement("afterend",section);
    else pane.prepend(section);
    return section;
  }

  async function loadHistory(){
    try{
      const r=await fetch("paper_trade_history.json?t="+Date.now(),{cache:"no-store"});
      if(!r.ok)throw new Error("history unavailable");
      const rows=await r.json();
      return Array.isArray(rows)?rows:[];
    }catch(_e){return [];}
  }

  async function loadPerformance(){
    try{
      const r=await fetch("performance_by_strategy.json?t="+Date.now(),{cache:"no-store"});
      if(!r.ok)throw new Error("performance unavailable");
      const data=await r.json();
      return data&&Array.isArray(data.strategies)?data:null;
    }catch(_e){return null;}
  }

  function performanceSparkline(series){
    const rows=Array.isArray(series)?series:[];
    const vals=rows.map(x=>Number(x?.cum_pnl_yen)).filter(Number.isFinite);
    if(vals.length<2)return '<div class="cc-perf-spark-empty">推移データ不足</div>';
    const lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1,hi-lo);
    const points=vals.map((v,i)=>((i/(vals.length-1))*100).toFixed(2)+","+(38-((v-lo)/span)*34).toFixed(2)).join(" ");
    return '<svg class="cc-perf-spark" viewBox="0 0 100 42" preserveAspectRatio="none" aria-label="累積損益推移"><line x1="0" y1="39" x2="100" y2="39"></line><polyline points="'+points+'"></polyline></svg>';
  }

  function ensurePerformanceStyles(){
    if(document.getElementById("cc-performance-style"))return;
    const style=document.createElement("style");
    style.id="cc-performance-style";
    style.textContent='.cc-performance-board{display:grid;gap:12px}.cc-performance-rank{display:grid;gap:7px}.cc-performance-row{display:grid;grid-template-columns:minmax(120px,1.1fr) minmax(140px,2fr) auto;gap:10px;align-items:center}.cc-performance-row>span{font-size:12px;color:#c7cacd}.cc-performance-row small{display:block;color:#737982}.cc-performance-track{height:10px;background:#17191d;border:1px solid #272a30;border-radius:999px;overflow:hidden}.cc-performance-fill{height:100%;background:currentColor;min-width:2px}.cc-performance-row.long{color:#35e2ae}.cc-performance-row.short{color:#f0616c}.cc-performance-row.wait{color:#7c838d}.cc-performance-row>b{font-variant-numeric:tabular-nums;color:#e8eaed}.cc-performance-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}.cc-performance-card{background:#0b0c0f;border:1px solid #272a30;border-radius:9px;padding:11px}.cc-performance-card h4{margin:0 0 3px;font-size:13px;color:#e8eaed}.cc-performance-card .mode{font-size:10px;color:#8e949d}.cc-performance-card .metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:#272a30;margin-top:8px}.cc-performance-card .metrics span{background:#101216;padding:6px;color:#848b94;font-size:9px}.cc-performance-card .metrics b{display:block;margin-top:2px;color:#e8eaed;font-size:11px}.cc-perf-spark{width:100%;height:42px;margin-top:8px}.cc-perf-spark line{stroke:#25282e;stroke-width:1}.cc-perf-spark polyline{fill:none;stroke:currentColor;stroke-width:1.8;vector-effect:non-scaling-stroke}.cc-perf-spark-empty{height:42px;display:flex;align-items:center;color:#666d76;font-size:10px}.cc-performance-note{color:#737982;font-size:11px}@media(max-width:650px){.cc-performance-row{grid-template-columns:1fr auto}.cc-performance-track{grid-column:1/-1}.cc-performance-card .metrics{grid-template-columns:repeat(2,1fr)}}';
    document.head.appendChild(style);
  }

  function strategyDashboardHtml(perf){
    const lanes=Array.isArray(perf?.strategies)?perf.strategies:[];
    const missing=Array.isArray(perf?.missing_strategy_tabs)?perf.missing_strategy_tabs:[];
    if(!lanes.length){
      return '<div class="cc-performance-board"><div class="cc-performance-note">戦略別の確定実績がまだ分類されていません。未接続を0件とは扱いません。</div></div>';
    }
    const comparable=lanes.filter(x=>Number.isFinite(Number(x?.pnl_yen)));
    const maxAbs=Math.max(1,...comparable.map(x=>Math.abs(Number(x.pnl_yen))));
    const ordered=comparable.slice().sort((a,b)=>Number(b.pnl_yen)-Number(a.pnl_yen));
    const rank=ordered.map(x=>{
      const pnl=Number(x.pnl_yen),cls=pnl>0?"long":pnl<0?"short":"wait",width=Math.max(2,Math.abs(pnl)/maxAbs*100);
      return '<div class="cc-performance-row '+cls+'"><span>'+esc(x.label||TAB_LABELS[x.tab]||x.tab)+'<small>'+esc(String(x.mode||"unknown").toUpperCase())+' / n='+esc(x.sample_count??0)+'</small></span><div class="cc-performance-track"><div class="cc-performance-fill" style="width:'+width.toFixed(1)+'%"></div></div><b>'+money(pnl)+'</b></div>';
    }).join("");
    const cards=lanes.map(x=>{
      const pnl=Number(x?.pnl_yen),cls=Number.isFinite(pnl)?(pnl>0?"long":pnl<0?"short":"wait"):"wait";
      const pf=x?.pf==null?(x?.pf_status==="NO_LOSSES"?"損失なし":"—"):Number(x.pf).toFixed(2);
      return '<article class="cc-performance-card '+cls+'"><h4>'+esc(x.label||TAB_LABELS[x.tab]||x.tab)+'</h4><span class="mode">'+esc(String(x.mode||"unknown").toUpperCase())+'</span>'+performanceSparkline(x.cumulative_series)+'<div class="metrics"><span>確定<b>'+esc(x.sample_count??"—")+'件</b></span><span>勝率<b>'+pct(x.win_rate)+'</b></span><span>PF<b>'+esc(pf)+'</b></span><span>平均R<b>'+rfmt(x.avg_r)+'</b></span><span>最大DD<b>'+money(x.max_drawdown_yen)+'</b></span><span>損益<b>'+money(x.pnl_yen)+'</b></span></div></article>';
    }).join("");
    const note='未分類 '+esc(perf?.unclassified_record_count??"—")+'件 / mode不明 '+esc(perf?.unknown_mode_record_count??"—")+'件'+(missing.length?' / 未接続戦略 '+missing.length+'個':'');
    return '<div class="cc-performance-board"><div class="cc-performance-rank">'+rank+'</div><div class="cc-performance-cards">'+cards+'</div><div class="cc-performance-note">'+note+'。REAL/SHADOW/BACKTESTは混合しません。</div></div>';
  }

  async function loadHealth(){
    try{
      const r=await fetch("health?t="+Date.now(),{cache:"no-store"});
      if(!r.ok)throw new Error("health unavailable");
      return await r.json();
    }catch(_e){return null;}
  }

  async function renderOwnerSummaries(){
    const panes=[...document.querySelectorAll(".tab-pane")];
    panes.forEach(p=>ensureSummarySection(p,p.dataset.pane));

    const rows=await loadHistory();
    const grouped=new Map();
    let unclassified=0;
    rows.forEach(x=>{
      const tab=classifyRecord(x);
      if(!tab){unclassified++;return;}
      if(!grouped.has(tab))grouped.set(tab,[]);
      grouped.get(tab).push(x);
    });

    panes.forEach(p=>{
      const tab=p.dataset.pane;
      const box=p.querySelector(":scope > .cc-tab-owner-summary [data-tab-performance]");
      if(box)box.innerHTML=performanceHtml(tab,computeStats(grouped.get(tab)||[]),unclassified);
    });

    const performance=await loadPerformance();
    const control=document.querySelector('.tab-pane[data-pane="control"]');
    if(control){
      let perfSection=control.querySelector(":scope > #strategy-performance-dashboard");
      if(!perfSection){
        perfSection=document.createElement("section");
        perfSection.id="strategy-performance-dashboard";
        perfSection.className="card wide";
        perfSection.innerHTML='<div class="pane-intro"><span>PERFORMANCE</span><h2>戦略別成績ダッシュボード</h2><p>REAL / SHADOW / BACKTESTを分離し、確定取引だけで損益・PF・平均R・最大DDを比較します。</p></div><div data-strategy-performance>集計読込中...</div>';
        const overview=control.querySelector(":scope > #owner-control-overview")?.closest("section");
        if(overview)overview.insertAdjacentElement("afterend",perfSection);else control.appendChild(perfSection);
      }
      const perfBox=perfSection.querySelector("[data-strategy-performance]");
      if(perfBox)perfBox.innerHTML=strategyDashboardHtml(performance);
    }

    const health=await loadHealth();
    const exec=health?.execution||null,runtime=health?.runtime||null;
    panes.forEach(p=>{
      const box=p.querySelector(":scope > .cc-tab-owner-summary [data-execution-control]");
      if(box)box.innerHTML=executionHtml(exec,runtime);
    });

    const overview=document.getElementById("owner-control-overview");
    if(overview){
      overview.innerHTML=
        executionHtml(exec,runtime)+
        metricCard("実績データの分類","TRACE",[
          ["総履歴",rows.length+"件"],["未分類",unclassified+"件"],["分類済み",Math.max(0,rows.length-unclassified)+"件"]
        ],"今後の仮想/Shadow取引は cockpit_tab を必須化して、どのタブの取引か追跡します。",unclassified?"block":"wait");
    }
  }

  function tradeCard(x,badge,cls){
    const code=String(x?.ticker||x?.code||"").replace(".T","");
    return '<article class="cc-card cc-card--'+cls+'">'+
      '<div class="cc-head"><div class="cc-identity"><span class="cc-company">'+esc(x?.name||code||"取引")+'</span>'+
      '<span class="cc-symbol">'+esc(code||"—")+'</span></div><span class="cc-badge">'+esc(badge)+'</span></div>'+
      '<div class="cc-metrics-grid">'+
      '<span>損益<b>'+money(x?.pnl_yen)+'</b></span><span>R<b>'+rfmt(x?.r)+'</b></span>'+
      '<span>ENTRY<b>'+esc(x?.entry??x?.simulated_fill??"—")+'</b></span><span>結果<b>'+esc(x?.result||"—")+'</b></span>'+
      '</div><div class="cc-foot">'+esc((x?.date||"")+" / "+(x?.strategy_id||"strategy未タグ"))+'</div></article>';
  }

  async function upgradeWeeklyReview(){
    const root=document.getElementById("weekly-review");
    if(!root)return;
    try{
      const r=await fetch("weekly_review.json?t="+Date.now(),{cache:"no-store"});
      if(!r.ok)throw new Error("weekly unavailable");
      const w=await r.json();
      const best=(Array.isArray(w.best)?w.best:[]).map(x=>tradeCard(x,"BEST",Number(x?.pnl_yen)>=0?"long":"short")).join("");
      const worst=(Array.isArray(w.worst)?w.worst:[]).map(x=>tradeCard(x,"REVIEW",Number(x?.pnl_yen)<0?"short":"wait")).join("");
      const themes=(Array.isArray(w.themes)?w.themes:[]).map(x=>'<span>'+esc(x)+'</span>').join("");
      const rules=(Array.isArray(w.next_rules)?w.next_rules:[]).map((x,i)=>'<span>'+(i+1)+'. '+esc(x)+'</span>').join("");
      root.className="card wide";
      root.innerHTML=
        '<div class="pane-intro"><span>AI COCKPIT</span><h2>週間振り返り・来週戦略</h2><p>'+esc(w.week||"—")+' / '+esc(w.created_at||"—")+'</p></div>'+
        '<div class="cc-grid">'+
          metricCard("週間成績",esc(w.decision||"REVIEW"),[
            ["仮想取引",(w.count??0)+"件"],["勝率",pct(w.win_rate)],["PF",Number.isFinite(Number(w.pf))?Number(w.pf).toFixed(2):"—"],
            ["平均R",rfmt(w.avg_r)],["週間損益",money(w.pnl)]
          ],"仮想検証/Shadowの集計で、実口座損益ではありません。",Number(w.pnl)>=0?"long":"short")+
          metricCard("来週の注目テーマ","THEME",[["候補",themes||"更新待ち"]],"テーマ文字列は分析候補であり、保有建玉ではありません。","wait")+
          metricCard("来週のルール","RULES",[["運用",rules||"更新待ち"]],"翌週の検証ルール。","wait")+
        '</div>'+
        '<h3>良かった取引</h3><div class="cc-grid">'+(best||metricCard("確定取引なし","—",[["結果","—"]],"","wait"))+'</div>'+
        '<h3>改善する取引</h3><div class="cc-grid">'+(worst||metricCard("確定取引なし","—",[["結果","—"]],"","wait"))+'</div>';
    }catch(_e){
      root.classList.add("card","wide");
    }
  }

  document.addEventListener("DOMContentLoaded",()=>{
    ensurePerformanceStyles();
    const control=document.querySelector('.tab-pane[data-pane="control"]');
    if(control&&!document.getElementById("owner-control-overview")){
      const section=document.createElement("section");
      section.className="card wide";
      section.innerHTML='<div class="pane-intro"><span>OWNER CONTROL</span><h2>取引・建玉・成績</h2><p>実発注、実建玉、Shadow建玉、各タブ成績をここで一括確認します。</p></div><div id="owner-control-overview" class="cc-grid"><div>状態読込中...</div></div>';
      control.appendChild(section);
    }
    renderOwnerSummaries();
    upgradeWeeklyReview();
    setInterval(renderOwnerSummaries,15000);
  });
})();