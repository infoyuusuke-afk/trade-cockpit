(()=>{
  "use strict";

  const lastLevel=new Map();
  const lastSpokenAt=new Map();
  const pulseUntil=new Map();
  const LEVEL_RANK={BLOCK:0,WAIT:1,WATCH:2,HOT:3};

  const n=v=>v==null||v===""||!Number.isFinite(Number(v))?null:Number(v);
  const pct=v=>n(v)==null?"—":(n(v)>=0?"+":"")+n(v).toFixed(2)+"%";
  const yen=v=>n(v)==null?"—":n(v).toLocaleString("ja-JP",{maximumFractionDigits:1});

  function bars1m(x){
    return Array.isArray(x?.bars_1m)?x.bars_1m.filter(b=>n(b?.c??b?.Close)!=null).slice(-15):[];
  }

  function closeSeries(x){
    return bars1m(x).map(b=>n(b?.c??b?.Close)).filter(v=>v!=null);
  }

  function opportunity(x,stale){
    const price=n(x?.price),vwap=n(x?.vwap),volume=n(x?.volume_burst),flow=n(x?.flow_bias);
    const or5h=n(x?.or5_high),or5l=n(x?.or5_low),or15h=n(x?.or_high),or15l=n(x?.or_low);
    const closes=closeSeries(x);
    const momentum3=closes.length>=4?((closes.at(-1)/closes.at(-4))-1)*100:null;
    const valid=!stale&&price!=null&&price>0;
    if(!valid){
      return {level:"BLOCK",score:0,direction:"block",reasons:["鮮度確認不可"],momentum3,bars:bars1m(x)};
    }

    let score=0;
    const reasons=[];
    if(volume!=null){
      if(volume>=2.5){score+=35;reasons.push("出来高 "+volume.toFixed(2)+"倍");}
      else if(volume>=1.8){score+=28;reasons.push("出来高 "+volume.toFixed(2)+"倍");}
      else if(volume>=1.4){score+=18;reasons.push("出来高 "+volume.toFixed(2)+"倍");}
      else if(volume>=1.2){score+=10;reasons.push("出来高 "+volume.toFixed(2)+"倍");}
    }
    if(flow!=null){
      const af=Math.abs(flow);
      if(af>=30){score+=20;reasons.push("歩み値 "+pct(flow));}
      else if(af>=15){score+=14;reasons.push("歩み値 "+pct(flow));}
      else if(af>=7){score+=8;reasons.push("歩み値 "+pct(flow));}
    }

    let upBreak=false,downBreak=false;
    if(or15h!=null&&or15h>0&&price>or15h){score+=20;upBreak=true;reasons.push("OR15上抜け");}
    else if(or15l!=null&&or15l>0&&price<or15l){score+=20;downBreak=true;reasons.push("OR15下抜け");}
    if(or5h!=null&&or5h>0&&price>or5h){score+=12;upBreak=true;reasons.push("OR5上抜け");}
    else if(or5l!=null&&or5l>0&&price<or5l){score+=12;downBreak=true;reasons.push("OR5下抜け");}

    if(momentum3!=null){
      const am=Math.abs(momentum3);
      if(am>=0.6){score+=15;reasons.push("3分 "+pct(momentum3));}
      else if(am>=0.3){score+=10;reasons.push("3分 "+pct(momentum3));}
    }

    let upVotes=0,downVotes=0;
    if(vwap!=null&&vwap>0){if(price>vwap)upVotes++;else if(price<vwap)downVotes++;}
    if(flow!=null){if(flow>=7)upVotes++;else if(flow<=-7)downVotes++;}
    if(momentum3!=null){if(momentum3>0.15)upVotes++;else if(momentum3<-0.15)downVotes++;}
    if(upBreak)upVotes+=2;
    if(downBreak)downVotes+=2;

    const direction=upVotes>downVotes?"long":downVotes>upVotes?"short":"wait";
    if(vwap!=null&&vwap>0&&direction!=="wait"){
      const aligned=(direction==="long"&&price>vwap)||(direction==="short"&&price<vwap);
      if(aligned){score+=7;reasons.push(direction==="long"?"VWAP上":"VWAP下");}
    }

    const activation=(volume!=null&&volume>=1.4)||(upBreak||downBreak);
    const level=score>=55&&activation&&reasons.length>=2?"HOT":score>=32&&reasons.length>=2?"WATCH":"WAIT";
    return {level,score,direction,reasons:[...new Set(reasons)].slice(0,4),momentum3,bars:bars1m(x)};
  }

  function speechText(x,o){
    const rel=n(x?.vwap)>0&&n(x?.price)!=null?(n(x.price)>=n(x.vwap)?"VWAPの上":"VWAPの下"):"VWAP位置未確認";
    const why=o.reasons.slice(0,3).join("、");
    return (x?.name||String(x?.ticker||"").replace(".T",""))+"、"+o.level+"。"+
      (why||"監視条件上昇")+"。現在値"+yen(x?.price)+"円、"+rel+"。";
  }

  function maybeAnnounce(x,o){
    const symbol=String(x?.ticker||"").replace(".T","");
    if(!symbol||!(o.level==="WATCH"||o.level==="HOT"))return;
    const prev=lastLevel.get(symbol)||"WAIT";
    const promoted=LEVEL_RANK[o.level]>LEVEL_RANK[prev];
    lastLevel.set(symbol,o.level);
    if(!promoted)return;

    pulseUntil.set(symbol,Date.now()+3200);
    window.recordOnAir?.({
      symbol,company:x.name,direction:o.direction,directionLabel:o.level,price:x.price,
      metrics:[
        {label:"出来高",value:n(x.volume_burst)==null?null:n(x.volume_burst).toFixed(2)+"倍"},
        {label:"歩み値",value:n(x.flow_bias)==null?null:pct(x.flow_bias)},
        {label:"3分",value:o.momentum3==null?null:pct(o.momentum3)}
      ],
      foot:o.reasons.join(" / ")
    });
    const box=document.getElementById("cockpit-onair-cards");
    if(box&&window.renderOnAirPanel)box.innerHTML=window.renderOnAirPanel();

    const now=Date.now(),last=lastSpokenAt.get(symbol)||0;
    if(now-last>=60000){
      lastSpokenAt.set(symbol,now);
      window.cockpitSpeak?.(speechText(x,o),o.level==="HOT"?"HOT":"WATCH");
    }
  }

  function radarCard(x,o,stale){
    const symbol=String(x?.ticker||"").replace(".T","");
    const fail=stale?"鮮度確認不可":false;
    return window.renderCockpitCard({
      symbol,company:x.name,direction:fail?"block":o.direction,directionLabel:fail?"BLOCK":o.level,
      price:x.price,changePct:x.change_pct,freshness:stale?"stale":"fresh",
      freshnessLabel:stale?"データ停止":"100銘柄 Opportunity Radar",
      failClosed:fail,
      opportunityState:fail?null:o.level,
      attentionPulse:!fail&&(pulseUntil.get(symbol)||0)>Date.now(),
      sparkline:o.bars,sparklineLabel:"直近15分・1分足終値",
      metrics:[
        {label:"OPP SCORE",value:String(Math.round(o.score))},
        {label:"出来高",value:n(x.volume_burst)==null?null:n(x.volume_burst).toFixed(2)+"倍"},
        {label:"歩み値",value:n(x.flow_bias)==null?null:pct(x.flow_bias)},
        {label:"3分",value:o.momentum3==null?null:pct(o.momentum3)},
        {label:"VWAP",value:n(x.vwap)==null?null:yen(x.vwap)},
        {label:"OR5",value:n(x.or5_low)>0&&n(x.or5_high)>0?yen(x.or5_low)+"–"+yen(x.or5_high):null}
      ],
      catalyst:o.reasons.length?o.reasons.join(" / "):"監視条件待ち",
      foot:"実発注ではありません。鮮度切れはHOT禁止。"
    });
  }

  function ensureRadar(){
    const pane=document.querySelector('.tab-pane[data-pane="scalp"]');
    if(!pane)return null;
    let section=document.getElementById("opportunity-radar");
    if(section)return section;
    section=document.createElement("section");
    section.id="opportunity-radar";
    section.className="card wide cc-opportunity-radar";
    section.innerHTML=
      '<div class="cc-opportunity-radar-head"><div><h2>Opportunity Radar・実況TOP5</h2>'+
      '<p>100銘柄を5秒ごとに監視。出来高急増・歩み値・OR5/OR15・VWAP・直近3分を実データだけで評価。</p></div>'+
      '<div id="opportunity-radar-state" class="cc-opportunity-radar-state">データ待ち</div></div>'+
      '<div id="opportunity-radar-cards" class="cc-grid"><div class="focus-empty">MS2 RSS接続待ち</div></div>';
    const first=pane.firstElementChild;
    if(first)first.insertAdjacentElement("afterend",section); else pane.prepend(section);
    return section;
  }

  function updateFixedCardAttention(rows,scored){
    const bySymbol=new Map(scored.map(z=>[String(z.x.ticker||"").replace(".T",""),z.o]));
    rows.forEach(x=>{
      const symbol=String(x?.ticker||"").replace(".T","");
      const el=document.querySelector('#scalp-fixed-5 .cc-card[data-symbol="'+CSS.escape(symbol)+'"]');
      if(!el)return;
      el.classList.remove("cc-opportunity--watch","cc-opportunity--hot","cc-opportunity--pulse");
      const o=bySymbol.get(symbol);
      if(!o)return;
      if(o.level==="WATCH")el.classList.add("cc-opportunity--watch");
      if(o.level==="HOT")el.classList.add("cc-opportunity--hot");
      if((pulseUntil.get(symbol)||0)>Date.now())el.classList.add("cc-opportunity--pulse");
    });
  }

  document.addEventListener("DOMContentLoaded",ensureRadar);

  document.addEventListener("ms2RssUpdate",e=>{
    const d=e.detail||{};
    const all=Array.isArray(d.all_targets)?d.all_targets:[];
    const stale=d.stale!==false;
    const section=ensureRadar();
    if(!section)return;
    const state=document.getElementById("opportunity-radar-state");
    const box=document.getElementById("opportunity-radar-cards");

    if(!all.length){
      if(state){state.textContent="データ待ち";state.classList.remove("hot");}
      if(box)box.innerHTML='<div class="focus-empty">100銘柄データ待ち</div>';
      return;
    }

    const scored=all.map(x=>({x,o:opportunity(x,stale)}));
    scored.forEach(z=>maybeAnnounce(z.x,z.o));
    const candidates=scored.slice().sort((a,b)=>
      (LEVEL_RANK[b.o.level]-LEVEL_RANK[a.o.level])||(b.o.score-a.o.score)
    ).slice(0,5);

    if(box)box.innerHTML=candidates.map(z=>radarCard(z.x,z.o,stale)).join("");
    const hot=scored.filter(z=>z.o.level==="HOT").length;
    const watch=scored.filter(z=>z.o.level==="WATCH").length;
    if(state){
      state.textContent=stale?"FAIL-CLOSED":("HOT "+hot+" / WATCH "+watch+" / "+(d.updated_at||"更新中"));
      state.classList.toggle("hot",!stale&&hot>0);
    }

    const fixed=["285A.T","9984.T","8035.T","6920.T","6857.T"]
      .map(t=>all.find(x=>String(x.ticker)===t)).filter(Boolean);
    setTimeout(()=>updateFixedCardAttention(fixed,scored),0);
  });

  window.cockpitOpportunityScore=opportunity;
})();