import fs from 'node:fs';
import assert from 'node:assert/strict';
const source = fs.readFileSync(new URL('../card_system.js', import.meta.url), 'utf8');
const {renderCockpitWatchRow, recordOnAir, getOnAirLog, clearOnAirLog} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const model={symbol:'TEST',price:123456,changePct:9.87,metrics:[{label:'bid',value:'654321'}]};
for(const freshness of ['stale','unknown']) {
  const html=renderCockpitWatchRow({...model,freshness});
  assert(!html.includes('123,456'));
  assert(!html.includes('9.87'));
  assert(!html.includes('654321'));
}
assert(renderCockpitWatchRow({...model,freshness:'fresh'}).includes('123,456'));
clearOnAirLog();
recordOnAir({...model,freshness:'fresh'});
assert.equal(getOnAirLog().length,1);
console.log('PASS: stale/unknown price, change and metrics hidden; fresh price shown; on-air log works without voice');
