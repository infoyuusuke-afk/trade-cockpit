'use strict';

const fs = require('node:fs');

const DEFAULT_MAX_AGE_MS = 60_000;
const DEFAULT_MAX_ITEM_BYTES = 512 * 1024;
const DEFAULT_MAX_RECORDS = 2_000;

class Next5BlockError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = 'Next5BlockError';
    this.code = code;
    this.details = details;
  }
}

function jstDateString(ms) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(ms));
  const m = Object.fromEntries(parts.map((x) => [x.type, x.value]));
  return `${m.year}-${m.month}-${m.day}`;
}

function parseStrictJstQuoteTime(value) {
  if (typeof value !== 'string') {
    throw new Next5BlockError('QUOTE_TIME_MISSING', 'quote_time must be a JST ISO-8601 string');
  }
  const s = value.trim();
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?\+09:00$/.test(s)) {
    throw new Next5BlockError('QUOTE_TIME_PARSE', 'quote_time must include an explicit +09:00 offset', { quote_time: value });
  }
  const ms = Date.parse(s);
  if (!Number.isFinite(ms)) {
    throw new Next5BlockError('QUOTE_TIME_PARSE', 'quote_time is not parseable', { quote_time: value });
  }
  return { ms, text: s };
}

function validateNext5Record(record, options = {}) {
  const nowMs = options.nowMs ?? Date.now();
  const maxAgeMs = options.maxAgeMs ?? DEFAULT_MAX_AGE_MS;

  if (!record || typeof record !== 'object' || Array.isArray(record)) {
    throw new Next5BlockError('RECORD_INVALID', 'NEXT5 source record must be an object');
  }
  if (record.data_role === 'DISCOVERY_ONLY' || record.status === 'DISCOVERY_ONLY') {
    throw new Next5BlockError('MS2_VERIFICATION_REQUIRED', 'discovery records are not MS2 quotes');
  }

  const ticker = typeof record.ticker === 'string' ? record.ticker.trim() : '';
  const sourceTicker = typeof record.source_ticker === 'string' ? record.source_ticker.trim() : '';
  if (!ticker) throw new Next5BlockError('TICKER_MISSING', 'ticker is missing');
  if (!sourceTicker) throw new Next5BlockError('SOURCE_TICKER_MISSING', 'source_ticker is missing', { ticker });
  if (ticker !== sourceTicker) {
    throw new Next5BlockError('IDENTITY_MISMATCH', 'ticker and source_ticker differ; inference is forbidden', {
      ticker, source_ticker: sourceTicker,
    });
  }

  if (record.quote_valid !== true) {
    throw new Next5BlockError('QUOTE_INVALID', 'quote_valid must be literal true', { ticker, quote_valid: record.quote_valid });
  }

  const { ms: quoteMs, text: quoteTime } = parseStrictJstQuoteTime(record.quote_time);
  const quoteDate = quoteTime.slice(0, 10);
  const todayJst = jstDateString(nowMs);
  if (quoteDate !== todayJst) {
    throw new Next5BlockError('QUOTE_DATE_MISMATCH', 'quote_time is not from the current JST date', {
      ticker, quote_date: quoteDate, expected_date: todayJst,
    });
  }
  if (quoteMs > nowMs) {
    throw new Next5BlockError('QUOTE_FROM_FUTURE', 'quote_time is in the future', { ticker, quote_time: quoteTime });
  }
  const ageMs = nowMs - quoteMs;
  if (ageMs > maxAgeMs) {
    throw new Next5BlockError('QUOTE_STALE', 'quote is older than NEXT5 freshness limit', {
      ticker, age_ms: ageMs, max_age_ms: maxAgeMs,
    });
  }

  const price = Number(record.price);
  const volume = Number(record.volume);
  if (!Number.isFinite(price) || price <= 0) {
    throw new Next5BlockError('PRICE_INVALID', 'price must be finite and > 0', { ticker, price: record.price });
  }
  if (!Number.isFinite(volume) || volume < 0) {
    throw new Next5BlockError('VOLUME_INVALID', 'volume must be finite and >= 0', { ticker, volume: record.volume });
  }

  return {
    ...record,
    ticker,
    source_ticker: sourceTicker,
    price,
    volume,
    quote_time: quoteTime,
    quote_age_ms: ageMs,
  };
}

