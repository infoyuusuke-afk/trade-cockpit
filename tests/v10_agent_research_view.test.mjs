/**
 * BRAIN tab specialist AI view: expired, unsourced, NO_DATA and UNAVAILABLE
 * reports are shown as not usable; text is escaped; Revenue Hunter is labelled
 * as project progress. Runs the shipped helpers from index.html in a VM.
 * No network, broker, Excel or IPC.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root=path.dirname(fileURLToPath(import.meta.url));
const html=fs.readFileSync(path.join(root,"..","index.html"),"utf8").replace(/\r\n/g,"\n");
function line(needle){
  const at=html.indexOf(needle);
  assert.notEqual(at,-1,"cannot find "+needle);
  const start=html.lastIndexOf("\n",at)+1;
  return html.slice(start,html.indexOf("\n",at));
}
function between(a,b){
  const s=html.indexOf(a),e=html.indexOf(b,s);
  assert.ok(s>=0&&e>s,"cannot find block "+a);
  return html.slice(s,e);
}
const src=line(" const esc=v=>String(v??\"\")")+"\n"+line(" const kioSafeUrl=u=>")+"\n"+
  between(" const AGENT_ROLE_LABEL="," const renderAgentResearch=");
const ctx=vm.createContext({URL,String,Number,Array,Date,JSON});
vm.runInContext(src,ctx,{timeout:2000});
const NOW=Date.parse("2026-10-21T00:00:00Z");
function rep(over){
  return {report_id:"run_20261021_01.pre_next",role:"pre_next",lane:"MARKET_RESEARCH_NOT_EXECUTION",status:"WATCH",
    target_at:"2026-10-21T08:30:00+09:00",expires_at:"2026-10-21T03:00:00+00:00",usable:true,not_usable_reason:null,
    evidence:[{source_id:"boj_1",source_url:"https://www.boj.or.jp/a",available_at:"2026-10-20T10:00:00+00:00"}],
    hypothesis:"h",conditions:"c",invalidation:"i",...over};
}
const usable=(r)=>vm.runInContext("agentReportUsable("+JSON.stringify(r)+","+NOW+")",ctx);
const card=(r)=>vm.runInContext("agentReportCard("+JSON.stringify(r)+","+NOW+")",ctx);

test("unexpired sourced WATCH report is usable as research",()=>{
  assert.deepEqual({...usable(rep({}))},{ok:true,reason:null});
  assert.match(card(rep({})),/注目銘柄なし/);   // OWNER 2026-10-23: only watched issues are shown
});

test("a card shows only the issues a usable WATCH report watches",()=>{
  const out=card(rep({hypothesis:"Watch 593A, 7012 and 285A on the 2026-10-20 data",conditions:"hold 7012"}));
  assert.match(out,/<strong>593A<br>7012<br>285A<\/strong>/);
  assert.doesNotMatch(card(rep({status:"NO_SIGNAL",hypothesis:"7012"})),/7012/);
  assert.doesNotMatch(card(rep({expires_at:"2026-10-20T00:00:00Z",hypothesis:"7012"})),/7012/);   // expired: hidden
});

test("expired, unsourced, NO_DATA and UNAVAILABLE are not usable",()=>{
  assert.equal(usable(rep({expires_at:"2026-10-20T23:59:59Z"})).reason,"EXPIRED");
  assert.equal(usable(rep({expires_at:"not a time"})).reason,"EXPIRED");
  assert.equal(usable(rep({evidence:[]})).reason,"NO_SOURCE");
  assert.equal(usable(rep({usable:false,not_usable_reason:"NO_DATA",status:"NO_DATA"})).reason,"NO_DATA");
  assert.equal(usable(rep({usable:false,not_usable_reason:"UNAVAILABLE",status:"UNAVAILABLE"})).reason,"UNAVAILABLE");
  assert.match(card(rep({expires_at:"2026-10-20T00:00:00Z"})),/注目銘柄なし/);
  assert.match(card(rep({evidence:[]})),/注目銘柄なし/);
});

test("report text and links are escaped; only http(s) links",()=>{
  const bad="<img src=x onerror=alert(1)>";
  const out=card(rep({hypothesis:bad,conditions:bad,invalidation:bad,report_id:bad,
    evidence:[{source_id:bad,source_url:"javascript:alert(1)",available_at:"x"}]}));
  assert.doesNotMatch(out,/<img|javascript:|onerror/);
  // OWNER 2026-10-23: the card shows only watched issues, so no report text or link is
  // rendered at all; a name taken from the Brain's list is escaped as well.
  vm.runInContext('agentNames={"7012":"<img src=x onerror=alert(1)>"}',ctx);
  const named=card(rep({hypothesis:"watch 7012"}));
  assert.doesNotMatch(named,/<img/);
  assert.match(named,/&lt;img src=x onerror=alert\(1\)&gt;\(7012\)/);
  vm.runInContext("agentNames={}",ctx);
});

test("Revenue Hunter is labelled as project progress",()=>{
  assert.match(card(rep({role:"revenue_hunter",lane:"PROJECT_PROGRESS_NOT_TRADING"})),/PROJECT進捗/);
});
