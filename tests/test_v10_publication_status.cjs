const test=require("node:test"),assert=require("node:assert/strict");
const {statusLabel,summarizeHealth}=require("../v10_publication_status.js");
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
