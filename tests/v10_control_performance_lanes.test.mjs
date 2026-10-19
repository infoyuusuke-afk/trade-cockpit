import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import {readFileSync} from "node:fs";

const source=readFileSync(new URL("../trade_control.js",import.meta.url),"utf8");

function harness(fetcher=async()=>({ok:false}),withPane=false){
  const end=/\}\)\(\);\s*$/;
  assert.match(source,end);
  const probe=source.replace(end,
    "globalThis.__controlTest={performanceEligibility,reconcilePerformanceRows,strategyStats,strategyGroups,controlPerformanceHtml,performanceHtml,computeStats,renderOwnerSummaries,jstDay,jstWeek};\n})();"
  );
  const box={innerHTML:""};
  const history={innerHTML:""};
  const perTab={innerHTML:""};
  const pane={dataset:{pane:"scalp"},querySelector(q){
    if(q.includes("data-tab-performance"))return perTab;
    if(q.includes("data-execution-control"))return {innerHTML:""};
    return null;
  }};
  const document={
    addEventListener(){},
    querySelectorAll(q){return withPane&&q===".tab-pane"?[pane]:[];},
    getElementById(id){
      return id==="owner-strategy-performance"?box:id==="owner-control-overview"?history:null;
    }
  };
  const context={document,fetch:fetcher};
  vm.runInNewContext(probe,context,{timeout:1500,filename:"trade_control.js"});
  return {...context.__controlTest,box,history,perTab};
}

const AT="2026-10-19T09:06:00+09:00";
const CLOSE="2026-10-19T09:05:00+09:00";
const NOW=Date.parse("2026-10-21T00:00:00+09:00");

function fixture(id,mode="shadow",tab="scalp",pnl=100){
  return {trade_id:id,mode,cockpit_tab:tab,status:"CLOSED",closed_at:CLOSE,
    available_at:AT,pnl_yen:pnl,r:1,mfe_r:1.5,mae_r:-0.5};
}
const reconcile=(items,now=NOW)=>harness().reconcilePerformanceRows(items,now);

test("untagged legacy data remains quarantined, not attributed to REALTIME by strategy_id",()=>{
  const rows=[{strategy_id:"day_rank_long",pnl_yen:100,source:"morning_snapshot"},
    {strategy_id:"day_short_mvp",pnl_yen:-50,source:"morning_snapshot"}];
  const audit=reconcile(rows);
  assert.equal(audit.total,2);
  assert.equal(audit.quarantined,2);
  assert.equal(audit.eligible.length,0);
  const html=harness().controlPerformanceHtml(audit);
  assert.ok(html.includes("保留（未分類・重複等）<b>2件</b>"),html);
  assert.ok(html.includes("REAL｜実取引"),html);
  assert.ok(html.includes("未接続"),html);
  assert.ok(!html.includes("仮想累計損益<b>+50円</b>"),html);
});

test("a paper file never proves a REAL trade, even with positive PnL",()=>{
  const rows=[fixture("REAL1","real"),fixture("SH1","paper"),fixture("BT1","backtest")];
  const audit=reconcile(rows);
  assert.equal(audit.eligible.length,2);
  assert.equal(audit.quarantined,1);
  const groups=harness().strategyGroups(audit.eligible);
  assert.equal((groups.get("shadow:scalp")||[]).length,1);
  assert.equal((groups.get("backtest:scalp")||[]).length,1);
  assert.equal((groups.get("real:scalp")||[]).length,0);
});

test("future, ambiguous timezone and lookahead inputs fail closed",()=>{
  const invalid=[
    {...fixture("NO_TZ"),available_at:"2026-10-19T09:06:00"},
    {...fixture("BAD_TIME"),available_at:"not-a-time"},
    {...fixture("AFTER_NOW"),available_at:"2026-10-22T09:00:00+09:00"},
    {...fixture("CLOSE_FUTURE"),closed_at:"2026-10-19T09:07:00+09:00"},
    {...fixture("MISSING_AVAILABLE"),available_at:null},
    {...fixture("MISSING_CLOSED"),closed_at:null}
  ];
  assert.equal(reconcile(invalid).eligible.length,0);
  assert.equal(reconcile(invalid).quarantined,invalid.length);
});

