import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";

const source=readFileSync(new URL("../trade_control.js",import.meta.url),"utf8");

function harness(fetcher=async()=>({ok:false})){
  const end=/\}\)\(\);\s*$/;
  assert.match(source,end,"trade_control.js must be a single self-contained IIFE");
  // Expose pure functions to the *test VM only*. The actual UI source is unchanged.
  const probe=source.replace(end,[
    "globalThis.__v10UiTest={knownNumber,money,pct,rfmt,computeStats,executionHtml,",
    "shadowEngineHtml,performanceHtml,tradeCard,loadHistory,upgradeWeeklyReview,renderOwnerSummaries};",
    "})();"
  ].join("\n"));
  const overview={innerHTML:""};
  const weekly={innerHTML:"",className:"",classList:{add(){}}};
  const document={
    addEventListener(){},
    querySelectorAll(){return [];},
    getElementById(id){
      return id==="owner-control-overview"?overview:id==="weekly-review"?weekly:null;
    }
  };
  const context={document,fetch:fetcher};
  vm.runInNewContext(probe,context,{filename:"trade_control.js",timeout:1500});
  return {...context.__v10UiTest,overview,weekly};
}

test("unknown, blank, boolean and malformed numbers must never be displayed as zero",()=>{
  const x=harness();
  for(const v of [null,undefined,""," ",false,true,{},[],"0x10","NaN","Infinity"]){
    assert.equal(x.knownNumber(v),null,String(v));
    assert.equal(x.money(v),"—");
    assert.equal(x.pct(v),"—");
    assert.equal(x.rfmt(v),"—");
  }
  assert.equal(x.money(0),"+0円");
  assert.equal(x.money("12.5"),"+12.5円");
  assert.equal(x.pct(0),"0.0%");
  assert.equal(x.rfmt("-1.5"),"-1.50R");
});

test("missing PnL must not count as closed zero-PnL trades or dilute win rate",()=>{
  const x=harness();
  assert.equal(x.computeStats([{pnl_yen:null},{pnl_yen:""},{result:"unavailable"}]),null);
  const s=x.computeStats([
    {pnl_yen:null,r:null},{pnl_yen:"",r:""},
    {pnl_yen:"100",r:null},{pnl_yen:-40,r:"-1"},{pnl_yen:0,r:0}
  ]);
  assert.equal(s.count,3);
  assert.equal(s.wins,1);
  assert.equal(s.pnl,60);
  assert.equal(s.winRate,100/3);
  assert.equal(s.avgR,-0.5);
});

test("connected but missing position counts are unknown; measured zero stays zero",()=>{
  const x=harness();
  const unknown=x.executionHtml({
    real_submit_allowed:false,broker_positions_connected:true,broker_position_count:null,
    shadow_positions_connected:true,shadow_open_position_count:""
  },{fail_closed:true});
  assert.ok(unknown.includes("実建玉<b>未確認</b>"),unknown);
  assert.ok(unknown.includes("Shadow建玉<b>未確認</b>"),unknown);
  assert.ok(unknown.includes("REAL ORDER LOCKED"),unknown);
  const measured=x.executionHtml({
    real_submit_allowed:false,broker_positions_connected:true,broker_position_count:0,
    shadow_positions_connected:true,shadow_open_position_count:0
  },{fail_closed:true});
  assert.ok(measured.includes("実建玉<b>0件</b>"),measured);
  assert.ok(measured.includes("Shadow建玉<b>0件</b>"),measured);
});

test("missing Shadow state and counters fail closed, not false STOPPED/zero",()=>{
  const x=harness();
  const html=x.shadowEngineHtml({
    shadow_engine_state:null,shadow_open_observation_count:null,
    shadow_ops:{daily:{shadow_uptime_ratio:null,error_count:null,total_downtime_seconds:null}}
  });
  assert.ok(html.includes("PAUSED_FAIL_CLOSED"),html);
  for(const label of ["仮想建玉","日次エラー","停止時間","稼働率"]){
    assert.ok(html.includes(label+"<b>—</b>"),label+" "+html);
  }
  assert.ok(!html.includes("STOPPED"),html);
});

test("a failed history response is unavailable, while a valid empty history is measured empty",async()=>{
  assert.equal(await harness(async()=>({ok:false})).loadHistory(),null);
  assert.equal(await harness(async()=>({ok:true,json:async()=>({})})).loadHistory(),null);
  const empty=await harness(async()=>({ok:true,json:async()=>([])})).loadHistory();
  assert.equal(Array.isArray(empty),true);
  assert.equal(empty.length,0);
});

test("CONTROL history overview shows unknown rather than zero on unavailable source",async()=>{
  const x=harness(async()=>({ok:false}));
  await x.renderOwnerSummaries();
  assert.ok(x.overview.innerHTML.includes("総履歴<b>—</b>"),x.overview.innerHTML);
  assert.ok(x.overview.innerHTML.includes("未分類<b>—</b>"),x.overview.innerHTML);
  assert.ok(x.overview.innerHTML.includes("件数や成績を0とは扱いません"),x.overview.innerHTML);
});

test("weekly review does not invent zero PnL or green profitability for missing values",async()=>{
  const x=harness(async url=>url.startsWith("weekly_review.json")
    ?{ok:true,json:async()=>({best:[{name:"synthetic",pnl_yen:null}],worst:[],themes:[],next_rules:[]})}
    :{ok:false});
  await x.upgradeWeeklyReview();
  assert.ok(x.weekly.innerHTML.includes("週間損益<b>—</b>"),x.weekly.innerHTML);
  assert.ok(x.weekly.innerHTML.includes("仮想取引<b>—</b>"),x.weekly.innerHTML);
  assert.ok(x.weekly.innerHTML.includes("cc-card--wait"),x.weekly.innerHTML);
  assert.ok(!x.weekly.innerHTML.includes("週間損益<b>+0円</b>"),x.weekly.innerHTML);
});

test("trade cards distinguish missing values from a measured zero",()=>{
  const x=harness();
  const unknown=x.tradeCard({ticker:"SYNTH",pnl_yen:null,r:null},"REVIEW","wait");
  const zero=x.tradeCard({ticker:"SYNTH",pnl_yen:0,r:0},"REVIEW","wait");
  assert.ok(unknown.includes("損益<b>—</b>"),unknown);
  assert.ok(unknown.includes("R<b>—</b>"),unknown);
  assert.ok(zero.includes("損益<b>+0円</b>"),zero);
});