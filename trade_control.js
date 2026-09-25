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

  function computeStats(rows){
    const done=rows.filter(x=>Number.isFinite(Number(x?.pnl_yen)));
    if(!done.length)return null;
    const wins=done.filter(x=>Number(x.pnl_yen)>0).length;
    const gains=done.reduce((a,x)=>a+Math.max(0,Number(x.pnl_yen)||0),0);
    const losses=Math.abs(done.reduce((a,x)=>a+Math.min(0,Number(x.pnl_yen)||0),0));
    const rRows=done.filter(x=>Number.isFinite(Number(x?.r)));
    return {
      count:done.length,
      wins,
      winRate:wins/done.length*100,
      pnl:done.reduce((a,x)=>a+(Number(x.pnl_yen)||0),0),
      pf:losses>0?gains/losses:(gains>0?99:null),
      avgR:rRows.length?rRows.reduce((a,x)=>a+Number(x.r),0)/rRows.length:null,
      openMark:done.filter(x=>String(x?.exit_reason||"")==="OPEN_MARK"||String(x?.result||"").includes("未決済")).length
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
    return metricCard(label+" 成績","仮想/Shadow",[
      ["取引件数",stats.count+"件"],["勝率",pct(stats.winRate)],["PF",stats.pf==null?"—":stats.pf.toFixed(2)],
      ["平均R",rfmt(stats.avgR)],["損益",money(stats.pnl)],["未決済評価",stats.openMark+"件"]
    ],"paper_trade_history.json のタブ識別可能な履歴のみ。未分類履歴 "+unclassified+"件は混ぜません。",cls);
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
      if(box)box.outerHTML=performanceHtml(tab,computeStats(grouped.get(tab)||[]),unclassified);
    });

    const health=await loadHealth();
    const exec=health?.execution||null,runtime=health?.runtime||null;
    panes.forEach(p=>{
      const box=p.querySelector(":scope > .cc-tab-owner-summary [data-execution-control]");
      if(box)box.outerHTML=executionHtml(exec,runtime);
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