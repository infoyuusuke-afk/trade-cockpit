import fs from 'node:fs';
import assert from 'node:assert/strict';
const source = fs.readFileSync(new URL('../card_system.js', import.meta.url), 'utf8');
const {renderCockpitCard, renderCockpitWatchRow, renderOnAirPanel, livePriceBlocked, recordOnAir, getOnAirLog, clearOnAirLog} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const model={symbol:'TEST',price:123456,changePct:9.87,metrics:[{label:'bid',value:'654321'}],entry:100,stop:90,target:120,sparkline:[1,2,3]};
for(const freshness of ['stale','unknown']) {
  const html=renderCockpitWatchRow({...model,freshness});
  assert(!html.includes('123,456'));
  assert(!html.includes('9.87'));
  assert(!html.includes('654321'));
}
const failClosedFresh=renderCockpitWatchRow({...model,freshness:'fresh',failClosed:'PRICE_SOURCE_MISMATCH'});
assert(!failClosedFresh.includes('123,456'));
assert(renderCockpitWatchRow({...model,freshness:'fresh'}).includes('123,456'));
const card=renderCockpitCard({...model,direction:'long',freshness:'stale',failClosed:'鮮度確認不可'});
assert(!card.includes('123,456'));
assert(!card.includes('9.87'));
assert(!card.includes('654321'));
assert(!card.includes('>100<'));
assert(card.includes('FAIL-CLOSED'));
const ok={
  source:'MarketSpeed II RSS / local PC',
  source_mode:'MS2_RSS_WORKBOOK',
  price_source_status:'OK',
  live_values_available:true,
  data_conflict:false,
  live_price_diagnostics:{price_source_status:'OK',source_mode:'MS2_RSS_WORKBOOK',live_values_available:true,data_conflict:false}
};
assert.equal(livePriceBlocked(ok),'');
assert.equal(livePriceBlocked({...ok,connection_source:'公開スナップショット'}),'CACHED_OR_SAMPLE_PAYLOAD');
assert.equal(livePriceBlocked({...ok,data_conflict:true}),'DATA_CONFLICT');
assert.equal(livePriceBlocked({...ok,price_source_status:'PRICE_SOURCE_MISMATCH'}),'PRICE_SOURCE_MISMATCH');
assert.equal(livePriceBlocked({...ok,live_values_available:false}),'LIVE_VALUES_UNAVAILABLE');
assert.equal(livePriceBlocked({source:'MarketSpeed II RSS / local PC'}),'MISSING_PRICE_DIAGNOSTICS');
clearOnAirLog();
recordOnAir({symbol:'OLD',price:777777,changePct:1.25,metrics:[{label:'bid',value:'888'}]});
getOnAirLog()[0].announcedAt=Date.now()-120000;
assert(!renderOnAirPanel().includes('777,777'));
clearOnAirLog();
recordOnAir({...model,freshness:'fresh'});
assert.equal(getOnAirLog().length,1);
console.log('PASS: stale/fail-closed prices hidden; transport reasons classified; aged on-air price hidden');
