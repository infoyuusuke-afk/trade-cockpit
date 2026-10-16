const test=require("node:test"),assert=require("node:assert/strict");
const {statusLabel,shadowLabel,brainObserverLabel,summarizeHealth}=require("../v10_publication_status.js");
test("healthy publication NEVER yields authenticated market data",()=>{
  const r=summarizeHealth({status:"ok",runtime:{
    collector_publication_state:"RECENT_PUBLICATION_ONLY",
    watcher_publication_state:"RECENT_PUBLICATION_ONLY",
    brain_publication_state:"UNKNOWN_NOT_PUBLISHED"
  },execution:{real_submit_allowed:false}});
  assert.equal(r.state,"PUBLICATION_ONLY");
  assert.match(r.text,/未認証/);
  assert.match(r.text,/BRAIN 未検証/);
  assert.match(r.text,/実注文禁止/);
  assert.doesNotMatch(r.text,/売買可能|発注許可/);
});
test("offline / missing / forbidden execution are unknown",()=>{
  for(const payload of [null,{}, {status:"ok",runtime:{},execution:{real_submit_allowed:true}}]){
    const r=summarizeHealth(payload);
    assert.equal(r.state,"UNKNOWN");
    assert.match(r.text,/実注文禁止/);
  }
});
test("missing or stale Watcher explicit distinction",()=>{
  assert.match(statusLabel("PUBLICATION_STALE"),/60秒超/);
  assert.equal(statusLabel("WATCHER_FILE_UNAVAILABLE"),"未確認");
  assert.match(statusLabel("PROCESS_UNVERIFIED"),/未検証/);
});

test("SHADOW heartbeat is not independent BRAIN or market authentication",()=>{
  const r=summarizeHealth({status:"ok",runtime:{
    collector_publication_state:"RECENT_PUBLICATION_ONLY",
    watcher_publication_state:"RECENT_PUBLICATION_ONLY",
    shadow_heartbeat_status:"SHADOW_RUNNING_HEARTBEAT_ONLY",
    brain_publication_state:"UNKNOWN_NOT_PUBLISHED"
  },execution:{real_submit_allowed:false,shadow_engine_state:"RUNNING"}});
  assert.match(r.text,/SHADOW プロセス発行確認/);
  assert.match(r.text,/BRAIN 未検証/);
  assert.match(r.text,/28584はGatewayのみ/);
  assert.match(r.text,/実注文禁止/);
  assert.match(shadowLabel("SHADOW_TIMESTAMP_STALE_OR_FUTURE"),/発行遅延/);
  assert.match(shadowLabel("SHADOW_PID_MISMATCH"),/プロセス未検証/);
  assert.match(shadowLabel("SHADOW_ORDER_FLAG_UNSAFE"),/フラグ異常/);
});

test("independent BRAIN observation is not authenticated or a trade sign",()=>{
  const r=summarizeHealth({status:"ok",runtime:{
    collector_publication_state:"RECENT_PUBLICATION_ONLY",
    watcher_publication_state:"RECENT_PUBLICATION_ONLY",
    shadow_heartbeat_status:"SHADOW_RUNNING_HEARTBEAT_ONLY",
    brain_publication_state:"UNKNOWN_NOT_PUBLISHED",
    brain_observer_state:"BRAIN_OBSERVING_PUBLICATION_ONLY",
    brain_observer_watch_count:7
  },execution:{real_submit_allowed:false}});
  assert.match(r.text,/BRAIN 未検証/);
  assert.match(r.text,/独立観測中/);
  assert.match(r.text,/期待値未認証/);
  assert.match(r.text,/実注文禁止/);
  assert.doesNotMatch(r.text,/実売買可能|発注許可/);
  assert.match(brainObserverLabel("BRAIN_PID_MISMATCH"),/未検証/);
  assert.match(brainObserverLabel("BRAIN_UNSAFE_EVIDENCE_CLAIM"),/拒否/);
});
