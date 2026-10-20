/**
 * V10 FOCUS integration smoke tests using the actual inline page script with
 * a minimal DOM event simulator. No browser network, Excel, MS2 or orders.
 *
 * Purpose: verify user button clicks, persisted symbol selection, and real
 * fail-closed rendering instead of merely checking text in index.html.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import vm from "node:vm";
import { livePriceBlocked } from "../card_system.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(here, "..", "index.html"), "utf8");
const begin = html.indexOf('<section id="focus-owner-panel"');
assert.notEqual(begin, -1, "reviewed FOCUS section must exist");
const open = html.indexOf("<script>", begin);
const close = html.indexOf("</script>", open);
assert.ok(open > begin && close > open, "FOCUS script must be inline and bounded");
const focusScript = html.slice(open + "<script>".length, close);

function element(id) {
  const listeners = new Map();
  return {
    id, textContent:"", innerHTML:"", value:"", options:[],
    addEventListener(event, cb) {
      if (!listeners.has(event)) listeners.set(event, []);
      listeners.get(event).push(cb);
    },
    replaceChildren(...elements) {
      this.options = [...elements];
      this.value = "";
    },
    append(node) { this.options.push(node); },
    click() { for (const cb of listeners.get("click") || []) cb({target:this}); },
  };
}
function mounted(persisted={}) {
  const clock={now:Date.now()};
  const TestDate=class extends Date {static now(){return clock.now;}};
  const timers=new Map(), windowEvents=new Map();
  let nextTimerId=1;
  const setInterval=(cb,ms)=>{
    assert.equal(ms,1000,"watchdog cadence must remain finite and frequent");
    const id=nextTimerId++;
    timers.set(id,cb);
    return id;
  };
  const clearInterval=id=>timers.delete(id);
  const map = new Map(Object.entries(persisted));
  const ids = ["focus-owner-select","focus-owner-status","focus-owner-cards",
    "focus-owner-add","focus-owner-remove"];
  const nodes = Object.fromEntries(ids.map(id=>[id,element(id)]));
  const listeners = new Map();
  const doc = {
    getElementById(id) { return nodes[id] || null; },
    createElement(tag) { assert.equal(tag,"option");return {value:"",textContent:""}; },
    addEventListener(event,cb) {
      if(!listeners.has(event)) listeners.set(event,[]);
      listeners.get(event).push(cb);
    },
  };
  const localStorage = {
    getItem(key) { return map.has(key) ? map.get(key) : null; },
    setItem(key,value) { map.set(key,String(value)); },
  };
  const paintCalls = {current:[],blocked:[]};
  const window = {
    addEventListener(name,cb) {
      if(!windowEvents.has(name))windowEvents.set(name,[]);
      windowEvents.get(name).push(cb);
    },
    livePriceBlocked,
    renderCockpitCard(model) {
      assert.equal(model.price,null, "BLOCK cards must never leak an old price");
      assert.ok(model.failClosed);
      paintCalls.blocked.push(model);
      return "[BLOCK:"+model.symbol+"]";
    },
    renderScalpCard(model,decision,interval) {
      assert.ok(model.price>0);
      assert.equal(decision.cls,"wait");
      assert.equal(interval,"1m");
      paintCalls.current.push(model);
      return "[PRICE:"+model.ticker+":"+model.price+"]";
    },
  };
  const context=vm.createContext({window, document:doc, localStorage,
    Date:TestDate,Number,String,Map,Set,Array,JSON,RegExp,console,
    setInterval,clearInterval});
  vm.runInContext(focusScript,context,{timeout:3000});
  function fire(type, detail={}) {
    const callbacks=(type==="pagehide"||type==="pageshow")?windowEvents.get(type):listeners.get(type);
    for (const cb of callbacks||[]) cb(type==="ms2RssUpdate"?{detail}:{});
  }
  function advanceClock(ms,runTimers=true){
    clock.now+=ms;
    if(runTimers)for(const callback of timers.values())callback();
  }
  fire("DOMContentLoaded");
  return {nodes,map,paintCalls,fire,advanceClock,timers,clock};
  
}
function jst(ms) {
  return new Date(ms+9*3600000).toISOString().slice(0,19)+"+09:00";
}
function row(ticker="464A.T",ageSeconds=8,now=Date.now()) {
  const quote=jst(now-ageSeconds*1000);
  const observed=jst(now-(ageSeconds-1)*1000);
  return {ticker,name:"Monitor",price:1234,
    source_timestamp_basis:"COLLECTOR_OBSERVED_CHANGE",
    source_timestamp_at:quote,source_timestamp_observed_at:observed,
    source_timestamp:quote.slice(11,19)};
}
function snapshot(rows=[],overrides={},now=Date.now()) {
  return {stale:false,live_values_available:true,data_conflict:false,
    real_submit_allowed:false,source:"MarketSpeed II RSS / local PC",
    source_mode:"MS2_RSS_WORKBOOK",price_source_status:"OK",
    connection_source:"自宅PC・MS2 RSS LIVE",
    live_price_diagnostics:{
      price_source_status:"OK",source_mode:"MS2_RSS_WORKBOOK",
      workbook_identity_verified:true,data_conflict:false,
      live_values_available:true,real_submit_allowed:false
    },
    observed_at_offset:new Date(now-1500).toISOString(),
    all_targets:rows,...overrides};
}

test("FOCUS action buttons cannot impersonate upper navigation tabs",()=>{
  const buttonMarkup=html.match(/<button[^>]*id="focus-owner-(?:add|remove)"[^>]*>/g)||[];
  assert.equal(buttonMarkup.length,2);
  for(const tag of buttonMarkup) {
    assert.ok(/class="focus-owner-action"/.test(tag),tag);
    assert.ok(!/class="[^"]*\bcockpit-tab\b/.test(tag),tag);
    assert.ok(!/\bdata-tab=/.test(tag),tag);
  }
  assert.ok(html.includes('querySelectorAll(".cockpit-tabs .cockpit-tab[data-tab]")'));
  assert.ok(!html.includes('document.querySelectorAll(".cockpit-tab")'));
});

test("FOCUS selection stays pinned, stale event clears price without clearing selection",()=>{
  const h=mounted();
  h.fire("ms2RssUpdate",snapshot([row()],{stale:true}));
  h.nodes["focus-owner-select"].value="464A.T";
  h.nodes["focus-owner-add"].click();
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),["464A.T"]);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.equal(h.paintCalls.current.length,0);

  h.fire("ms2RssUpdate",snapshot([row()]));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));
  assert.ok(h.paintCalls.current.length>0);
  const priceCount=h.paintCalls.current.length;

  h.fire("ms2RssUpdate",snapshot([row()],{data_conflict:true}));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.equal(h.paintCalls.current.length,priceCount);
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),["464A.T"]);

  h.fire("ms2RssUpdate",{stale:true});
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
});

test("FOCUS blocks undated/aged/future/unknown quote and transport payloads",()=>{
  const h=mounted({cockpitFocusPinnedV10:JSON.stringify(["464A.T"])});
  const cases=[
    snapshot([row("464A.T",125)]),
    snapshot([row("464A.T",-30)]),
    snapshot([{...row(),source_timestamp_at:null}]),
    snapshot([{...row(),source_timestamp_basis:"UNOBSERVED_SINCE_START"}]),
    snapshot([{...row(),price:0}]),
    snapshot([row()],{source:"Public delayed snapshot"}),
    snapshot([row()],{live_values_available:false}),
    snapshot([row()],{real_submit_allowed:true}),
    snapshot([row()],{observed_at_offset:"2026-10-20 09:00:00"}),
  ];
  for(const d of cases) {
    h.fire("ms2RssUpdate",d);
    assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  }
  assert.equal(h.paintCalls.current.length,0);
});

test("FOCUS fixes exactly five tickers, ignores unsolicited candidates, allows explicit removal",()=>{
  const h=mounted();
  const tickers=["1000.T","1001.T","1002.T","1003.T","1004.T","1005.T"];
  h.fire("ms2RssUpdate",snapshot(tickers.map(t=>row(t))));
  for(const ticker of tickers) {
    h.nodes["focus-owner-select"].value=ticker;
    h.nodes["focus-owner-add"].click();
  }
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),tickers.slice(0,5));
  assert.ok(h.nodes["focus-owner-status"].textContent.includes("最大5銘柄"));
  h.fire("ms2RssUpdate",snapshot([...tickers,"8888.T"].map(t=>row(t))));
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),tickers.slice(0,5));

  h.nodes["focus-owner-select"].value="1002.T";
  h.nodes["focus-owner-remove"].click();
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),["1000.T","1001.T","1003.T","1004.T"]);
  h.nodes["focus-owner-select"].value="1005.T";
  h.nodes["focus-owner-add"].click();
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),["1000.T","1001.T","1003.T","1004.T","1005.T"]);
});

test("FOCUS safely discards invalid stored selections without rendering prices",()=>{
  const h=mounted({cockpitFocusPinnedV10:'["464A.T","bad",null,42,"464A.T"]'});
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")||'["464A.T"]'),["464A.T","bad",null,42,"464A.T"]);
  h.fire("ms2RssUpdate",snapshot([]));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.equal(h.paintCalls.current.length,0);
});


test("NO-EVENT clock advance revokes a previously fresh FOCUS price without a new MS2 event",()=>{
  const h=mounted({cockpitFocusPinnedV10:JSON.stringify(["464A.T"])});
  h.fire("ms2RssUpdate",snapshot([row()]));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));
  h.advanceClock(11999);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));
  h.advanceClock(2);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.ok(h.nodes["focus-owner-status"].textContent.includes("MS2通信が停止"));
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),["464A.T"]);
  h.fire("ms2RssUpdate",snapshot([row("464A.T",8,h.clock.now)],{},h.clock.now));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));
  h.fire("pagehide");
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.equal(h.timers.size,0);
  h.fire("pageshow");
  assert.equal(h.timers.size,1,"watchdog must re-arm after bfcache pageshow");
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  h.fire("ms2RssUpdate",snapshot([row("464A.T",8,h.clock.now)],{},h.clock.now));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));
  h.advanceClock(12001);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
});

test("throttled watchdog cannot re-render an old price after silent clock advance",()=>{
  const h=mounted();
  h.fire("ms2RssUpdate",snapshot([row("464A.T"),row("1000.T")]));
  h.nodes["focus-owner-select"].value="464A.T";
  h.nodes["focus-owner-add"].click();
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));
  h.advanceClock(18000,false); // background timer did not run
  h.nodes["focus-owner-select"].value="1000.T";
  h.nodes["focus-owner-add"].click(); // forces paint: must independently detect expired event
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:1000]"));
  assert.deepEqual(JSON.parse(h.map.get("cockpitFocusPinnedV10")),["464A.T","1000.T"]);
  assert.equal(h.paintCalls.current.length,1); // the original, never a stale repaint
});

test("Collector does not emit source_authenticated: absent flag needs explicit independent identity proof",()=>{
  const h=mounted({cockpitFocusPinnedV10:JSON.stringify(["464A.T"])});
  const trusted=snapshot([row()]);
  assert.equal(Object.hasOwn(trusted,"source_authenticated"),false);
  h.fire("ms2RssUpdate",trusted);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[PRICE:464A.T:1234]"));

  const missing=JSON.parse(JSON.stringify(trusted));
  delete missing.live_price_diagnostics.workbook_identity_verified;
  h.fire("ms2RssUpdate",missing);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  h.fire("ms2RssUpdate",snapshot([row()],{source_authenticated:false}));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  h.fire("ms2RssUpdate",snapshot([row()],{live_price_diagnostics:{price_source_status:"OK"}}));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  h.fire("ms2RssUpdate",snapshot([row()],{connection_source:"公開スナップショット"}));
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.equal(h.paintCalls.current.length,1);
});

test("FOCUS watchdog starts before market data and never inserts synthetic quotes",()=>{
  const h=mounted({cockpitFocusPinnedV10:JSON.stringify(["464A.T"])});
  assert.equal(h.timers.size,1);
  h.advanceClock(60000);
  assert.ok(h.nodes["focus-owner-cards"].innerHTML.includes("[BLOCK:464A]"));
  assert.equal(h.paintCalls.current.length,0);
});
