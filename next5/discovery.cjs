'use strict';

const fs = require('node:fs');
const { Next5BlockError } = require('./selective-reader.cjs');
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_ROWS = 300;
const MAX_AGE_MS = 60_000;
const SOURCE = 'TradingViewスクリーナー（非公式・無保証API、scanner.tradingview.com）';
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const fail = code => { throw new Next5BlockError(code, code); };
const jst = ms => new Date(ms + 9 * 3600_000).toISOString();

function timestamp(value, nowMs) {
  if (typeof value !== 'string') fail('DISCOVERY_TIME_MISSING');
  // This producer supplies acquisition time, never an MS2 quote timestamp.
  const iso = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} JST$/.test(value)
    ? value.replace(' ', 'T').replace(' JST', '+09:00') : value;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/.test(iso)) fail('DISCOVERY_TIME_PARSE');
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms) || jst(ms).slice(0, 19) !== iso.slice(0, 19)) fail('DISCOVERY_TIME_PARSE');
  if (jst(ms).slice(0, 10) !== jst(nowMs).slice(0, 10)) fail('DISCOVERY_DATE_MISMATCH');
  if (ms > nowMs) fail('DISCOVERY_FROM_FUTURE');
  if (nowMs - ms > MAX_AGE_MS) fail('DISCOVERY_STALE');
  return { iso, age: nowMs - ms };
}

function watchedTickers(manifest) {
  if (!object(manifest) || !object(manifest.stocks)) fail('FIXED100_MISSING');
  const entries = Object.values(manifest.stocks);
  // The existing fixed100 manifest can contain fewer than exactly 100 names.
  if (!entries.length || entries.length > 100) fail('FIXED100_INVALID');
  const seen = new Set();
  for (const entry of entries) {
    if (!object(entry) || typeof entry.ticker !== 'string' || !/^[0-9][0-9A-Z]{3}\.T$/.test(entry.ticker)) fail('FIXED100_IDENTITY');
    if (seen.has(entry.ticker)) fail('FIXED100_DUPLICATE');
    seen.add(entry.ticker);
  }
  return seen;
}

function normalizeDiscovery(payload, manifest, { nowMs = Date.now() } = {}) {
  if (!Number.isFinite(nowMs) || !Number.isFinite(new Date(nowMs).getTime())) fail('DISCOVERY_CLOCK_INVALID');
  const watched = watchedTickers(manifest);
  if (!object(payload) || payload.schema_version !== 'tradingview-screener-watch-1.0' || payload.source !== SOURCE) fail('DISCOVERY_SOURCE_IDENTITY');
  if (payload.error !== null) fail('DISCOVERY_SOURCE_ERROR');
  const time = timestamp(payload.updated_at, nowMs);
  if (!Array.isArray(payload.scan_rows)) fail('DISCOVERY_ROWS_MISSING');
  if (payload.scan_rows.length > MAX_ROWS) fail('DISCOVERY_TOO_MANY_ROWS');
  const seen = new Set();
  const rows = [];
  for (const row of payload.scan_rows) {
    if (!object(row) || typeof row.code !== 'string' || !/^[0-9][0-9A-Z]{3}$/.test(row.code) || row.exchange !== 'TSE') fail('DISCOVERY_IDENTITY');
    const ticker = `${row.code}.T`;
    // Explicit TSE code mapping is discovery identity only, not MS2 proof.
    if ((row.ticker !== undefined && row.ticker !== ticker) ||
        (row.source_ticker !== undefined && row.source_ticker !== `TSE:${row.code}`) ||
        (row.source !== undefined && row.source !== SOURCE) ||
        (row.updated_at !== undefined && row.updated_at !== payload.updated_at)) fail('DISCOVERY_IDENTITY_CONFLICT');
    if (seen.has(ticker)) fail('DISCOVERY_DUPLICATE');
    seen.add(ticker);
    if (typeof row.change_pct !== 'number' || !Number.isFinite(row.change_pct) ||
        typeof row.relative_volume !== 'number' || !Number.isFinite(row.relative_volume) || row.relative_volume < 0) fail('DISCOVERY_METRIC_INVALID');
    // Validate every row before filtering: duplicates or corrupt watched rows
    // must not silently turn a partial snapshot into an accepted snapshot.
    if (watched.has(ticker)) continue;
    rows.push({
      ticker, source_ticker: `TSE:${row.code}`, source_code: row.code,
      exchange: row.exchange, source: payload.source,
      updated_at: payload.updated_at, updated_at_iso: time.iso,
      freshness_basis: 'SCREENER_ACQUISITION_TIME', source_age_ms: time.age,
      change: row.change_pct, change_pct: row.change_pct, relative_volume: row.relative_volume,
      outside_fixed100: true, data_role: 'DISCOVERY_ONLY', status: 'DISCOVERY_ONLY',
      ms2_verified: false, ready_eligible: false, quote_valid: false,
      real_submit_allowed: false, stop_code: 'MS2_VERIFICATION_REQUIRED',
    });
  }
  return {
    status: 'DISCOVERY_ONLY', data_role: 'DISCOVERY_ONLY', source: payload.source,
    coverage: 'JAPAN_VOLUME_FILTERED_MAX_300_NOT_EXHAUSTIVE',
    scanned_count: payload.scan_rows.length, fixed100_count: watched.size,
    count: rows.length, rows, ready_candidates: [], real_submit_allowed: false,
    stop_code: 'MS2_VERIFICATION_REQUIRED',
  };
}

async function readBoundedJson(filePath) {
  // Enforce the cap on bytes actually read as well as stat, including file growth.
  const handle = await fs.promises.open(filePath, 'r');
  try {
    const stat = await handle.stat();
    if (!stat.isFile()) fail('DISCOVERY_SOURCE_INVALID');
    if (stat.size > MAX_BYTES) fail('SOURCE_TOO_LARGE');
    const buffer = Buffer.alloc(MAX_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, null);
      if (!bytesRead) break;
      length += bytesRead;
    }
    if (length > MAX_BYTES) fail('SOURCE_TOO_LARGE');
    const after = await handle.stat();
    if (after.size !== stat.size || after.mtimeMs !== stat.mtimeMs || length !== stat.size) fail('DISCOVERY_SOURCE_CHANGED');
    try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(0, length))); }
    catch { fail('DISCOVERY_SOURCE_PARSE'); }
  } finally { await handle.close(); }
}

async function discoverFromFiles({ sourcePath, fixed100Path, nowMs = Date.now() }) {
  try {
    const payload = await readBoundedJson(sourcePath);
    const manifest = await readBoundedJson(fixed100Path);
    return normalizeDiscovery(payload, manifest, { nowMs });
  } catch (error) {
    return { status: 'BLOCK', data_role: 'DISCOVERY_ONLY', rows: [], ready_candidates: [],
      real_submit_allowed: false, stop_code: error instanceof Next5BlockError ? error.code : 'DISCOVERY_SOURCE_UNAVAILABLE' };
  }
}

module.exports = { SOURCE, MAX_BYTES, normalizeDiscovery, discoverFromFiles };