test("duplicate trade_id invalidates all occurrences, including malformed row",()=>{
  const valid=fixture("DUPLICATE");
  const poisoned={...fixture("DUPLICATE"),mode:"real",available_at:null};
  const good=fixture("UNIQUE");
  const audit=reconcile([valid,poisoned,good]);
  assert.equal(audit.eligible.length,1);
  assert.equal(audit.eligible[0].id,"UNIQUE");
  assert.equal(audit.quarantined,2);
});

test("open marks and missing PnL are never called realized wins",()=>{
  const invalid=[
    {...fixture("OPEN"),exit_reason:"OPEN_MARK"},
    {...fixture("OPEN2"),status:"OPEN"},
    {...fixture("OPEN3"),result:"未決済"},
    {...fixture("NO_PNL"),pnl_yen:null},
    {...fixture("EMPTY_PNL"),pnl_yen:""},
    {...fixture("BAD_PNL"),pnl_yen:"NaN"},
    {...fixture("UNKNOWN_MODE"),mode:"unknown"},
    {...fixture("NO_TAB"),cockpit_tab:null},
    {...fixture("BAD_ID"),trade_id:"secrets / path"}
  ];
  assert.equal(reconcile(invalid).eligible.length,0);
  assert.equal(reconcile(invalid).quarantined,invalid.length);
});

test("legitimate settled 0 remains measured 0; missing data is not 0",()=>{
  const audit=reconcile([fixture("ZERO","shadow","scalp",0)]);
  const st=harness().strategyStats(audit.eligible);
  assert.equal(st.count,1);
  assert.equal(st.pnl,0);
  assert.equal(st.winRate,0);
  assert.equal(st.pf,null); // no gross losses; never invent 99
  assert.equal(harness().computeStats([{pnl_yen:100}]).pf,null);
});

test("chronological cumulative, drawdown and recent trades use close-time ordering",()=>{
  const p=[100,-50,-120,30],r=[1,-0.5,-1.2,0.3];
  const rows=p.map((value,i)=>({...fixture("SER"+i,"paper","scalp",value),
    r:r[i],closed_at:"2026-10-19T09:"+String(10+i).padStart(2,"0")+":00+09:00",
    available_at:"2026-10-19T09:"+String(10+i).padStart(2,"0")+":30+09:00"})).reverse();
  const audit=reconcile(rows);
  const st=harness().strategyStats(audit.eligible);
  assert.equal(st.pnl,-40);
  assert.equal(st.maxDrawdown,170);
  assert.ok(Math.abs(st.maxDrawdownR-1.7)<1e-10);
  assert.equal(st.recentN,4);
  assert.equal(st.recentPnl,-40);
  assert.equal(st.cumulative[0].pnl_yen,100);
  assert.equal(st.cumulative[3].pnl_yen,-40);
  assert.equal(st.mfeAvg,1.5);
  assert.equal(st.maeAvg,-0.5);
});

test("JST day and ISO-Monday week boundary is not browser-local timezone",()=>{
  const x=harness();
  const sunday=Date.parse("2026-10-18T23:59:00+09:00");
  const monday=Date.parse("2026-10-19T00:01:00+09:00");
  assert.equal(x.jstDay(sunday),"2026-10-18");
  assert.equal(x.jstDay(monday),"2026-10-19");
  assert.equal(x.jstWeek(sunday),"2026-10-12");
  assert.equal(x.jstWeek(monday),"2026-10-19");
});

