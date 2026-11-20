/**
 * REALTIME 5 expected-value ranking helpers from index.html, run in a VM.
 * Ticker-level stats are used when they have enough trades, otherwise the
 * strategy level; INSUFFICIENT groups are never ranked above OK ones; text is
 * escaped. No network, broker, Excel or IPC.
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
  return html.slice(html.lastIndexOf("\n",at)+1,html.indexOf("\n",at));
}
function between(a,b){
  const s=html.indexOf(a),e=html.indexOf(b,s);
  assert.ok(s>=0&&e>s,"cannot find block "+a);
  return html.slice(s,e);
}
const src=line(" const esc=v=>String(v??\"\")")+"\n"+between(" const evStatFor=(t,x)=>{"," const renderEv=d=>{");
const ctx=vm.createContext({Number,String,Array,Object,JSON});
vm.runInContext(src,ctx,{timeout:2000});
const table={by_strategy:{"OR15押し目|買いサイン":{n:550,ev_pct:-0.165,gross_ev_pct:0.035,status:"OK",win_rate_pct:15.1,pf:0.19},
  "OR15戻り|空売りサイン":{n:596,ev_pct:-0.181,gross_ev_pct:0.019,status:"OK"},
  "新戦略|買いサイン":{n:5,ev_pct:1.2,status:"INSUFFICIENT"}},
  by_strategy_ticker:{"OR15押し目|買いサイン|6857.T":{n:30,ev_pct:0.05,status:"OK"},
    "OR15押し目|買いサイン|1000.T":{n:3,ev_pct:2.0,status:"INSUFFICIENT"}}};
const rank=rows=>JSON.parse(JSON.stringify(vm.runInContext("evRank("+JSON.stringify(table)+","+JSON.stringify(rows)+")",ctx)));

test("ticker level when enough trades, else strategy level; ordered by net EV",()=>{
  const got=rank([
    {ticker:"1000.T",signal:"買いサイン",strategy:"OR15押し目"},
    {ticker:"6857.T",signal:"買いサイン",strategy:"OR15押し目"},
    {ticker:"2000.T",signal:"空売りサイン",strategy:"OR15戻り"},
    {ticker:"3000.T",signal:"監視",strategy:"条件待ち"},
  ]);
  assert.deepEqual(got.map(r=>[r.x.ticker,r.ev.level,r.ev.ev_pct]),[
    ["6857.T","銘柄別",0.05],["1000.T","戦略別",-0.165],["2000.T","戦略別",-0.181]]);
});

test("insufficient evidence is never ranked above an OK group",()=>{
  const got=rank([{ticker:"9.T",signal:"買いサイン",strategy:"新戦略"},{ticker:"8.T",signal:"空売りサイン",strategy:"OR15戻り"}]);
  assert.deepEqual(got.map(r=>r.x.ticker),["8.T","9.T"]);
  const html=vm.runInContext("evRowHtml("+JSON.stringify(got[1])+",1)",ctx);
  assert.match(html,/根拠不足/);
});

test("negative expected value is labelled and text is escaped",()=>{
  const got=rank([{ticker:"2.T",name:"<img src=x onerror=alert(1)>",signal:"空売りサイン",strategy:"OR15戻り"}]);
  const out=vm.runInContext("evRowHtml("+JSON.stringify(got[0])+",0)",ctx);
  assert.match(out,/期待値マイナス/);
  assert.doesNotMatch(out,/<img/);
});
