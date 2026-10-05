'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { SOURCE, MAX_BYTES, normalizeDiscovery, discoverFromFiles } = require('../next5/discovery.cjs');
const { buildNext5, validateNext5Record } = require('../next5/selective-reader.cjs');
const NOW = Date.parse('2026-10-01T10:00:30+09:00');
const manifest = () => ({ stocks: { watched: { ticker: '285A.T' } } });
const row = (code = '336A') => ({ code, exchange: 'TSE', change_pct: 2.1, relative_volume: 3.2 });
const payload = () => ({ schema_version: 'tradingview-screener-watch-1.0', source: SOURCE,
  updated_at: '2026-10-01 10:00:00 JST', error: null, scan_rows: [row(), row('285A')] });
const run = (p = payload(), m = manifest(), nowMs = NOW) => normalizeDiscovery(p, m, { nowMs });
const blocked = (fn, code) => assert.throws(fn, e => e.code === code);

test('normalizes outside fixed100 with original provenance and no quote privileges', () => {
  const p = payload(); p.scan_rows[0].already_watched = true;
  p.scan_rows[1].already_watched = false;
  const before = JSON.stringify(p);
  const result = run(p);
  assert.equal(JSON.stringify(p), before);
  assert.equal(result.status, 'DISCOVERY_ONLY');
  assert.equal(result.count, 1);
  assert.deepEqual(result.ready_candidates, []);
  const r = result.rows[0];
  assert.equal(r.ticker, '336A.T'); assert.equal(r.source_ticker, 'TSE:336A');
  assert.equal(r.source, SOURCE); assert.equal(r.updated_at, p.updated_at);
  assert.equal(r.change, 2.1); assert.equal(r.relative_volume, 3.2);
  assert.equal(r.source_age_ms, 30_000); assert.equal(r.ms2_verified, false);
  assert.equal(r.quote_valid, false); assert.equal(r.ready_eligible, false);
  assert.equal(r.price, undefined); assert.equal(r.quote_time, undefined);
});

for (const [name, edit, code] of [
  ['source missing', p => delete p.source, 'DISCOVERY_SOURCE_IDENTITY'],
  ['source wrong', p => p.source = 'MS2', 'DISCOVERY_SOURCE_IDENTITY'],
  ['schema wrong', p => p.schema_version = 'unknown', 'DISCOVERY_SOURCE_IDENTITY'],
  ['producer failed', p => p.error = 'timeout', 'DISCOVERY_SOURCE_ERROR'],
  ['error missing', p => delete p.error, 'DISCOVERY_SOURCE_ERROR'],
  ['time missing', p => delete p.updated_at, 'DISCOVERY_TIME_MISSING'],
  ['no timezone', p => p.updated_at = '2026-10-01T10:00:00', 'DISCOVERY_TIME_PARSE'],
  ['invalid calendar', p => p.updated_at = '2026-02-30T10:00:00+09:00', 'DISCOVERY_TIME_PARSE'],
  ['future', p => p.updated_at = '2026-10-01T10:00:31+09:00', 'DISCOVERY_FROM_FUTURE'],
  ['stale', p => p.updated_at = '2026-10-01T09:59:29+09:00', 'DISCOVERY_STALE'],
  ['old JST day', p => p.updated_at = '2026-09-30T10:00:00+09:00', 'DISCOVERY_DATE_MISMATCH'],
  ['missing scan rows', p => delete p.scan_rows, 'DISCOVERY_ROWS_MISSING'],
  ['too many rows', p => p.scan_rows = Array(301).fill(row()), 'DISCOVERY_TOO_MANY_ROWS'],
  ['duplicate outside', p => p.scan_rows.push(row()), 'DISCOVERY_DUPLICATE'],
  ['duplicate watched', p => p.scan_rows.push(row('285A')), 'DISCOVERY_DUPLICATE'],
  ['missing identity', p => delete p.scan_rows[0].code, 'DISCOVERY_IDENTITY'],
  ['numeric code', p => p.scan_rows[0].code = 336, 'DISCOVERY_IDENTITY'],
  ['foreign exchange', p => p.scan_rows[0].exchange = 'NASDAQ', 'DISCOVERY_IDENTITY'],
  ['identity conflict', p => p.scan_rows[0].ticker = '285A.T', 'DISCOVERY_IDENTITY_CONFLICT'],
  ['source identity conflict', p => p.scan_rows[0].source_ticker = 'TSE:285A', 'DISCOVERY_IDENTITY_CONFLICT'],
  ['row time conflict', p => p.scan_rows[0].updated_at = 'yesterday', 'DISCOVERY_IDENTITY_CONFLICT'],
  ['row source conflict', p => p.scan_rows[0].source = 'MS2', 'DISCOVERY_IDENTITY_CONFLICT'],
  ['missing change', p => delete p.scan_rows[0].change_pct, 'DISCOVERY_METRIC_INVALID'],
  ['null volume', p => p.scan_rows[0].relative_volume = null, 'DISCOVERY_METRIC_INVALID'],
  ['string change', p => p.scan_rows[0].change_pct = '2', 'DISCOVERY_METRIC_INVALID'],
  ['nonfinite change', p => p.scan_rows[0].change_pct = Infinity, 'DISCOVERY_METRIC_INVALID'],
  ['negative volume', p => p.scan_rows[0].relative_volume = -1, 'DISCOVERY_METRIC_INVALID'],
  ['invalid watched row', p => p.scan_rows[1].relative_volume = null, 'DISCOVERY_METRIC_INVALID'],
]) test(`fail closed: ${name}`, () => { const p = payload(); edit(p); blocked(() => run(p), code); });

