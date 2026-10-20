/**
 * V10 provenance panel: execute the exact inline HTML script under a
 * simulated DOM and clock. No broker, MS2, Excel, network or local files edited.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import {fileURLToPath} from "node:url";
import {livePriceBlocked} from "../card_system.js";

const root=path.dirname(fileURLToPath(import.meta.url));
const html=fs.readFileSync(path.join(root,"..","index.html"),"utf8");
const tag='/* V10 provenance: SOURCE/QUOTE proof, never an execution permission.';
const begin=html.indexOf(tag);
assert.ok(begin>0,"V10 provenance source block missing");
const end=html.indexOf("</script>",begin);
assert.ok(end>begin && end-begin<12000,"V10 provenance block not bounded");
const script=html.slice(begin,end);
const quoteSource="MarketSpeed II RSS / local PC";

function createHarness(){
  const label={dataset:{},textContent:""};
  const listeners=new Map(),windowListeners=new Map(), timers=new Map();
  let time=Date.now(),nextTimer=1;
  class TestDate extends Date { static now(){return time;} }
  const document={
    visibilityState:"visible",
    getElementById(id){return id==="v10-source-provenance"?label:null;},
    addEventListener(name,cb){
      if(!listeners.has(name))listeners.set(name,[]);
      listeners.get(name).push(cb);
    },
  };
  const window={
    livePriceBlocked,
    addEventListener(name,cb){
      if(!windowListeners.has(name))windowListeners.set(name,[]);
      windowListeners.get(name).push(cb);
    },
  };
  const setInterval=(cb,period)=>{
    assert.equal(period,1000,"watchdog must update once per second");
    const id=nextTimer++;
    timers.set(id,cb);
    return id;
  };
  const clearInterval=(id)=>timers.delete(id);
  const ctx=vm.createContext({document,window,Date:TestDate,
    Number,String,Array,JSON,RegExp,Set,Map,console,setInterval,clearInterval});
  vm.runInContext(script,ctx,{timeout:3000});
  function event(data){
    for(const cb of listeners.get("ms2RssUpdate")||[])cb({detail:data});
  }
  function advance(ms,runTimers=true) {
    time+=ms;
    if(runTimers) for(const callback of timers.values())callback();
  }
  function hide() {
    document.visibilityState="hidden";
    for(const cb of listeners.get("visibilitychange")||[])cb({});
  }
  function pagehide(){for(const cb of windowListeners.get("pagehide")||[])cb({});}
  return {label,event,advance,hide,pagehide,timers,now:()=>time};
}
function packet(h, overrides={}){
  return {source:quoteSource,source_mode:"MS2_RSS_WORKBOOK",price_source_status:"OK",
    connection_source:"自宅PC・MS2 RSS LIVE",
    real_submit_allowed:false,stale:false,live_values_available:true,
    data_conflict:false,_transport_fail_closed:false,
    observed_at_offset:new Date(h.now()-2000).toISOString(),
    live_price_diagnostics:{
      workbook_identity_verified:true,price_source_status:"OK",
      source_mode:"MS2_RSS_WORKBOOK",data_conflict:false,
      live_values_available:true,real_submit_allowed:false,
    },
    ...overrides};
}

test("past-date 2026-09-25 top and footer are explicitly marked historic",()=>{
  assert.match(html,/<span class="tag">過去の参考分析<\/span>/);
  assert.match(html,/静的分析作成：2026-09-25 10:41:50 JST（本日のLIVE市場情報ではありません）/);
  assert.match(html,/静的HTML作成：2026-09-25 10:41:50 JST／LIVE未認証/);
  assert.ok(!html.includes("寄り付き前8:00版"));
  assert.ok(!html.includes("d.source_authenticated===true"));
});

test("initial no-event panel is BLOCKED and no LIVE status is inferred",()=>{
  const h=createHarness();
  assert.equal(h.label.dataset.marketTrust,"BLOCKED");
  assert.match(h.label.textContent,/LIVE 未認証/);
  h.advance(30000);
  assert.equal(h.label.dataset.marketTrust,"BLOCKED");
});

test("Collector independent workbook identity admits observation-only, not trade",()=>{
  const h=createHarness();
  const p=packet(h);
  assert.equal(Object.hasOwn(p,"source_authenticated"),false);
  h.event(p);
  assert.equal(h.label.dataset.marketTrust,"OBSERVATION_ONLY");
  assert.match(h.label.textContent,/参照専用・実注文禁止/);
  assert.doesNotMatch(h.label.textContent,/買い|ロング推奨|SHORT推奨/);
});

test("missing or conflicting independent proof always BLOCKS the panel",()=>{
  const h=createHarness();
  const base=packet(h);
  const bad=[
    {...base,source_authenticated:false},
    {...base,live_price_diagnostics:{price_source_status:"OK"}},
    {...base,live_price_diagnostics:{...base.live_price_diagnostics,workbook_identity_verified:null}},
    {...base,connection_source:"公開スナップショット"},
    {...base,source:"Public delayed snapshot"},
    {...base,stale:true},
    {...base,live_values_available:false},
    {...base,real_submit_allowed:true},
    {...base,data_conflict:true},
    {...base,_transport_fail_closed:true},
    {...base,live_price_diagnostics:{...base.live_price_diagnostics,source_mode:"OTHER"}},
    {...base,live_price_diagnostics:{...base.live_price_diagnostics,real_submit_allowed:true}},
    {...base,observed_at_offset:null},
    {...base,observed_at_offset:"2026-10-20 15:00:00 JST"},
    {...base,observed_at_offset:new Date(h.now()-61000).toISOString()},
    {...base,observed_at_offset:new Date(h.now()+180000).toISOString()},
  ];
  for(const p of bad){
    h.event(p);
    assert.equal(h.label.dataset.marketTrust,"BLOCKED",JSON.stringify(p).slice(0,140));
  }
  assert.match(h.label.textContent,/証拠不足/);
});

test("no additional MS2 event: watchdog clears previously accepted banner after 12 seconds",()=>{
  const h=createHarness();
  h.event(packet(h));
  assert.equal(h.label.dataset.marketTrust,"OBSERVATION_ONLY");
  h.advance(11999);
  assert.equal(h.label.dataset.marketTrust,"OBSERVATION_ONLY");
  h.advance(2);
  assert.equal(h.label.dataset.marketTrust,"BLOCKED");
  assert.match(h.label.textContent,/通信停止・12秒超の無受信/);
  h.event(packet(h));
  assert.equal(h.label.dataset.marketTrust,"OBSERVATION_ONLY");
});

test("page becomes hidden or closed: revoke and remove watchdog timer",()=>{
  const h=createHarness();
  h.event(packet(h));
  h.hide();
  assert.equal(h.label.dataset.marketTrust,"BLOCKED");
  h.event(packet(h));
  assert.equal(h.label.dataset.marketTrust,"OBSERVATION_ONLY");
  h.pagehide();
  assert.equal(h.label.dataset.marketTrust,"BLOCKED");
  assert.equal(h.timers.size,0);
});

test("a missing timer tick cannot retroactively authorize a missing event",()=>{
  const h=createHarness();
  h.event(packet(h));
  h.advance(60000,false);
  // Browser throttling may delay timer, but the first later tick must revoke.
  assert.equal(h.label.dataset.marketTrust,"OBSERVATION_ONLY");
  h.advance(1);
  assert.equal(h.label.dataset.marketTrust,"BLOCKED");
});
