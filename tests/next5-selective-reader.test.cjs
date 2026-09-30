'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  Next5BlockError,
  validateNext5Record,
  buildNext5,
  streamArrayObjectsFromJsonFile,
} = require('../next5/selective-reader.cjs');

const NOW = Date.parse('2026-09-30T10:00:30+09:00');

function rec(ticker, overrides = {}) {
  return {
    ticker,
    source_ticker: ticker,
    price: 1000,
    volume: 100000,
    quote_time: '2026-09-30T10:00:00+09:00',
    quote_valid: true,
    change_pct: 1.2,
    volume_burst: 2.0,
    flow_bias: 20,
    signal: '監視',
    strategy: '条件待ち',
    ...overrides,
  };
}

function codeOf(fn) {
  try { fn(); }
  catch (e) { assert.ok(e instanceof Next5BlockError); return e.code; }
  assert.fail('expected Next5BlockError');
}

test('validates a strict fresh JST quote', () => {
  const out = validateNext5Record(rec('285A.T'), { nowMs: NOW, maxAgeMs: 60_000 });
  assert.equal(out.source_ticker, '285A.T');
  assert.equal(out.quote_age_ms, 30_000);
});

test('blocks missing quote_time instead of inferring it', () => {
  const x = rec('285A.T');
  delete x.quote_time;
  assert.equal(codeOf(() => validateNext5Record(x, { nowMs: NOW })), 'QUOTE_TIME_MISSING');
});

test('blocks stale quote', () => {
  assert.equal(codeOf(() => validateNext5Record(rec('285A.T', {
    quote_time: '2026-09-30T09:58:00+09:00',
  }), { nowMs: NOW, maxAgeMs: 60_000 })), 'QUOTE_STALE');
});

test('blocks JST date mismatch', () => {
  assert.equal(codeOf(() => validateNext5Record(rec('285A.T', {
    quote_time: '2026-09-29T15:30:00+09:00',
  }), { nowMs: NOW })), 'QUOTE_DATE_MISMATCH');
});

test('blocks future quote', () => {
  assert.equal(codeOf(() => validateNext5Record(rec('285A.T', {
    quote_time: '2026-09-30T10:00:31+09:00',
  }), { nowMs: NOW })), 'QUOTE_FROM_FUTURE');
});

test('blocks non-explicit JST timestamp', () => {
  assert.equal(codeOf(() => validateNext5Record(rec('285A.T', {
    quote_time: '2026-09-30 10:00:00',
  }), { nowMs: NOW })), 'QUOTE_TIME_PARSE');
});

test('blocks identity mismatch without ticker inference', () => {
  assert.equal(codeOf(() => validateNext5Record(rec('285A.T', {
    source_ticker: '285A',
  }), { nowMs: NOW })), 'IDENTITY_MISMATCH');
});

test('blocks quote_valid false', () => {
  assert.equal(codeOf(() => validateNext5Record(rec('285A.T', {
    quote_valid: false,
  }), { nowMs: NOW })), 'QUOTE_INVALID');
});

test('buildNext5 rejects ambiguous duplicate identity', () => {
  const rows = ['1.T','2.T','3.T','4.T','5.T'].map((x) => rec(x));
  rows.push(rec('5.T'));
  assert.equal(codeOf(() => buildNext5(rows, { nowMs: NOW })), 'AMBIGUOUS_SOURCE');
});

test('buildNext5 blocks when fewer than five valid quotes remain', () => {
  const rows = ['1.T','2.T','3.T','4.T','5.T'].map((x) => rec(x));
  rows[4].quote_valid = false;
  assert.equal(codeOf(() => buildNext5(rows, { nowMs: NOW })), 'INSUFFICIENT_VALID_QUOTES');
});

test('early-move ranking uses deterministic evidence order without composite weights', () => {
  const rows = [
    rec('A.T', { volume_burst: 9.0, signal: '監視' }),
    rec('B.T', { volume_burst: 1.3, signal: '初動買い候補' }),
    rec('C.T', { volume_burst: 4.0, strategy: 'OR5初動' }),
    rec('D.T', { volume_burst: 3.5, signal: '監視' }),
    rec('E.T', { volume_burst: 2.5, signal: '監視' }),
  ];
  const out = buildNext5(rows, { nowMs: NOW });
  assert.deepEqual(out.rows.map((x) => x.ticker), ['B.T','C.T','A.T','D.T','E.T']);
});

test('stream reader extracts all_targets from source larger than 5MB without lifting full-read cap', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'next5-'));
  const file = path.join(dir, 'large.json');
  const filler = 'x'.repeat(5 * 1024 * 1024 + 1000);
  const rows = ['1.T','2.T','3.T','4.T','5.T'].map((x) => rec(x));
  fs.writeFileSync(file, JSON.stringify({ filler, all_targets: rows, tail: 'ok' }));
  const out = await streamArrayObjectsFromJsonFile(file);
  assert.ok(out.file_size > 5 * 1024 * 1024);
  assert.equal(out.records.length, 5);
  assert.equal(out.records[0].ticker, '1.T');
});

test('stream reader blocks missing target array', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'next5-'));
  const file = path.join(dir, 'missing.json');
  fs.writeFileSync(file, JSON.stringify({ rows: [rec('1.T')] }));
  await assert.rejects(() => streamArrayObjectsFromJsonFile(file), (e) => e.code === 'SOURCE_ARRAY_MISSING');
});

test('stream reader blocks oversized individual object', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'next5-'));
  const file = path.join(dir, 'oversized.json');
  fs.writeFileSync(file, JSON.stringify({ all_targets: [rec('1.T', { blob: 'x'.repeat(3000) })] }));
  await assert.rejects(() => streamArrayObjectsFromJsonFile(file, { maxItemBytes: 1000 }), (e) => e.code === 'SOURCE_ITEM_TOO_LARGE');
});