test('missing, empty, corrupt or duplicate fixed100 is never treated as unwatched universe', () => {
  blocked(() => run(payload(), null), 'FIXED100_MISSING');
  blocked(() => run(payload(), { stocks: {} }), 'FIXED100_INVALID');
  blocked(() => run(payload(), { stocks: { x: { ticker: '285A' } } }), 'FIXED100_IDENTITY');
  blocked(() => run(payload(), { stocks: { x: { ticker: '285A.T' }, y: { ticker: '285A.T' } } }), 'FIXED100_DUPLICATE');
});
test('clock cannot bypass freshness', () => {
  for (const n of [NaN, Infinity, 'now', 1e99]) blocked(() => run(payload(), manifest(), n), 'DISCOVERY_CLOCK_INVALID');
});
test('freshness boundary and explicit ISO supported', () => {
  const p = payload(); p.updated_at = '2026-10-01T09:59:30+09:00';
  assert.equal(run(p).count, 1);
});
test('zero candidates stays discovery only without padding', () => {
  const p = payload(); p.scan_rows = [row('285A')];
  assert.deepEqual(run(p).rows, []);
  p.scan_rows = []; assert.equal(run(p).status, 'DISCOVERY_ONLY');
});
test('forged external READY and MS2 flags are stripped; reader refuses even enriched discovery', () => {
  const p = payload(); Object.assign(p.scan_rows[0], { status: 'READY', ms2_verified: true,
    ready_eligible: true, quote_valid: true, price: 1000, volume: 100,
    quote_time: '2026-10-01T10:00:00+09:00' });
  const r = run(p).rows[0];
  assert.equal(r.ms2_verified, false);
  const enriched = { ...r, source_ticker: r.ticker, ms2_verified: true, quote_valid: true,
    price: 1000, volume: 100, quote_time: '2026-10-01T10:00:00+09:00' };
  blocked(() => validateNext5Record(enriched, { nowMs: NOW }), 'MS2_VERIFICATION_REQUIRED');
  blocked(() => buildNext5([enriched], { nowMs: NOW, limit: 1 }), 'INSUFFICIENT_VALID_QUOTES');
});

test('file adapter bounds bytes and blocks parse/missing/stale data without candidates', async t => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'next5-discovery-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const sourcePath = path.join(dir, 'source.json');
  const fixed100Path = path.join(dir, 'fixed.json');
  const read = () => discoverFromFiles({ sourcePath, fixed100Path, nowMs: NOW });
  await fs.writeFile(fixed100Path, JSON.stringify(manifest()));
  for (const [data, expected] of [
    [JSON.stringify(payload()), 'MS2_VERIFICATION_REQUIRED'],
    [' '.repeat(MAX_BYTES + 1), 'SOURCE_TOO_LARGE'],
    ['{"scan_rows":', 'DISCOVERY_SOURCE_PARSE'],
    [JSON.stringify({ ...payload(), updated_at: '2026-09-30 10:00:00 JST' }), 'DISCOVERY_DATE_MISMATCH'],
  ]) {
    await fs.writeFile(sourcePath, data);
    const r = await read(); assert.equal(r.stop_code, expected);
    assert.deepEqual(r.ready_candidates, []);
    if (r.status === 'BLOCK') assert.deepEqual(r.rows, []);
  }
  await fs.unlink(sourcePath);
  assert.equal((await read()).stop_code, 'DISCOVERY_SOURCE_UNAVAILABLE');
});
