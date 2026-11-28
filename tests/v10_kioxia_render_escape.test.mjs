/**
 * FIX-03 (2026-10-21): KIOXIA tab renders external JSON as text, not markup.
 * Runs the shipped esc/kioSafeUrl helpers and the real catalyst, US-context
 * and gap-study render lines from index.html in a VM with hostile values.
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
const helpers=line(" const esc=v=>String(v??\"\")")+"\n"+line(" const kioSafeUrl=u=>");
// signedPct only formats numbers; a local copy keeps the test independent of its layout.
const signedPct='const signedPct=(v,digits=1)=>Number.isFinite(Number(v))?(Number(v)>=0?"+":"")+Number(v).toFixed(digits)+"%":"未取得";';
const HOSTILE="<img src=x onerror=alert(1)>\"'</script><b>";

function run(src,data){
  const nodes=new Map();
  const document={getElementById(id){if(!nodes.has(id))nodes.set(id,{innerHTML:"",textContent:""});return nodes.get(id);}};
  const ctx=vm.createContext({document,URL,String,Number,Object,Array,...data});
  vm.runInContext(helpers+"\n"+signedPct+"\n"+src,ctx,{timeout:2000});
  return {nodes,ctx};
}

test("kioSafeUrl only links http(s) and escapes the href",()=>{
  const {ctx}=run("",{});
  assert.equal(vm.runInContext('kioSafeUrl("javascript:alert(1)")',ctx),"#");
  assert.equal(vm.runInContext('kioSafeUrl("data:text/html,x")',ctx),"#");
  assert.equal(vm.runInContext('kioSafeUrl("not a url")',ctx),"#");
  assert.equal(vm.runInContext('kioSafeUrl(null)',ctx),"#");
  assert.equal(vm.runInContext('kioSafeUrl("https://example.com/a?b=1&c=\\"x")',ctx),"https://example.com/a?b=1&amp;c=%22x");
});

test("catalyst list renders hostile fields as text and drops a javascript: link",()=>{
  const src=line('document.getElementById("kio-catalyst-list").innerHTML=');
  const item={verified:true,date:HOSTILE,kind:HOSTILE,stage:HOSTILE,title:HOSTILE,fact:HOSTILE,expectation:HOSTILE,
    risk:HOSTILE,next_checkpoint:HOSTILE,impact:HOSTILE,source_url:"javascript:alert(1)"};
  const {nodes}=run(src,{catalysts:{items:[item]}});
  const out=nodes.get("kio-catalyst-list").innerHTML;
  assert.doesNotMatch(out,/<img|<\/script>/);
  assert.match(out,/&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(out,/href='#'/);
  assert.doesNotMatch(out,/javascript:/);
});

test("US context labels and gap-study fields are escaped",()=>{
  const us=line('document.getElementById("kio-us-context").innerHTML =');
  const r1=run(us,{context:{values:{[HOSTILE]:1.5}},usLabels:{}});
  assert.doesNotMatch(r1.nodes.get("kio-us-context").innerHTML,/<img/);
  const gap=line('document.getElementById("kio-gap-study").innerHTML=');
  const r2=run(gap,{gaps:[{usable:true,bucket:HOSTILE,sample:HOSTILE,close_up_rate:HOSTILE,gap_fill_rate:HOSTILE,
    median_day_ret:1,median_max_up:1,median_max_down:-1}]});
  const out=r2.nodes.get("kio-gap-study").innerHTML;
  assert.doesNotMatch(out,/<img|<\/script>/);
  assert.match(out,/&lt;img/);
});
