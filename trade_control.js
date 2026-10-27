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

  // OWNER 2026-10-27 「戦略別パフォーマンスをつないで」: the brain's virtual (Shadow) results per rule, from
  // /rule_shadow.json (recorded signals replayed on recorded MS2 ticks, forward from its forward_from date), next to
  // each rule's past-data check (前半＝train / 後半＝test). Display only; a failed read shows 未接続, never 0.
  async function loadRuleShadow(){
    try{
      const r=await fetch("/rule_shadow.json?t="+Date.now(),{cache:"no-store"});
      if(!r.ok)return null;
      const v=await r.json();
      return v&&v.schema_version==="100b-v10-rule-shadow-v1"&&v.real_submit_allowed===false?v:null;
    }catch(_e){return null;}
  }
  function brainRuleHtml(rs){
    if(!rs||!rs.forward)return metricCard("SHADOW｜ブレインのルール別","未接続",[["取引件数","—"],["期待値","—"]],"ブレインの仮想売買の記録（rule_shadow）を読めません。0件と断定しません。","block");
    const days=Array.isArray(rs.days)?rs.days:[];
    const label=k=>k==="BRAIN"?(rs.brain?.label||"ブレインの選択"):(rs.rules?.[k]?.label||rs.gap_rules?.[k]?.label||k);
    const sgn=v=>v===null||v===undefined||!Number.isFinite(Number(v))?"—":(Number(v)>0?"+":"")+Number(v).toFixed(3)+"%";
    const exitsText=e=>e?["TARGET","STOP","TIME_EXIT"].filter(k=>e[k]).map(k=>({TARGET:"利確",STOP:"損切",TIME_EXIT:"時間"}[k])+e[k]).join("・")||"—":"—";
    const order=["BRAIN","R1","R2","R4","R5"].concat(Object.keys(rs.forward).filter(k=>!["BRAIN","R1","R2","R4","R5"].includes(k)).sort());
    let html=metricCard("SHADOW｜ブレインのルール別（仮想）","つながりました",[
      ["記録の期間",(rs.forward_from||"—")+"〜"+(days.slice(-1)[0]||"—")],["日数",days.length+"日"],
      ["ルールの数",Object.keys(rs.forward).length+"個"],["更新",String(rs.generated_at||"—").slice(0,16).replace("T"," ")+" UTC"]
    ],"記録したサインを、記録した実際の値動きで仮想売買した結果（費用込みの期待値）。お金は動いていません。最大DDはこの記録に無いため出しません。","wait");
    const ranked=[];
    for(const k of order){
      const f=rs.forward[k];if(!f)continue;
      const bt=rs.rules?.[k]?.backtest||null,n=Number(f.n)||0,ev=Number(f.ev_pct),pf=Number(f.pf);
      if(n>=20&&Number.isFinite(ev))ranked.push({k,ev});
      html+=metricCard("SHADOW｜"+label(k),n>=20?"記録N="+n:"N不足（"+n+"回）",[
        ["取引件数",n+"回"],["1回の期待値",sgn(f.ev_pct)],["勝率",f.win_rate_pct==null?"—":f.win_rate_pct+"%"],
        ["PF",Number.isFinite(pf)?pf.toFixed(2):"—"],["決済の内訳",exitsText(f.exits)],
        ["過去データ 前半",bt?.train?sgn(bt.train.ev_pct)+"・PF"+bt.train.pf+"（"+bt.train.n+"回）":"—"],
        ["過去データ 後半",bt?.test?sgn(bt.test.ev_pct)+"・PF"+bt.test.pf+"（"+bt.test.n+"回）":"—"]
      ],(rs.rules?.[k]?.record_only?"記録のみ（ブレイン・音声・注文カードに使わない）。":"")+"仮想売買・検証中。実発注の判断には使いません。",
      n<20?"wait":ev>0&&pf>=1?"long":"short");
    }
    if(ranked.length>=2){
      ranked.sort((a,b)=>b.ev-a.ev);
      html+=metricCard("SHADOW｜ルールの相対強弱","N≥20",[
        ["期待値 上位",label(ranked[0].k)+" "+sgn(ranked[0].ev)],["期待値 下位",label(ranked[ranked.length-1].k)+" "+sgn(ranked[ranked.length-1].ev)],
        ["比べたルール",ranked.length+"個"]
      ],"20回以上の記録があるルールだけを比べます。費用込み・仮想。日数が少ないので順位は変わります。","wait");
    }
    return html;
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
    if(strategy)strategy.innerHTML=controlPerformanceHtml(audit)+brainRuleHtml(await loadRuleShadow());

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

  // OWNER 2026-10-23 夜 「コントロールに保有株をカード表示追加、場中、売買したら保有中」「両方 ただし分けて表示」
  // 「保有中、保有した銘柄はAIトレード日記のタブ」: separate panels in the AIトレード日記 tab, for what is held now
  // and what was held and closed today. 実口座: the OWNER's real holdings read by the Collector with the read-only RSS
  // position lists (this PC only). 仮想: the cockpit's simulated holdings (rule signals, overnight).
  // Display only; nothing here can place an order.
  function holdingCard(name,code,badge,metrics,foot,cls,pl){
    return '<article class="cc-card cc-card--'+cls+'">'+
      '<div class="cc-head"><div class="cc-identity"><span class="cc-company">'+esc(name||code||"—")+'</span>'+
      '<span class="cc-symbol">'+esc(code||"")+'</span></div><span class="cc-badge">'+esc(badge)+'</span></div>'+
      (pl||"")+
      '<div class="cc-metrics-grid">'+metrics.filter(x=>x&&x[1]!=null).map(x=>'<span>'+esc(x[0])+'<b>'+esc(x[1])+'</b></span>').join("")+'</div>'+
      (foot?'<div class="cc-foot">'+esc(foot)+'</div>':"")+'</article>';
  }
  const yen=v=>{const n=knownNumber(v);return n===null?"—":n.toLocaleString("ja-JP")+"円";};
  // OWNER 2026-10-27 「保有銘柄が現在含み損か含み益か一目で分かるようにして」: the live price the screen trusts
  // (window.cockpitLivePrices, fresh rows only, at most 30 s old) against the virtual entry / reference price.
  // OWNER 2026-10-27: a short is 1 - now / entry, the same formula as the scoring (not entry / now - 1).
  // No live price -> 「現在値なし」, never an old number. Display only.
  function unrealized(code,entry,isShort){
    const lp=window.cockpitLivePrices,now=lp&&Date.now()-lp.at<=30000?Number(lp.rows?.[code]):NaN,e=knownNumber(entry);
    if(!Number.isFinite(now)||now<=0||e===null||e<=0)return {cls:"pl-none",text:"含み損益：現在値なし",now:null};
    const pct=(isShort?1-now/e:now/e-1)*100,sign=pct>0?"+":"";
    return {cls:pct>0?"pl-plus":pct<0?"pl-minus":"pl-flat",text:(pct>0?"含み益 ":pct<0?"含み損 ":"±0 ")+sign+pct.toFixed(2)+"%",now};
  }
  function plLine(u){return '<div class="cc-pl '+u.cls+'"><b>'+esc(u.text)+'</b>'+(u.now!==null?'<small>現在値 '+esc(u.now.toLocaleString("ja-JP"))+'円</small>':"")+'</div>';}
  const shares=v=>{const n=knownNumber(v);return n===null?"—":n.toLocaleString("ja-JP")+"株";};
  const signedPct=v=>{const n=knownNumber(v);return n===null?"—":(n>=0?"+":"")+n.toFixed(2)+"%";};
  const openDay=v=>{const s=String(v||"");if(!/^\d{8}$/.test(s))return s||"—";const jst=new Date(Date.now()+9*3600e3).toISOString().slice(0,10).replace(/-/g,"");return s===jst?"本日":s.slice(4,6)+"/"+s.slice(6,8);};
  async function renderHoldings(){
    const realRoot=document.getElementById("owner-real-holdings");
    if(realRoot){
      try{
        const r=await fetch("/real_positions.json?t="+Date.now(),{cache:"no-store"});
        if(!r.ok)throw new Error("unavailable");
        const d=await r.json();
        const execs=Array.isArray(d.executions_today)?d.executions_today:[];
        const openedAt=x=>{const e=execs.filter(e=>e.code===x.code&&e.trade==="信用新規"&&e.side===x.side).map(e=>String(e.at||"").slice(11,19)).sort();return e.length?e[0]:null;};
        const margin=(Array.isArray(d.margin)?d.margin:[]).map(x=>holdingCard(x.name,x.code,"保有中・"+(x.side||"信用"),[
          ["売買",x.side||"—"],["株数",shares(x.qty)],["建値",yen(x.price)],["時価",yen(x.last)],
          ["含み損益",money(x.pnl)],["損益率",signedPct(x.pnl_pct)],["建てた時刻",openedAt(x)?"本日 "+openedAt(x):openDay(x.open_date)],["区分",(x.kind||"")+(x.term?"・"+x.term:"")]
        ],"信用建玉（"+(x.account||"")+"・"+(x.market||"")+"）",String(x.side||"").includes("売")?"short":"long"));
        const cash=(Array.isArray(d.cash)?d.cash:[]).map(x=>holdingCard(x.name,x.code,"保有中・現物",[
          ["株数",shares(x.qty)],["平均取得",yen(x.price)],["時価",yen(x.last)],
          ["含み損益",money(x.pnl)],["損益率",signedPct(x.pnl_pct)]
        ],"現物（"+(x.account||"")+"）","long"));
        const state=d.margin_state==="OK"&&d.cash_state==="OK"?"":"（一部取得待ち）";
        const doneRoot=document.getElementById("owner-real-closed");
        if(doneRoot){
          // today's executions per issue: opening and closing sides, average prices and an estimate without costs
          const byCode={};
          execs.forEach(e=>{(byCode[e.code]=byCode[e.code]||{name:e.name,code:e.code,open:[],close:[]})[/埋|売付/.test(String(e.side))?"close":"open"].push(e);});
          const avg=a=>{const q=a.reduce((s,e)=>s+(knownNumber(e.qty)||0),0);return q?{q,p:a.reduce((s,e)=>s+(knownNumber(e.qty)||0)*(knownNumber(e.price)||0),0)/q}:null;};
          const heldNow=new Set([...(d.margin||[]),...(d.cash||[])].map(x=>x.code));
          const cards=Object.values(byCode).filter(g=>g.close.length).map(g=>{
            const o=avg(g.open),c=avg(g.close),short=g.close.some(e=>e.side==="買埋");
            const est=o&&c?Math.round((c.p-o.p)*Math.min(o.q,c.q)*(short?-1:1)):null;
            const times=[...g.open,...g.close].map(e=>String(e.at||"").slice(11,19)).sort();
            return holdingCard(g.name,g.code,heldNow.has(g.code)?"一部保有中":"決済済み",[
              ["売買",short?"空売り→買い戻し":"買い→売り"],["株数",shares(c?c.q:null)],["建値（平均）",o?yen(Math.round(o.p*10)/10):"—（前日以前）"],
              ["決済（平均）",c?yen(Math.round(c.p*10)/10):"—"],["損益（概算）",est===null?"—":money(est)],["時刻",times.length?times[0]+"〜"+times[times.length-1]:"—"]
            ],"本日の約定から（手数料・金利は含まない概算）",est!==null&&est<0?"short":"long");
          });
          doneRoot.innerHTML=cards.join("")||'<div class="focus-empty">今日決済した銘柄はありません</div>';
        }
        realRoot.innerHTML=(margin.join("")+cash.join(""))||'<div class="focus-empty">保有中の銘柄はありません'+esc(state)+'（'+esc(String(d.updated_at||"").slice(11,19))+' 時点）</div>';
      }catch(_e){
        realRoot.innerHTML='<div class="focus-empty">実口座の保有を読めません（V10停止中・MS2未接続・または設定OFF）。古い保有は表示しません。</div>';
        const doneRoot=document.getElementById("owner-real-closed");
        if(doneRoot)doneRoot.innerHTML='<div class="focus-empty">実口座の約定を読めません。</div>';
      }
    }
    const virtRoot=document.getElementById("owner-virtual-holdings");
    if(virtRoot){
      try{
        const r=await fetch("/brain_pick.json?t="+Date.now(),{cache:"no-store"});
        if(!r.ok)throw new Error("unavailable");
        const pos=(await r.json())?.positions||{};
        const rules=(Array.isArray(pos.rule_positions)?pos.rule_positions:[]).filter(p=>p&&p.status==="OPEN").map(p=>holdingCard(p.name,String(p.ticker||"").replace(/\.T$/,""),"保有中（仮想）",[
          ["サイン",p.signal||"—"],["ルール",p.rule||"—"],["約定（仮想）",yen(p.fill_price)],["約定時刻",p.fill_time||"—"],
          ["利確",yen(p.target)],["損切り",yen(p.stop)]
        ],"ルールのサインの仮想売買（検証中・注文なし）",String(p.signal||"").includes("空売り")?"short":"long",
          plLine(unrealized(String(p.ticker||"").replace(/\.T$/,""),p.fill_price,String(p.signal||"").includes("空売り")))));
        const overnight=(Array.isArray(pos.overnight)?pos.overnight:[]).map(p=>holdingCard(p.name,String(p.ticker||"").replace(/\.T$/,""),"持ち越し（仮想）",[
          ["売買",p.side==="LONG"?"買い":"空売り"],["基準",yen(p.reference_price)],["決定",String(p.decided_at||"").slice(5,16)],
          ["採点",String(p.valid_until||"").replace("next trading day","翌営業日")]
        ],"オーバーナイトの仮想売買（検証中・注文なし）",p.side==="LONG"?"long":"short",
          plLine(unrealized(String(p.ticker||"").replace(/\.T$/,""),p.reference_price,p.side!=="LONG"))));
        virtRoot.innerHTML=(rules.join("")+overnight.join(""))||'<div class="focus-empty">仮想の保有はありません</div>';
        const vDone=document.getElementById("owner-virtual-closed");
        if(vDone){
          const exitName={TARGET:"利確",STOP:"損切り",TIME_EXIT:"時間で手じまい",CLOSE_EXIT:"引けで手じまい"};
          const closed=(Array.isArray(pos.rule_positions)?pos.rule_positions:[]).filter(p=>p&&p.status==="CLOSED"&&p.fill_price!=null).map(p=>holdingCard(p.name,String(p.ticker||"").replace(/\.T$/,""),"決済済み（仮想）",[
            ["サイン",p.signal||"—"],["ルール",p.rule||"—"],["約定（仮想）",yen(p.fill_price)],["約定時刻",p.fill_time||"—"],
            ["決済",exitName[p.exit]||p.exit||"—"],["決済値",yen(p.exit_price)],["損益率",signedPct(p.return_pct)]
          ],"ルールのサインの仮想売買（検証中・注文なし）",knownNumber(p.return_pct)!==null&&Number(p.return_pct)<0?"short":"long"));
          vDone.innerHTML=closed.join("")||'<div class="focus-empty">今日決済した仮想の売買はありません</div>';
        }
      }catch(_e){
        virtRoot.innerHTML='<div class="focus-empty">仮想の保有を読めません（ブレインの記録が新しくありません）</div>';
      }
    }
  }

  // OWNER 2026-10-27 「AIコクピットの成績が一目で分かるように改修…全体成績、保有銘柄の損益（含み損・益）
  // 各投資手法別　各アナリスト別　コントロールタブで成績はわかりやすく数字、グラフも良いかも」:
  // one panel at the top of CONTROL. Real account = the same read-only MS2 lists as the 実口座 cards (estimates,
  // no costs); cockpit = the brain's virtual trades (today from brain_pick, per rule from rule_shadow); analysts =
  // analyst_scores.json (GPT) and Grok 3号's answer checks. Bars are plain CSS. Display only, no orders.
  let glanceRuleShadow=null,glanceRuleShadowAt=0;
  const gNum=v=>{const n=knownNumber(v);return n===null?null:n;};
  const gCls=v=>v===null?"g-none":v>0?"g-plus":v<0?"g-minus":"g-flat";
  const gYen=v=>v===null?"—":(v>0?"+":"")+Math.round(v).toLocaleString("ja-JP")+"円";
  const gPct=(v,d=2)=>v===null||!Number.isFinite(v)?"—":(v>0?"+":"")+v.toFixed(d)+"%";
  const gBar=(v,max)=>{if(v===null||!Number.isFinite(v)||!max)return '<i class="g-bar"></i>';const w=Math.max(2,Math.min(100,Math.abs(v)/max*100));return '<i class="g-bar"><b class="'+(v>=0?"g-up":"g-dn")+'" style="width:'+w.toFixed(0)+'%"></b></i>';};
  const gTile=(title,value,cls,sub)=>'<div class="g-tile '+cls+'"><span>'+esc(title)+'</span><b>'+esc(value)+'</b><small>'+esc(sub)+'</small></div>';
  async function gJson(url){try{const r=await fetch(url+(url.includes("?")?"&":"?")+"t="+Date.now(),{cache:"no-store"});return r.ok?await r.json():null;}catch(_e){return null;}}
  function gHeld(kind,p,entry,short){
    const u=unrealized(String(p.ticker||"").replace(/\.T$/,""),entry,short);
    const e=knownNumber(entry),val=u.now===null||e===null||e<=0?null:(short?1-u.now/e:u.now/e-1)*100;
    return {kind,name:p.name,code:String(p.ticker||"").replace(/\.T$/,""),side:short?"空売り":"買い",val,text:u.text.replace("含み損益：","")};
  }
  async function renderGlance(){
    const root=document.getElementById("owner-performance-glance");
    if(!root)return;
    if(!glanceRuleShadow||Date.now()-glanceRuleShadowAt>300000){glanceRuleShadow=await loadRuleShadow();glanceRuleShadowAt=Date.now();}
    const [bp,acct,an,gb]=await Promise.all([gJson("/brain_pick.json"),gJson("/real_positions.json"),gJson("analyst_scores.json"),gJson("grok_bots.json")]);
    const rs=glanceRuleShadow,pos=bp?.positions||{},rp=Array.isArray(pos.rule_positions)?pos.rule_positions:[],on=Array.isArray(pos.overnight)?pos.overnight:[];
    // real account (estimates from the read-only lists, no costs; the same arithmetic as the 実口座 cards)
    let realDone=0,realWin=0,realLose=0,realN=0,realOpen=null,realUncalc=0;const realHeld=[],realSide={long:{yen:0,n:0},short:{yen:0,n:0}};
    if(acct){
      // OWNER 2026-10-27 「買い→売埋と空売り→買埋を分けて計算して、前日以前の建玉の決済は『未計算○件』と出して」:
      // long = 買建/買付 opened and 売埋/売付 closed today; short = 売建 opened and 買埋 closed today, per stock.
      // Only today's opened quantity is matched; a close beyond it (a position opened on an earlier day, whose
      // entry price is not in today's list) is counted as 未計算 and never guessed.
      const execs=Array.isArray(acct.executions_today)?acct.executions_today:[],groups={};
      const dirOf=s=>/^(買建|買付)$/.test(s)?["long","open"]:/^(売埋|売付)$/.test(s)?["long","close"]:/^売建$/.test(s)?["short","open"]:/^買埋$/.test(s)?["short","close"]:null;
      execs.forEach(e=>{const d=dirOf(String(e.side||"").trim());if(!d)return;const g=groups[e.code+"|"+d[0]]=groups[e.code+"|"+d[0]]||{dir:d[0],open:[],close:[]};g[d[1]].push(e);});
      const avg=a=>{const q=a.reduce((x,e)=>x+(knownNumber(e.qty)||0),0);return q?{q,p:a.reduce((x,e)=>x+(knownNumber(e.qty)||0)*(knownNumber(e.price)||0),0)/q}:null;};
      Object.values(groups).filter(g=>g.close.length).forEach(g=>{const o=avg(g.open),c=avg(g.close);
        if(!c)return;
        if(!o||c.q>o.q)realUncalc++;                      // part or all of the close is an earlier day's position
        if(o){const q=Math.min(o.q,c.q),est=(c.p-o.p)*q*(g.dir==="short"?-1:1);
          realDone+=est;realN++;realSide[g.dir].yen+=est;realSide[g.dir].n++;if(est>0)realWin++;else if(est<0)realLose++;}});
      [...(Array.isArray(acct.margin)?acct.margin:[]),...(Array.isArray(acct.cash)?acct.cash:[])].forEach(x=>{const v=gNum(x.pnl);if(v!==null)realOpen=(realOpen||0)+v;
        realHeld.push({kind:"実口座",name:x.name,code:x.code,side:x.side||"現物",val:gNum(x.pnl_pct),text:gYen(v)+"（"+gPct(gNum(x.pnl_pct))+"）"});});
    }
    // cockpit virtual: today closed and open (open uses the screen's fresh live price)
    const closed=rp.filter(p=>p&&p.status==="CLOSED"&&gNum(p.return_pct)!==null);
    const vSum=closed.reduce((a,p)=>a+Number(p.return_pct),0),vWin=closed.filter(p=>Number(p.return_pct)>0).length;
    const vHeld=rp.filter(p=>p&&p.status==="OPEN").map(p=>gHeld("仮想",p,p.fill_price,String(p.signal||"").includes("空売り")))
      .concat(on.map(p=>gHeld("仮想・持越",p,p.reference_price,p.side!=="LONG")));
    const vVals=vHeld.map(x=>x.val).filter(v=>v!==null),vAvg=vVals.length?vVals.reduce((a,b)=>a+b,0)/vVals.length:null;
    let html='<div class="g-tiles">'+
      gTile("実口座 今日の確定損益（概算）",acct?gYen(realDone):"読めません",acct?gCls(realDone):"g-none",acct?"買い→売埋 "+gYen(realSide.long.yen)+"（"+realSide.long.n+"件）／空売り→買埋 "+gYen(realSide.short.yen)+"（"+realSide.short.n+"件）・勝ち"+realWin+"／負け"+realLose+(realUncalc?"・未計算"+realUncalc+"件（前日以前の建玉の決済）":"")+"（手数料なしの概算）":"V10停止中・MS2未接続・設定OFF")+
      gTile("実口座 含み損益",acct?gYen(realOpen):"読めません",acct?gCls(realOpen):"g-none",acct?"保有"+realHeld.length+"銘柄":"—")+
      gTile("コクピット仮想 今日の決済",closed.length?gPct(vSum):"まだなし",closed.length?gCls(vSum):"g-none",closed.length?closed.length+"回・勝率"+Math.round(vWin/closed.length*100)+"%（1回ごとの％の合計）":"今日の仮想決済はまだありません")+
      gTile("コクピット仮想 含み損益（平均）",vAvg===null?"—":gPct(vAvg),gCls(vAvg),"保有"+vHeld.length+"件"+(vHeld.length&&vAvg===null?"・現在値なし":""))+
      '</div>';
    // holdings P/L list
    const holds=realHeld.concat(vHeld).sort((a,b)=>(b.val??-1e9)-(a.val??-1e9)),hMax=Math.max(1,...holds.map(x=>Math.abs(x.val||0)));
    html+='<h3 class="g-h">保有銘柄の損益（含み）</h3>'+(holds.length?'<div class="g-rows">'+holds.map(x=>'<div class="g-row g-row5"><span class="g-kind">'+esc(x.kind)+'</span><span class="g-name">'+esc(String(x.name||"").replace(/（[0-9A-Z]{4}）$/,""))+'('+esc(x.code)+')・'+esc(x.side)+'</span>'+gBar(x.val,hMax)+'<b class="'+gCls(x.val)+'">'+esc(x.text)+'</b></div>').join("")+'</div>':'<p class="g-empty">保有はありません</p>');
    // per rule (virtual, forward) + today
    html+='<h3 class="g-h">手法別（ブレインの仮想売買'+(rs?"・"+esc(rs.forward_from||"")+"〜"+esc((rs.days||[]).slice(-1)[0]||""):"")+'・費用込み）</h3>';
    if(rs&&rs.forward){
      const keys=["BRAIN","R1","R2","R4","R5"].concat(Object.keys(rs.forward).filter(k=>!["BRAIN","R1","R2","R4","R5"].includes(k)).sort()).filter(k=>rs.forward[k]);
      const lab=k=>k==="BRAIN"?"ブレインの選択":String(rs.rules?.[k]?.label||rs.gap_rules?.[k]?.label||k).split("・")[0];
      const eMax=Math.max(0.1,...keys.map(k=>Math.abs(Number(rs.forward[k].ev_pct)||0)));
      html+='<div class="g-rows">'+keys.map(k=>{const f=rs.forward[k],ev=gNum(f.ev_pct),n=Number(f.n)||0,today=closed.filter(p=>p.rule===k),ts=today.reduce((a,p)=>a+Number(p.return_pct),0);
        return '<div class="g-row"><span class="g-name">'+esc(lab(k))+'</span><span class="g-n">'+n+'回・勝率'+esc(f.win_rate_pct??"—")+'%・PF'+esc(f.pf??"—")+(n<20?"・N不足":"")+'</span>'+gBar(ev,eMax)+'<b class="'+gCls(ev)+'">1回 '+gPct(ev,3)+'</b><small class="g-today">'+(today.length?"今日 "+today.length+"回 "+gPct(ts):"今日 0回")+'</small></div>';}).join("")+'</div>';
    }else html+='<p class="g-empty">手法別の記録（rule_shadow）を読めません。0件とは扱いません。</p>';
    // per analyst
    html+='<h3 class="g-h">アナリスト別（答えの向きの当たり・費用なし）</h3><div class="g-rows">';
    const arows=Array.isArray(an?.analysts)?an.analysts:[];
    html+=arows.length?arows.map(a=>'<div class="g-row"><span class="g-name">GPT '+esc(a.name)+'</span><span class="g-n">答え'+esc(a.answers)+'件（監視'+esc(a.watch)+'）・採点'+esc(a.scored)+'件</span>'+gBar(gNum(a.avg_move_pct),1)+'<b class="'+gCls(gNum(a.avg_move_pct))+'">'+(a.scored?"当たり"+esc(a.hit_rate_pct)+"%・平均"+gPct(gNum(a.avg_move_pct)):"採点待ち")+'</b><small class="g-today"></small></div>').join(""):'<p class="g-empty">GPTアナリストの採点を読めません</p>';
    const g3=(Array.isArray(gb?.bots)?gb.bots:[]).find(b=>b.bot==="Grok3号"),ck=Array.isArray(g3?.checks)?g3.checks:[];
    const hit=ck.reduce((a,c)=>a+(c.hit||0),0),miss=ck.reduce((a,c)=>a+(c.miss||0),0),unk=ck.reduce((a,c)=>a+(c.unknown||0),0);
    html+='<div class="g-row"><span class="g-name">Grok 3号（決算前の空気）</span><span class="g-n">答え合わせ'+(hit+miss+unk)+'件（判定不能'+unk+'）</span>'+gBar(hit+miss?(hit/(hit+miss)*100-50):null,50)+'<b class="'+gCls(hit+miss?hit-miss:null)+'">'+(hit+miss?"当たり"+hit+"／外れ"+miss+"（"+Math.round(hit/(hit+miss)*100)+"%）":"答え合わせ待ち")+'</b><small class="g-today"></small></div>';
    html+='</div><p class="g-note">実口座はMS2の一覧を読むだけの概算（手数料・金利なし）。仮想はお金が動いていない検証です。売買の判断には使いません。</p>';
    root.innerHTML=html;
  }

  document.addEventListener("DOMContentLoaded",()=>{
    const control=document.querySelector('.tab-pane[data-pane="control"]');
    if(control&&!document.getElementById("owner-performance-glance")){
      const section=document.createElement("section");
      section.className="card wide g-panel";
      section.innerHTML='<div class="pane-intro"><span>OWNER CONTROL</span><h2>成績（ひと目で）</h2><p>全体・保有銘柄の含み損益・手法別・アナリスト別。</p></div><div id="owner-performance-glance"><div>成績読込中...</div></div>';
      const intro=control.querySelector(":scope > .pane-intro");
      if(intro)intro.after(section);else control.prepend(section);
    }
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
    const journal=document.querySelector('.tab-pane[data-pane="ai-journal"]');
    if(journal&&!document.getElementById("owner-real-holdings")){
      const panels=[
        ["owner-real-holdings","保有中｜実口座（読むだけ）","武蔵などで売買した本当の保有です。MS2 RSSの建玉一覧・保有一覧・約定一覧を読むだけで、注文は出しません。このPCの画面だけに出します。"],
        ["owner-real-closed","保有した銘柄｜実口座・今日決済","今日の約定一覧から、決済した銘柄をまとめます。損益は手数料・金利を含まない概算です。"],
        ["owner-virtual-holdings","保有中｜仮想（コクピットの検証）","ルール①②④⑤のサインとオーバーナイトの仮想売買です。お金は動いていません。"],
        ["owner-virtual-closed","保有した銘柄｜仮想・今日決済","ルールのサインの仮想売買で、今日決済したものです。"]
      ];
      const intro=journal.querySelector(":scope > .pane-intro");
      let after=intro;
      panels.forEach(([id,title,note])=>{
        const section=document.createElement("section");
        section.className="card wide";
        section.innerHTML='<div class="pane-intro"><span>AIトレード日記</span><h2>'+esc(title)+'</h2><p>'+esc(note)+'</p></div><div id="'+id+'" class="cc-grid"><div>読込中...</div></div>';
        if(after&&after.parentNode===journal)after.after(section);else journal.prepend(section);
        after=section;
      });
    }
    renderOwnerSummaries();
    renderHoldings();
    upgradeWeeklyReview();
    setInterval(renderOwnerSummaries,15000);
    setInterval(renderHoldings,10000);
    renderGlance();
    setInterval(renderGlance,10000);
  });
})();