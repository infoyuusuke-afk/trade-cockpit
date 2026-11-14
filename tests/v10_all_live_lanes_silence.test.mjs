/**
 * Real V10 UI script cross-panel fail-closed regression.
 * Executes source-extracted existing inline event handlers in a synthetic DOM.
 * Clock advances without any MS2 message. No network, broker, Excel or IPC.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {livePriceBlocked} from "../card_system.js";

const root=path.dirname(fileURLToPath(import.meta.url));
const html=fs.readFileSync(path.join(root,"..","index.html"),"utf8");
const radar=fs.readFileSync(path.join(root,"..","opportunity_radar.js"),"utf8");

function inside(startText,endText,source=html) {
  const begin=source.indexOf(startText);
  assert.notEqual(begin,-1,"cannot find source block "+startText);
  const end=source.indexOf(endText,begin+startText.length);
  assert.notEqual(end,-1,"cannot find end of source block "+startText);
  return source.slice(begin,end+endText.length);
}
function oneLine(needle) {
  const start=html.indexOf(needle);
  assert.notEqual(start,-1,needle);
  return html.slice(start,html.indexOf("\n",start));
}
const sourceCentral=inside(" // One 12-second MS2 admission/expiry contract",
                            "\n const esc=v=>").replace(/\n const esc=v=>$/,"");
const sourceScalp=inside('document.addEventListener("ms2RssUpdate",e=>{\n   const d=e.detail||{},stale=',"\n });");
const sourceUnified=oneLine('document.addEventListener("ms2RssUpdate",e=>{const d=e.detail||{},live=');
const sourceWatch=oneLine('document.addEventListener("ms2RssUpdate",e=>{const d=e.detail||{},box=document.getElementById("watchlist-100-rows")');
const sourceGap=oneLine('document.addEventListener("ms2RssUpdate",e=>{const d=e.detail||{},box=document.getElementById("premarket-gap-rows")');
const sourceKioxia=oneLine('document.addEventListener("ms2RssUpdate",e=>{const d=e.detail||{},k=d.kioxia');
const sourceKioStat=oneLine('document.addEventListener("ms2RssUpdate",e=>{const k=e.detail?.kioxia');
const sourceRadar=inside('document.addEventListener("ms2RssUpdate",e=>{',"\n  });",radar);

const REQUIRED=["ms2-live-health","ms2-live-meta","ms2-live-cards",
  "ms2-hold-cards","ms2-hold-status","ms2-hold-stats","ms2-hold-history",
  "ms2-pts-cards","ms2-ir-pts-cards","ms2-ir-pts-meta",
  "scalp-fixed-5","watchlist-100-rows","premarket-gap-rows",
  "opportunity-radar-state","opportunity-radar-cards","ms2-common-status",
  "unified-mode","unified-mode-title","unified-mode-note","unified-mode-time",
  "kio-ms2-state","kio-ms2-source","kio-preopen-stat","kio-ms2-orderflow"];

function el(id) {
  let t="",h="";
  const flags=new Set();
  const obj={id,style:{},dataset:{},className:"",children:new Map(),
    classList:{
      add(...args){args.forEach(x=>flags.add(x));},
      remove(...args){args.forEach(x=>flags.delete(x));},
      toggle(name,state){if(state)flags.add(name);else flags.delete(name);},
      contains(name){return flags.has(name);}
    },
    get textContent(){return t;},set textContent(v){t=String(v);h=t;},
    get innerHTML(){return h;},set innerHTML(v){h=String(v);t=h;},
    querySelector(selector) {
      if(!this.children.has(selector))this.children.set(selector,el(id+" "+selector));
      return this.children.get(selector);
    }
  };
  return obj;
}

function harness() {
  let clock=Date.now(),nextTimer=1;
  const timers=new Map(),events=new Map(),winEvents=new Map(),nodes=new Map();
  for(const id of REQUIRED)nodes.set(id,el(id));
  class TestDate extends Date { static now(){return clock;} }
  class TestCustomEvent {constructor(type,opts){this.type=type;this.detail=opts?.detail;}}
  const document={
    visibilityState:"visible",
    getElementById(id){if(!nodes.has(id))nodes.set(id,el(id));return nodes.get(id);},
    addEventListener(type,fn){if(!events.has(type))events.set(type,[]);events.get(type).push(fn);},
    dispatchEvent(ev){for(const fn of events.get(ev.type)||[])fn(ev);},
    querySelectorAll(selector){return [];},
  };
  const window={
    livePriceBlocked,
    renderScalpCard(x,sv){return '<scalp ticker="'+x.ticker+'" stale="'+x._stale+'" signal="'+sv.label+'">';},
    renderCockpitWatchRow(x){return '<watch symbol="'+x.symbol+'" price="'+x.price+'" freshness="'+x.freshness+'">';},
    addEventListener(type,fn){if(!winEvents.has(type))winEvents.set(type,[]);winEvents.get(type).push(fn);},
  };
  const setInterval=(fn,ms)=>{assert.equal(ms,1000);const id=nextTimer++;timers.set(id,fn);return id;};
  const clearInterval=(id)=>timers.delete(id);
  const setTimeout=(fn)=>{fn();return 1;};
  const context=vm.createContext({document,window,Date:TestDate,CustomEvent:TestCustomEvent,
    setInterval,clearInterval,setTimeout,Number,String,Array,JSON,Map,Set,console,
    signalView:()=>({label:"監視",cls:"wait"}),
    ensureRadar:()=>({}),opportunity:()=>({level:"WATCH",score:1}),
    maybeAnnounce:()=>{},radarCard:x=>'<radar symbol="'+x.ticker+'">',
    LEVEL_RANK:{WATCH:1,HOT:2},updateFixedCardAttention:()=>{},CSS:{escape:x=>x}
  });
  // The real SCALP5 listener was registered in an earlier DOMContentLoaded
  // handler than the dashboard listener: preserve that registration order.
  vm.runInContext(sourceScalp,context,{timeout:2000});
  vm.runInContext(sourceCentral,context,{timeout:2000});
  for(const src of [sourceUnified,sourceWatch,sourceGap,sourceKioxia,sourceKioStat,sourceRadar])
    vm.runInContext(src,context,{timeout:2000});
  function send(data){document.dispatchEvent(new TestCustomEvent("ms2RssUpdate",{detail:data}));}
  function advance(ms,fireTimers=true){clock+=ms;if(fireTimers){for(const cb of timers.values())cb();}}
  function pagehide(){for(const cb of winEvents.get("pagehide")||[])cb({});}
  function pageshow(){for(const cb of winEvents.get("pageshow")||[])cb({});}
  function hide(){document.visibilityState="hidden";for(const fn of events.get("visibilitychange")||[])fn({});}
  return {nodes,send,advance,pagehide,pageshow,hide,now:()=>clock,timers,window};
}
function row(now,ticker,preopen=false){
  const q=new Date(now-4000).toISOString(),obs=new Date(now-3000).toISOString();
  return {ticker,name:"synthetic test",price:1234,change_pct:1.2,
    source_timestamp_basis:"COLLECTOR_OBSERVED_CHANGE",
    source_timestamp_at:q,source_timestamp_observed_at:obs,
    source_timestamp:q.slice(11,19),
    ...(preopen?{preopen_quote:1233,preopen_gap_pct:2.3,preopen_market_imbalance:5}:{})
  };
}
function good(h){
  const rows=[row(h.now(),"464A.T"),row(h.now(),"1000.T"),row(h.now(),"1001.T",true)];
  return {source:"MarketSpeed II RSS / local PC",connection_source:"自宅PC・MS2 RSS LIVE",
    source_mode:"MS2_RSS_WORKBOOK",price_source_status:"OK",
    stale:false,live_values_available:true,data_conflict:false,real_submit_allowed:false,
    _transport_fail_closed:false,observed_at_offset:new Date(h.now()-1000).toISOString(),
    updated_at:new Date(h.now()-1000).toISOString(),all_targets:rows,top5:[rows[0]],
    kioxia:{orderflow_state:"買い優勢",preopen_historical:{ready:false,sample_days:3}},
    live_price_diagnostics:{
      workbook_identity_verified:true,source_mode:"MS2_RSS_WORKBOOK",
      price_source_status:"OK",data_conflict:false,live_values_available:true,
      real_submit_allowed:false
    }};
}
const content=(h,id)=>h.nodes.get(id).innerHTML;
function assertBlocked(h) {
  assert.match(h.nodes.get("unified-mode").className,/stale/);
  assert.match(h.nodes.get("unified-mode-title").textContent,/事前分析/);
  assert.doesNotMatch(content(h,"scalp-fixed-5"),/<scalp/);
  assert.doesNotMatch(content(h,"watchlist-100-rows"),/<watch/);
  assert.doesNotMatch(content(h,"premarket-gap-rows"),/<watch/);
  assert.doesNotMatch(content(h,"opportunity-radar-cards"),/<radar/);
  for(const id of ["ms2-live-cards","ms2-hold-cards","ms2-pts-cards","ms2-ir-pts-cards"])
    assert.doesNotMatch(content(h,id),/1234|LIVE接続中|<watch|<scalp/);
  assert.match(content(h,"ms2-live-health"),/データ停止/);
  assert.match(h.nodes.get("kio-ms2-state").textContent,/未接続/);
  assert.equal(h.nodes.get("kio-preopen-quote").textContent,"—");
}
test("real UI handlers share the same source and quote admission gate",()=>{
  const h=harness();
  h.send(good(h));
  assert.match(h.nodes.get("unified-mode").className,/live/);
  assert.match(content(h,"scalp-fixed-5"),/<scalp ticker="464A.T"/);
  assert.match(content(h,"watchlist-100-rows"),/<watch/);
  assert.match(content(h,"premarket-gap-rows"),/<watch/);
  assert.match(content(h,"opportunity-radar-cards"),/<radar/);
  assert.match(h.nodes.get("kio-ms2-state").textContent,/買い優勢/);
});
test("no next event: all LIVE-labeled lanes, cards and metrics clear after 12 sec",()=>{
  const h=harness();h.send(good(h));
  for(const id of ["ms2-live-cards","ms2-hold-cards","ms2-pts-cards","ms2-ir-pts-cards"])
    h.nodes.get(id).innerHTML="LIVE接続中 price=1234";
  h.nodes.get("ms2-live-health").textContent="LIVE 接続中";
  h.advance(11999);
  assert.match(h.nodes.get("unified-mode").className,/live/);
  h.advance(2);
  assertBlocked(h);
  assert.equal(h.timers.size,1,"central watchdog must be single shared interval");
  h.send(good(h));
  assert.match(h.nodes.get("unified-mode").className,/live/);
  h.advance(12001);
  assertBlocked(h);
});
test("malformed identity, frozen timestamp or one unverifiable row never paint LIVE",()=>{
  const h=harness();
  const valid=good(h);
  for(const d of [
    {...valid,connection_source:"公開スナップショット"},
    {...valid,source_authenticated:false},
    {...valid,live_price_diagnostics:{...valid.live_price_diagnostics,workbook_identity_verified:null}},
    {...valid,observed_at_offset:new Date(h.now()-20000).toISOString()},
    {...valid,stale:true},
    {...valid,real_submit_allowed:true},
  ]){h.send(d);assertBlocked(h);}
  const rows=good(h);rows.all_targets[1].source_timestamp_basis="UNOBSERVED_SINCE_START";
  h.send(rows);
  assert.match(h.nodes.get("unified-mode").className,/live/);
  assert.doesNotMatch(content(h,"watchlist-100-rows"),/symbol="1000"/);
});
test("pagehide/pageshow and background-tab disable every panel until new verified MS2 event",()=>{
  const h=harness();h.send(good(h));h.pagehide();assertBlocked(h);
  assert.equal(h.timers.size,0);
  h.pageshow();assertBlocked(h);assert.equal(h.timers.size,1);
  h.send(good(h));assert.match(h.nodes.get("unified-mode").className,/live/);
  h.hide();assertBlocked(h);
  h.send(good(h));h.advance(12001);assertBlocked(h);
});
test("unknown data source or an old per-row quote/provenance time never paints LIVE",()=>{
  const h=harness();
  const valid=good(h);
  for(const d of [
    {...valid,source:"unknown"},
    {...valid,source:undefined},
    {...valid,live_price_diagnostics:{...valid.live_price_diagnostics,source_mode:"PUBLIC_SNAPSHOT"}},
  ]){h.send(d);assertBlocked(h);}
  // Fresh screen event, but one row's own quote time or observation proof is
  // older than 120 s: that row must not render even though the screen is LIVE.
  for(const field of ["source_timestamp_at","source_timestamp_observed_at"]){
    const d=good(h);
    const old=new Date(h.now()-121000).toISOString();
    d.all_targets[1][field]=old;
    if(field==="source_timestamp_at")d.all_targets[1].source_timestamp=old.slice(11,19);
    h.send(d);
    assert.match(h.nodes.get("unified-mode").className,/live/);
    assert.doesNotMatch(content(h,"watchlist-100-rows"),/symbol="1000"/);
    assert.match(content(h,"watchlist-100-rows"),/<watch/);
  }
});
