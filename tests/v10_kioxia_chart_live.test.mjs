// P0-V10 Kioxia chart freshness (2026-10-21). Synthetic only.
// Runs the real helper block from index.html (KIO_LIVE_BEGIN..KIO_LIVE_END).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const begin = html.indexOf("// KIO_LIVE_BEGIN");
const end = html.indexOf("// KIO_LIVE_END");
assert.ok(begin > 0 && end > begin, "KIO_LIVE markers missing");
const block = html.slice(begin, end);

function load({ screenReady = true, rowReady = true } = {}) {
  const listeners = {};
  const draws = [];
  const nodes = { "kio-one-minute-note": { textContent: "" } };
  const window = {
    cockpitMs2ScreenReady: () => screenReady,
    cockpitMs2RowReady: () => rowReady,
  };
  const context = {
    window, Date, Number, String, Array, Math, JSON, Promise,
    document: {
      addEventListener: (name, fn) => { (listeners[name] ||= []).push(fn); },
      getElementById: id => nodes[id] || null,
    },
    kioOneMinuteChart: (...args) => draws.push(args),
  };
  vm.createContext(context);
  vm.runInContext(block + "\n;globalThis.__k={kioPickCalendar,kioMs2Actual,kioTodayJst};", context);
  return { ...context.__k, window, listeners, draws, nodes };
}

test("every inline script in index.html parses", () => {
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  assert.ok(scripts.length > 0);
  for (const code of scripts) {
    if (/^\s*import\s|\bexport\s/m.test(code)) continue; // module scripts are checked by their own tests
    new vm.Script(code); // throws SyntaxError on a broken script
  }
});

test("today in JST", () => {
  const { kioTodayJst } = load();
  assert.equal(kioTodayJst(Date.UTC(2026, 9, 20, 15, 30)), "2026-10-21"); // 00:30 JST
  assert.equal(kioTodayJst(Date.UTC(2026, 9, 20, 14, 59)), "2026-10-20");
});

test("today's calendar is preferred, newest first; another day is never 'today'", () => {
  const { kioPickCalendar } = load();
  const remote = { source: "GitHub main", data: { analysis_date: "2026-10-21", updated_at: "2026-10-21 08:05:00 JST" } };
  const local = { source: "V10フォルダ", data: { analysis_date: "2026-10-19", updated_at: "2026-10-19 22:52:40 JST" } };
  assert.deepEqual(kioPickCalendar([remote, local], "2026-10-21"), { ...remote, today: true });
  assert.deepEqual(kioPickCalendar([null, local], "2026-10-21"), { ...local, today: false });
  assert.equal(kioPickCalendar([null, null], "2026-10-21"), null);
  const later = { source: "V10フォルダ", data: { analysis_date: "2026-10-21", updated_at: "2026-10-21 09:30:00 JST" } };
  assert.equal(kioPickCalendar([remote, later], "2026-10-21").source, "V10フォルダ");
  assert.equal(kioPickCalendar([{ data: [1, 2] }], "2026-10-21"), null);
});

function row(extra = {}) {
  return {
    ticker: "285A.T", open_price: 13000, source_timestamp_at: "2026-10-21T09:05:03+09:00",
    bars_1m: [
      { ts: "2026-10-21 09:00:00", t: "09:00", o: 13000, h: 13130, l: 12935, c: 13065, v: 1000 },
      { ts: "2026-10-21 09:01:00", t: "09:01", o: 13065, h: 13100, l: 13000, c: 13000, v: 500 },
      { ts: "2026-10-20 15:29:00", t: "15:29", o: 13100, h: 13100, l: 13100, c: 13100, v: 1 },
    ],
    ...extra,
  };
}

test("MS2 bars become % from the MS2 open; other-day bars are dropped", () => {
  const { kioMs2Actual } = load();
  const out = kioMs2Actual({}, row(), "2026-10-21");
  assert.equal(out.length, 2);
  assert.equal(out[0].t, "09:00");
  assert.ok(Math.abs(out[0].h - 1.0) < 1e-9);
  assert.ok(Math.abs(out[0].l + 0.5) < 1e-9);
  assert.ok(Math.abs(out[1].c - 0) < 1e-9);
  assert.equal(out[1].price, 13000);
});

test("no MS2 candles unless board and row are verified, open known and quote today", () => {
  assert.equal(load({ screenReady: false }).kioMs2Actual({}, row(), "2026-10-21"), null);
  assert.equal(load({ rowReady: false }).kioMs2Actual({}, row(), "2026-10-21"), null);
  const { kioMs2Actual } = load();
  assert.equal(kioMs2Actual({}, row({ open_price: null }), "2026-10-21"), null);
  assert.equal(kioMs2Actual({}, row({ open_price: 0 }), "2026-10-21"), null);
  assert.equal(kioMs2Actual({}, row({ source_timestamp_at: "2026-10-20T15:00:00+09:00" }), "2026-10-21"), null);
  assert.equal(kioMs2Actual({}, row({ bars_1m: [{ ts: "2026-10-21 09:00:00", t: "09:00", o: null, h: 1, l: 1, c: 1 }] }), "2026-10-21"), null);
  assert.equal(kioMs2Actual({}, null, "2026-10-21"), null);
});

test("live update redraws with MS2 candles and clears them when MS2 is not verified", () => {
  const k = load();
  k.window.kioChartState = { points: [0, 1], actual: [], turns: [], levels: {} };
  const realNow = Date.now;
  try {
    const t0 = Date.UTC(2026, 9, 21, 0, 5, 0); // 09:05 JST
    Date.now = () => t0;
    k.listeners.ms2RssUpdate[0]({ detail: { all_targets: [row()] } });
    assert.equal(k.draws.length, 1);
    assert.equal(k.window.kioChartState.actualSource, "MS2");
    assert.equal(k.window.kioChartState.actual.length, 2);
    assert.match(k.nodes["kio-one-minute-note"].textContent, /^MS2 実測1分足 2本/);
    Date.now = () => t0 + 5000; // within 15 s: no redraw
    k.listeners.ms2RssUpdate[0]({ detail: { all_targets: [row()] } });
    assert.equal(k.draws.length, 1);
  } finally {
    Date.now = realNow;
  }
  const blocked = load({ screenReady: false });
  blocked.window.kioChartState = { points: [0, 1], actual: [{ t: "09:00" }], turns: [], levels: {}, actualSource: "MS2" };
  blocked.listeners.ms2RssUpdate[0]({ detail: { all_targets: [row()] } });
  assert.deepEqual(blocked.window.kioChartState.actual, []);
  assert.equal(blocked.window.kioChartState.actualSource, "NONE");
  assert.match(blocked.nodes["kio-one-minute-note"].textContent, /確認待ち/);
});