function signalPriority(record) {
  const signal = String(record.signal || '');
  const strategy = String(record.strategy || '');
  if (signal === '初動買い候補' || signal === '初動ショート候補') return 0;
  if (strategy === 'OR5初動' || signal.includes('OR5')) return 1;
  if (Number(record.volume_burst) >= 1.2) return 2;
  if (signal === '買いサイン' || signal === '空売りサイン') return 3;
  return 4;
}

function finiteOr(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function rankEarlyMoves(records) {
  return records.slice().sort((a, b) => {
    const p = signalPriority(a) - signalPriority(b);
    if (p) return p;
    const burst = finiteOr(b.volume_burst) - finiteOr(a.volume_burst);
    if (burst) return burst;
    const flow = Math.abs(finiteOr(b.flow_bias)) - Math.abs(finiteOr(a.flow_bias));
    if (flow) return flow;
    const change = Math.abs(finiteOr(b.change_pct)) - Math.abs(finiteOr(a.change_pct));
    if (change) return change;
    return String(a.ticker).localeCompare(String(b.ticker));
  });
}

function buildNext5(records, options = {}) {
  const limit = options.limit ?? 5;
  const valid = [];
  const rejected = [];
  const seen = new Set();

  for (const raw of records) {
    const identity = raw && typeof raw === 'object' ? String(raw.source_ticker || raw.ticker || '') : '';
    if (identity && seen.has(identity)) {
      throw new Next5BlockError('AMBIGUOUS_SOURCE', 'duplicate ticker identity in source', { source_ticker: identity });
    }
    if (identity) seen.add(identity);
    try {
      valid.push(validateNext5Record(raw, options));
    } catch (err) {
      if (!(err instanceof Next5BlockError)) throw err;
      rejected.push({
        ticker: raw && typeof raw === 'object' ? raw.ticker ?? null : null,
        code: err.code,
        message: err.message,
      });
    }
  }

  if (valid.length < limit) {
    throw new Next5BlockError('INSUFFICIENT_VALID_QUOTES', 'fewer than five provably valid live quotes remain', {
      valid_count: valid.length,
      required_count: limit,
      rejected,
    });
  }

  const ranked = rankEarlyMoves(valid).slice(0, limit).map((x, i) => ({
    rank: i + 1,
    ...x,
    next5_reason: signalPriority(x) === 0 ? '初動候補'
      : signalPriority(x) === 1 ? 'OR5初動'
        : signalPriority(x) === 2 ? '出来高加速'
          : signalPriority(x) === 3 ? '売買サイン'
            : '監視',
  }));

  return {
    status: 'READY',
    count: ranked.length,
    rows: ranked,
    rejected,
  };
}

async function streamArrayObjectsFromJsonFile(filePath, options = {}) {
  const arrayKey = options.arrayKey ?? 'all_targets';
  const maxItemBytes = options.maxItemBytes ?? DEFAULT_MAX_ITEM_BYTES;
  const maxRecords = options.maxRecords ?? DEFAULT_MAX_RECORDS;

  const stat = await fs.promises.stat(filePath).catch((err) => {
    throw new Next5BlockError('SOURCE_MISSING', `source file is unavailable: ${err.code || err.message}`, { file_path: filePath });
  });
  if (!stat.isFile()) throw new Next5BlockError('SOURCE_INVALID', 'source path is not a regular file', { file_path: filePath });

  const input = fs.createReadStream(filePath, { encoding: 'utf8', highWaterMark: 64 * 1024 });
  const records = [];

  let rootDepth = 0;
  let inString = false;
  let escape = false;
  let token = '';
  let tokenAtRoot = false;
  let pendingKey = null;
  let foundKey = false;
  let waitingForArray = false;
  let inArray = false;
  let element = '';
  let elementDepth = 0;
  let elementInString = false;
  let elementEscape = false;
  let elementStarted = false;
  let done = false;

  function pushElement(text) {
    if (Buffer.byteLength(text, 'utf8') > maxItemBytes) {
      throw new Next5BlockError('SOURCE_ITEM_TOO_LARGE', 'one source record exceeds selective-reader item limit', {
        max_item_bytes: maxItemBytes,
      });
    }
    let parsed;
    try { parsed = JSON.parse(text); }
    catch (err) {
      throw new Next5BlockError('SOURCE_PARSE', 'failed to parse one selected source record', { error: err.message });
    }
    records.push(parsed);
    if (records.length > maxRecords) {
      throw new Next5BlockError('SOURCE_TOO_MANY_RECORDS', 'selected source array exceeds bounded record limit', {
        max_records: maxRecords,
      });
    }
  }

  try {
    outer: for await (const chunk of input) {
      for (let i = 0; i < chunk.length; i++) {
        const ch = chunk[i];

        if (inArray) {
          if (!elementStarted) {
            if (/\s/.test(ch) || ch === ',') continue;
            if (ch === ']') { done = true; break outer; }
            if (ch !== '{') {
              throw new Next5BlockError('SOURCE_SCHEMA', `${arrayKey} must contain JSON objects only`);
            }
            elementStarted = true;
            element = '{';
            elementDepth = 1;
            elementInString = false;
            elementEscape = false;
            continue;
          }

          element += ch;
          if (Buffer.byteLength(element, 'utf8') > maxItemBytes) {
            throw new Next5BlockError('SOURCE_ITEM_TOO_LARGE', 'one source record exceeds selective-reader item limit', {
              max_item_bytes: maxItemBytes,
            });
          }
          if (elementInString) {
            if (elementEscape) elementEscape = false;
            else if (ch === '\\') elementEscape = true;
            else if (ch === '"') elementInString = false;
            continue;
          }
          if (ch === '"') { elementInString = true; continue; }
          if (ch === '{' || ch === '[') elementDepth++;
          else if (ch === '}' || ch === ']') elementDepth--;
          if (elementDepth === 0) {
            pushElement(element);
            element = '';
            elementStarted = false;
          }
          continue;
        }

        if (waitingForArray) {
          if (/\s/.test(ch)) continue;
          if (ch !== '[') throw new Next5BlockError('SOURCE_SCHEMA', `${arrayKey} is not a JSON array`);
          inArray = true;
          waitingForArray = false;
          foundKey = true;
          continue;
        }

        if (inString) {
          if (escape) { escape = false; if (tokenAtRoot) token += ch; continue; }
          if (ch === '\\') { escape = true; if (tokenAtRoot) token += ch; continue; }
          if (ch === '"') {
            inString = false;
            if (tokenAtRoot) pendingKey = token;
            token = '';
            tokenAtRoot = false;
          } else if (tokenAtRoot) token += ch;
          continue;
        }

        if (ch === '"') {
          inString = true;
          tokenAtRoot = rootDepth === 1;
          token = '';
          continue;
        }
        if (ch === '{' || ch === '[') { rootDepth++; continue; }
        if (ch === '}' || ch === ']') { rootDepth--; continue; }

        if (pendingKey !== null) {
          if (/\s/.test(ch)) continue;
          if (ch === ':') {
            if (pendingKey === arrayKey && rootDepth === 1) waitingForArray = true;
            pendingKey = null;
            continue;
          }
          pendingKey = null;
        }
      }
    }
  } finally {
    input.destroy();
  }

  if (!foundKey) throw new Next5BlockError('SOURCE_ARRAY_MISSING', `top-level ${arrayKey} array was not found`);
  if (!done) throw new Next5BlockError('SOURCE_TRUNCATED', `${arrayKey} array did not terminate cleanly`);
  return {
    file_path: filePath,
    file_size: stat.size,
    mtime_ms: stat.mtimeMs,
    array_key: arrayKey,
    records,
  };
}

module.exports = {
  DEFAULT_MAX_AGE_MS,
  Next5BlockError,
  parseStrictJstQuoteTime,
  validateNext5Record,
  rankEarlyMoves,
  buildNext5,
  streamArrayObjectsFromJsonFile,
};
