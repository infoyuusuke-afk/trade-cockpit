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
  // Missing/blank/boolean values are not zero. A measured numeric 0 remains 0.
  const knownNumber=v=>{
    if(typeof v!=="number"&&typeof v!=="string")return null;
    if(typeof v==="string"&&(!v.trim()||!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(v.trim())))return null;
    const n=Number(v);
    return Number.isFinite(n)?n:null;
  };
  const money=v=>{const n=knownNumber(v);return n===null?"—":(n>=0?"+":"")+n.toLocaleString("ja-JP")+"円";};
  const pct=v=>{const n=knownNumber(v);return n===null?"—":n.toFixed(1)+"%";};
  const rfmt=v=>{const n=knownNumber(v);return n===null?"—":(n>=0?"+":"")+n.toFixed(2)+"R";};

  function metricCard(title,badge,metrics,foot,cls="wait"){
    return '<article class="cc-card cc-card--'+cls+'">'+
      '<div class="cc-head"><div class="cc-identity"><span class="cc-company">'+esc(title)+'</span>'+
      '<span class="cc-symbol">AI COCKPIT</span></div><span class="cc-badge">'+esc(badge)+'</span></div>'+
      '<div class="cc-metrics-grid">'+metrics.filter(x=>x&&x[1]!=null).map(x=>'<span>'+esc(x[0])+'<b>'+esc(x[1])+'</b></span>').join("")+'</div>'+
      (foot?'<div class="cc-foot">'+esc(foot)+'</div>':"")+
      '</article>';
  }

  function computeStats(rows){
    const done=rows.filter(x=>knownNumber(x?.pnl_yen)!==null);
    if(!done.length)return null;
    const wins=done.filter(x=>Number(x.pnl_yen)>0).length;
    const gains=done.reduce((a,x)=>a+Math.max(0,Number(x.pnl_yen)||0),0);
    const losses=Math.abs(done.reduce((a,x)=>a+Math.min(0,Number(x.pnl_yen)||0),0));
    const rRows=done.filter(x=>knownNumber(x?.r)!==null);
    return {
      count:done.length,
      wins,
      winRate:wins/done.length*100,
      pnl:done.reduce((a,x)=>a+(Number(x.pnl_yen)||0),0),
      pf:losses>0?gains/losses:null,
      avgR:rRows.length?rRows.reduce((a,x)=>a+Number(x.r),0)/rRows.length:null,
      openMark:done.filter(x=>String(x?.exit_reason||"")==="OPEN_MARK"||String(x?.result||"").includes("未決済")).length
    };
  }

  function performanceHtml(tab,stats,unclassified,mode){
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
    return metricCard(label+" 成績",mode==="backtest"?"BACKTEST":"SHADOW/PAPER",[
      ["取引件数",stats.count+"件"],["勝率",pct(stats.winRate)],["PF",stats.pf==null?"—":stats.pf.toFixed(2)],
      ["平均R",rfmt(stats.avgR)],["仮想損益",money(stats.pnl)],["未決済評価","—"]
    ],"mode・cockpit_tab・取引ID・available_at・確定時刻を検証した仮想履歴のみ。保留 "+unclassified+"件は混ぜません。",cls);
  }


  // CONTROL research display: only explicitly tagged, settled simulated records
  // are eligible. The public paper history can NEVER authenticate real fills.
  // No source row is rewritten; legacy/ambiguous rows remain quarantined.
  const CONTROL_MODES=["shadow","backtest"];
  const CONTROL_STRATEGIES=["scalp","event-hot","ms2-live","overnight","swing","value","kioxia-calendar"];
  const JST_OFFSET_MS=9*60*60*1000;

  function evidenceTime(value){
    if(typeof value!=="string"||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value))return null;
    const t=Date.parse(value);
    return Number.isFinite(t)?t:null;
  }

  function performanceEligibility(x,nowMs){
    if(!x||typeof x!=="object"||Array.isArray(x))return null;
    if(!TRADE_TABS.has(x.cockpit_tab))return null;
    // "paper" is a display synonym of shadow; "real" is never accepted from a paper file.
    const mode=x.mode==="paper"?"shadow":x.mode;
    if(!CONTROL_MODES.includes(mode))return null;
    if(typeof x.trade_id!=="string"||!/^[A-Za-z0-9_.:-]{1,128}$/.test(x.trade_id))return null;
    const available=evidenceTime(x.available_at),closed=evidenceTime(x.closed_at);
    if(available===null||closed===null||closed>available||available>nowMs)return null;
    if(x.status!=null&&x.status!=="CLOSED")return null;
    if(x.exit_reason==="OPEN_MARK"||String(x.result||"").includes("未決済"))return null;
    const pnl=knownNumber(x.pnl_yen);
    if(pnl===null)return null;
    return {row:x,mode,tab:x.cockpit_tab,id:x.trade_id,pnl,available,closed};
  }

  function reconcilePerformanceRows(raw,nowMs=Date.now()){
    if(!Array.isArray(raw))return {available:false,total:null,quarantined:null,eligible:[]};
    const candidates=raw.map(x=>performanceEligibility(x,nowMs));
    const ids=new Map();
    for(const item of raw){
      if(item&&typeof item.trade_id==="string")
        ids.set(item.trade_id,(ids.get(item.trade_id)||0)+1);
    }
    const eligible=candidates.filter(x=>x&&ids.get(x.id)===1);
    eligible.sort((a,b)=>a.closed-b.closed||a.available-b.available||a.id.localeCompare(b.id));
    return {available:true,total:raw.length,quarantined:raw.length-eligible.length,eligible};
  }

  function jstDay(t){
    return new Date(t+JST_OFFSET_MS).toISOString().slice(0,10);
  }
  function jstWeek(t){
    const date=new Date(t+JST_OFFSET_MS);
    date.setUTCDate(date.getUTCDate()-((date.getUTCDay()+6)%7));
    return date.toISOString().slice(0,10);
  }

  function strategyStats(records){
    if(!records.length)return null;
    const sorted=[...records].sort((a,b)=>a.closed-b.closed||a.available-b.available||a.id.localeCompare(b.id));
    let pnl=0,positive=0,negative=0,wins=0,maxDrawdown=0,peak=0;
    let cumulativeR=0,peakR=0,drawdownR=0,allR=true,streak=0;
    const rValues=[],mfe=[],mae=[],daily=new Map(),weekly=new Map(),series=[];
    for(const item of sorted){
      const v=item.pnl;
      pnl+=v;
      if(!Number.isFinite(pnl))return null;
      if(v>0){wins++;positive+=v;streak=streak>=0?streak+1:1;}
      else if(v<0){negative-=v;streak=streak<=0?streak-1:-1;}
      else streak=0;
      if(!Number.isFinite(positive)||!Number.isFinite(negative))return null;
      peak=Math.max(peak,pnl);
      maxDrawdown=Math.max(maxDrawdown,peak-pnl);
      const r=knownNumber(item.row.r);
      if(r===null)allR=false;
      else{
        rValues.push(r);cumulativeR+=r;
        peakR=Math.max(peakR,cumulativeR);
        drawdownR=Math.max(drawdownR,peakR-cumulativeR);
      }
      const mfeR=knownNumber(item.row.mfe_r),maeR=knownNumber(item.row.mae_r);
      if(mfeR!==null)mfe.push(mfeR);
      if(maeR!==null)mae.push(maeR);
      const d=jstDay(item.closed),w=jstWeek(item.closed);
      daily.set(d,(daily.get(d)||0)+v);
      weekly.set(w,(weekly.get(w)||0)+v);
      series.push({date:d,pnl_yen:pnl});
    }
    const recent=sorted.slice(-20);
    return {
      count:sorted.length,wins,winRate:wins/sorted.length*100,pnl,
      pf:negative>0?positive/negative:null,
      avgR:rValues.length?rValues.reduce((a,b)=>a+b,0)/rValues.length:null,
      rN:rValues.length,maxDrawdown,maxDrawdownR:allR?drawdownR:null,
      mfeAvg:mfe.length===sorted.length?mfe.reduce((a,b)=>a+b,0)/mfe.length:null,
      maeAvg:mae.length===sorted.length?mae.reduce((a,b)=>a+b,0)/mae.length:null,
      streak,recentN:recent.length,recentPnl:recent.reduce((a,x)=>a+x.pnl,0),
      daily:[...daily].map(([date,pnl_yen])=>({date,pnl_yen})),
      weekly:[...weekly].map(([week,pnl_yen])=>({week,pnl_yen})),
      cumulative:series
    };
  }

  function strategyGroups(accepted){
    const groups=new Map();
    for(const x of accepted){
      const key=x.mode+":"+x.tab;
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(x);
    }
    return groups;
  }

  function controlPerformanceHtml(audit){
    const total=audit.available?audit.total+"件":"—";
    const accepted=audit.available?audit.eligible.length+"件":"—";
    const held=audit.available?audit.quarantined+"件":"—";
    const info=metricCard("CONTROL 履歴照合","PROVENANCE",[
      ["元履歴",total],["表示可能",accepted],["保留（未分類・重複等）",held]
    ],"trade_id / cockpit_tab / mode / closed_at / available_at / 確定PnLをすべて検証。旧履歴は自動推定しません。","wait");
    const real=metricCard("REAL｜実取引","未接続",[
      ["確定損益","—"],["勝率","—"],["取引件数","—"]
    ],"紙上の取引履歴は実約定の証拠ではありません。認証済みブローカー実績がないため表示できません。","block");
    if(!audit.available){
      return info+real+metricCard("SHADOW/PAPER｜仮想","履歴取得不能",[["戦略別成績","—"]],"取得失敗を0件と扱いません。","block")+
        metricCard("BACKTEST｜検証","履歴取得不能",[["戦略別成績","—"]],"将来時刻・欠測を取り込みません。","block");
    }
    const groups=strategyGroups(audit.eligible);
    let cards=info+real;
    for(const mode of CONTROL_MODES){
      let any=false;
      for(const tab of CONTROL_STRATEGIES){
        const list=groups.get(mode+":"+tab)||[];
        if(!list.length)continue;
        const st=strategyStats(list);
        if(!st)continue;
        any=true;
        const label=mode==="shadow"?"SHADOW/PAPER":"BACKTEST";
        const trend=(items,key)=>items.slice(-3).map(x=>x[key]+":"+money(x.pnl_yen)).join(" / ")||"—";
        const cls=st.pnl>0?"long":st.pnl<0?"short":"wait";
        cards+=metricCard(label+"｜"+TAB_LABELS[tab],st.count>=20?"記録N="+st.count:"N不足",[
          ["取引件数",st.count+"件"],["仮想累計損益",money(st.pnl)],
          ["勝率",pct(st.winRate)],["PF",st.pf===null?"—":st.pf.toFixed(2)],
          ["平均R",rfmt(st.avgR)],["最大DD",money(-st.maxDrawdown)],
          ["最大DD(R)",rfmt(st.maxDrawdownR===null?null:-st.maxDrawdownR)],
          ["MFE / MAE",st.mfeAvg===null||st.maeAvg===null?"—":rfmt(st.mfeAvg)+" / "+rfmt(st.maeAvg)],
          ["直近20件",st.recentN+"件 "+money(st.recentPnl)],
          ["日次（直近3）",trend(st.daily,"date")],
          ["週次（直近3）",trend(st.weekly,"week")]
        ],"紙上の確定履歴のみ。R "+st.rN+"/"+st.count+"件。費用控除・実現損益は未認証。",cls);
      }
      if(!any){
        cards+=metricCard((mode==="shadow"?"SHADOW/PAPER":"BACKTEST")+"｜戦略別","未接続",[
          ["取引件数","—"],["期待値","—"],["最大DD","—"]
        ],"必要なモード・画面タグ・時刻・取引ID付きの履歴がありません。0件と断定しません。","block");
      }
      const candidates=CONTROL_STRATEGIES.map(tab=>({tab,stats:strategyStats(groups.get(mode+":"+tab)||[])}))
        .filter(x=>x.stats&&x.stats.count>=20);
      if(candidates.length>=2){
        candidates.sort((a,b)=>(b.stats.pnl/b.stats.count)-(a.stats.pnl/a.stats.count));
        const strongest=candidates[0],weakest=candidates[candidates.length-1];
        cards+=metricCard((mode==="shadow"?"SHADOW/PAPER":"BACKTEST")+"｜相対強弱","N≥20",[[
          "平均PnL上位",TAB_LABELS[strongest.tab]+" "+money(strongest.stats.pnl/strongest.stats.count)],
          ["平均PnL下位",TAB_LABELS[weakest.tab]+" "+money(weakest.stats.pnl/weakest.stats.count)]
        ],"同一モード内のみ比較。費用/スリッページ・選択バイアスは未検証であり、実発注判断に使用禁止。","wait");
      }else{
        cards+=metricCard((mode==="shadow"?"SHADOW/PAPER":"BACKTEST")+"｜相対強弱","N不足",[
          ["順位","未算定"],["比較可能な戦略",candidates.length+"種類"]
        ],"1戦略N≥20、同一モードの2戦略以上が揃うまで優劣を表示しません。","wait");
      }
    }
    return cards;
  }

  function executionHtml(exec,runtime){
    const known=!!exec;
    const realAllowed=exec?.real_submit_allowed===true;
    const brokerConnected=exec?.broker_positions_connected===true;
    const brokerN=knownNumber(exec?.broker_position_count);
    const brokerCount=!brokerConnected?"未接続":
      (brokerN!==null&&Number.isInteger(brokerN)&&brokerN>=0?brokerN+"件":"未確認");
    const shadowConnected=exec?.shadow_positions_connected===true;
    const shadowN=knownNumber(exec?.shadow_open_position_count);
    const shadowCount=!shadowConnected?"未接続":
      (shadowN!==null&&Number.isInteger(shadowN)&&shadowN>=0?shadowN+"件":"未確認");
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

  function shadowEngineHtml(exec){
    const allowed=["RUNNING","PAUSED_FAIL_CLOSED","RECOVERING","STOPPED"];
    const raw=typeof exec?.shadow_engine_state==="string"?exec.shadow_engine_state:"";
    const shown=allowed.includes(raw)?raw:"PAUSED_FAIL_CLOSED";
    const ops=exec?.shadow_ops?.daily||null;
    const incident=exec?.shadow_latest_incident||null;
    const num=value=>{const n=knownNumber(value);return n===null?"—":String(n);};
    const uptimeRatio=knownNumber(ops?.shadow_uptime_ratio);
    const uptime=uptimeRatio!==null&&uptimeRatio>=0&&uptimeRatio<=1?(Math.round(uptimeRatio*1000)/10)+"%":"—";
    const foot=incident
      ? String(incident.occurrence_at||"—")+" "+String(incident.error_code||"障害")+" → "+String(incident.shadow_impact||"—")+" / 無効化 "+num(incident.invalidated_signal_count)+" / 復旧 "+String(incident.recovery_mode||"未復旧")
      : "画面を閉じていてもコントローラ配下のAI SHADOWは継続します。状態ファイルが無い、古い、読めないときはRUNNINGにしません。";
    return metricCard("AI SHADOW",shown,[
      ["エンジン",shown],
      ["理由",exec?.shadow_engine_reason||(exec?"":"状態取得不能")],
      ["仮想建玉",knownNumber(exec?.shadow_open_observation_count)!==null&&Number.isInteger(knownNumber(exec?.shadow_open_observation_count))&&knownNumber(exec?.shadow_open_observation_count)>=0?String(exec.shadow_open_observation_count)+"件":"—"],
      ["日次エラー",num(ops?.error_count)],
      ["停止時間",knownNumber(ops?.total_downtime_seconds)!==null&&knownNumber(ops?.total_downtime_seconds)>=0?String(ops.total_downtime_seconds)+"秒":"—"],
      ["稼働率",uptime],
      ["鮮度異常",num(ops?.freshness_anomaly_count)],
      ["価格不一致",num(ops?.price_mismatch_count)],
      ["自動復旧",num(ops?.auto_recovery_count)],
      ["手動対応",num(ops?.manual_response_count)]
    ],foot,shown==="RUNNING"?"long":"block");
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
      return Array.isArray(rows)?rows:null;
    }catch(_e){return null;}
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

    const loadedRows=await loadHistory();
    const historyAvailable=Array.isArray(loadedRows);
    const rows=historyAvailable?loadedRows:[];
    const audit=reconcilePerformanceRows(loadedRows,Date.now());
    const grouped=strategyGroups(audit.eligible);
    const unclassified=audit.available?audit.quarantined:0;

    panes.forEach(p=>{
      const tab=p.dataset.pane;
      const box=p.querySelector(":scope > .cc-tab-owner-summary [data-tab-performance]");
      if(!box)return;
      const shadow=grouped.get("shadow:"+tab)||[];
      const backtest=grouped.get("backtest:"+tab)||[];
      if(shadow.length&&backtest.length){
        box.innerHTML=metricCard((TAB_LABELS[tab]||tab)+" 成績","モード別表示",[
          ["集計","CONTROLを参照"],["混合損益","—"]
        ],"Shadow/PaperとBacktestを合算しません。","wait");
      }else{
        const selected=shadow.length?shadow:backtest;
        box.innerHTML=performanceHtml(tab,computeStats(selected.map(x=>x.row)),unclassified,
          shadow.length?"shadow":backtest.length?"backtest":null);
      }
    });

    const strategy=document.getElementById("owner-strategy-performance");
    if(strategy)strategy.innerHTML=controlPerformanceHtml(audit);

    const health=await loadHealth();
    const exec=health?.execution||null,runtime=health?.runtime||null;
    panes.forEach(p=>{
      const box=p.querySelector(":scope > .cc-tab-owner-summary [data-execution-control]");
      if(box)box.innerHTML=executionHtml(exec,runtime)+shadowEngineHtml(exec);
    });

    const overview=document.getElementById("owner-control-overview");
    if(overview){
      overview.innerHTML=
        executionHtml(exec,runtime)+
        shadowEngineHtml(exec)+
        metricCard("実績データの分類","TRACE",[
          ["総履歴",historyAvailable?rows.length+"件":"—"],
          ["未分類",historyAvailable?unclassified+"件":"—"],
          ["分類済み",historyAvailable?Math.max(0,rows.length-unclassified)+"件":"—"]
        ],historyAvailable?"今後の仮想/Shadow取引は cockpit_tab を必須化して、どのタブの取引か追跡します。":"取引履歴が取得できません。件数や成績を0とは扱いません。",!historyAvailable||unclassified?"block":"wait");
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
      const best=(Array.isArray(w.best)?w.best:[]).map(x=>tradeCard(x,"BEST",knownNumber(x?.pnl_yen)===null?"wait":knownNumber(x.pnl_yen)>=0?"long":"short")).join("");
      const worst=(Array.isArray(w.worst)?w.worst:[]).map(x=>tradeCard(x,"REVIEW",knownNumber(x?.pnl_yen)!==null&&knownNumber(x.pnl_yen)<0?"short":"wait")).join("");
      const themes=(Array.isArray(w.themes)?w.themes:[]).map(x=>'<span>'+esc(x)+'</span>').join("");
      const rules=(Array.isArray(w.next_rules)?w.next_rules:[]).map((x,i)=>'<span>'+(i+1)+'. '+esc(x)+'</span>').join("");
      root.className="card wide";
      root.innerHTML=
        '<div class="pane-intro"><span>AI COCKPIT</span><h2>週間振り返り・来週戦略</h2><p>'+esc(w.week||"—")+' / '+esc(w.created_at||"—")+'</p></div>'+
        '<div class="cc-grid">'+
          metricCard("週間成績",esc(w.decision||"REVIEW"),[
            ["仮想取引",knownNumber(w.count)!==null&&Number.isInteger(knownNumber(w.count))&&knownNumber(w.count)>=0?String(w.count)+"件":"—"],
            ["勝率",pct(w.win_rate)],["PF",knownNumber(w.pf)!==null?knownNumber(w.pf).toFixed(2):"—"],
            ["平均R",rfmt(w.avg_r)],["週間損益",money(w.pnl)]
          ],"仮想検証/Shadowの集計で、実口座損益ではありません。",knownNumber(w.pnl)===null?"wait":knownNumber(w.pnl)>=0?"long":"short")+
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
    if(control&&!document.getElementById("owner-strategy-performance")){
      const section=document.createElement("section");
      section.className="card wide cc-strategy-owner-panel";
      section.innerHTML='<div class="pane-intro"><span>OWNER CONTROL</span><h2>戦略別パフォーマンス（実績区分・証拠付き）</h2><p>REAL／SHADOW・PAPER／BACKTESTを混同しません。証拠不足は未接続と表示します。</p></div><div id="owner-strategy-performance" class="cc-grid"><div>戦略実績を照合中...</div></div>';
      control.appendChild(section);
    }
    renderOwnerSummaries();
    upgradeWeeklyReview();
    setInterval(renderOwnerSummaries,15000);
  });
})();