test("recent window is capped at 20 and MFE/MAE are unknown if partial",()=>{
  const rows=Array.from({length:25},(_,i)=>({...fixture("REC"+i),closed_at:
      "2026-10-19T09:"+String(i).padStart(2,"0")+":00+09:00",
    available_at:"2026-10-19T09:"+String(i).padStart(2,"0")+":01+09:00",
    pnl_yen:1,mfe_r:i===5?null:1.4}));
  const st=harness().strategyStats(reconcile(rows).eligible);
  assert.equal(st.count,25);
  assert.equal(st.recentN,20);
  assert.equal(st.recentPnl,20);
  assert.equal(st.mfeAvg,null);
  assert.equal(st.maeAvg,-0.5);
});

test("SHADOW/PAPER and BACKTEST cards are segregated and Real remains disconnected",()=>{
  const audit=reconcile([
    fixture("SH","shadow","scalp",200),fixture("BT","backtest","scalp",-300)
  ]);
  const html=harness().controlPerformanceHtml(audit);
  assert.ok(html.includes("SHADOW/PAPER｜SCALP 5"),html);
  assert.ok(html.includes("BACKTEST｜SCALP 5"),html);
  assert.ok(html.includes("REAL｜実取引"),html);
  assert.ok(html.includes("仮想累計損益<b>+200円</b>"),html);
  assert.ok(html.includes("仮想累計損益<b>-300円</b>"),html);
  assert.ok(!html.includes("仮想累計損益<b>-100円</b>"),html);
});

test("relative ranking requires two same-mode strategies with N at least 20",()=>{
  const rows=[];
  for(let i=0;i<20;i++){
    rows.push(fixture("SC"+i,"shadow","scalp",100));
    rows.push(fixture("EV"+i,"shadow","event-hot",-20));
  }
  const html=harness().controlPerformanceHtml(reconcile(rows));
  assert.ok(html.includes("SHADOW/PAPER｜相対強弱"),html);
  assert.ok(html.includes("平均PnL上位<b>SCALP 5 +100円</b>"),html);
  assert.ok(html.includes("平均PnL下位<b>EVENT 5 -20円</b>"),html);
  const insufficient=harness().controlPerformanceHtml(reconcile(rows.slice(0,10)));
  assert.ok(insufficient.includes("N不足"),insufficient);
  assert.ok(!insufficient.includes("平均PnL上位"),insufficient);
});

test("no source must stay UNKNOWN instead of an invented zero-trade performance",()=>{
  const x=harness();
  const audit=x.reconcilePerformanceRows(null,NOW);
  const html=x.controlPerformanceHtml(audit);
  assert.ok(html.includes("履歴取得不能"),html);
  assert.ok(html.includes("元履歴<b>—</b>"),html);
  assert.ok(html.includes("取引件数<b>—</b>"),html);
  assert.ok(!html.includes("取引件数<b>0件</b>"),html);
});

test("existing per-tab cards never combine SHADOW/PAPER and BACKTEST PnL",async()=>{
  const rows=[fixture("CROSS-SH","paper","scalp",200),fixture("CROSS-BT","backtest","scalp",-100)];
  const x=harness(async url=>url.startsWith("paper_trade_history.json")
    ?{ok:true,json:async()=>rows}:{ok:false},true);
  await x.renderOwnerSummaries();
  assert.ok(x.perTab.innerHTML.includes("モード別表示"),x.perTab.innerHTML);
  assert.ok(x.perTab.innerHTML.includes("混合損益<b>—</b>"),x.perTab.innerHTML);
  assert.ok(!x.perTab.innerHTML.includes("仮想損益<b>+100円</b>"),x.perTab.innerHTML);
});

test("CONTROL render with legacy record stays safe and honors the existing DOM",async()=>{
  const x=harness(async url=>url.startsWith("paper_trade_history.json")
    ?{ok:true,json:async()=>[{strategy_id:"day_rank_long",pnl_yen:555}]}
    :{ok:false},true);
  await x.renderOwnerSummaries();
  assert.ok(x.box.innerHTML.includes("保留（未分類・重複等）<b>1件</b>"),x.box.innerHTML);
  assert.ok(x.perTab.innerHTML.includes("未接続"),x.perTab.innerHTML);
  assert.ok(x.history.innerHTML.includes("実績データの分類"),x.history.innerHTML);
});