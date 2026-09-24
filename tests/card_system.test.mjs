import test from 'node:test';
import assert from 'node:assert/strict';
import {
  renderCockpitCard, renderCockpitWatchRow,
  recordOnAir, getOnAirLog, clearOnAirLog, renderOnAirPanel,
} from '../card_system.js';

test('renderCockpitCard requires a symbol', () => {
  assert.throws(() => renderCockpitCard({}), /symbol is required/);
  assert.throws(() => renderCockpitCard(null), /symbol is required/);
});

test('renderCockpitCard renders the direction badge and card modifier class', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'long' });
  assert.match(html, /class="cc-card cc-card--long"/);
  assert.match(html, /class="cc-badge">BUY</);
});

test('unknown direction falls back to wait, not a fabricated state', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'not-a-real-direction' });
  assert.match(html, /cc-card--wait/);
  assert.match(html, />WAIT</);
});

test('directionLabel overrides the default badge text', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'short', directionLabel: 'SHORT WATCH' });
  assert.match(html, />SHORT WATCH</);
});

test('missing price/entry/stop/target never render as fabricated numbers', () => {
  const html = renderCockpitCard({ symbol: '9984', direction: 'wait' });
  assert.match(html, /cc-price">—</);
  // no order block at all when none of entry/stop/target are finite numbers
  assert.doesNotMatch(html, /cc-order-grid/);
});

test('order block appears when at least one of entry/stop/target is present', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'long', entry: 49870 });
  assert.match(html, /cc-order-grid/);
  assert.match(html, /ENTRY<b>49,870</);
  assert.match(html, /STOP<b>—</);
});

test('metrics entries with no value are dropped, not shown as dashes', () => {
  const html = renderCockpitCard({
    symbol: '285A',
    direction: 'long',
    metrics: [
      { label: 'VWAP', value: '49,668' },
      { label: 'OR5', value: null },
      { label: 'OR15', value: '' },
    ],
  });
  assert.match(html, /VWAP<b>49,668/);
  assert.doesNotMatch(html, />OR5</);
  assert.doesNotMatch(html, />OR15</);
});

test('freshness defaults to unknown when no age/threshold/override is given', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'wait' });
  assert.match(html, /cc-freshness--unknown/);
  assert.match(html, /鮮度不明/);
});

test('freshness is derived from ageSeconds vs staleThresholdSeconds', () => {
  const fresh = renderCockpitCard({ symbol: '285A', direction: 'long', ageSeconds: 10, staleThresholdSeconds: 60 });
  assert.match(fresh, /cc-freshness--fresh/);

  const stale = renderCockpitCard({ symbol: '285A', direction: 'long', ageSeconds: 120, staleThresholdSeconds: 60 });
  assert.match(stale, /cc-freshness--stale/);
});

test('negative ageSeconds (clock skew) never renders as a negative number', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'long', ageSeconds: -5663, staleThresholdSeconds: 60 });
  assert.doesNotMatch(html, /-\d+秒前/);
  assert.match(html, /0秒前/);
});

test('conflict banner only renders when conflict is set, and carries a message', () => {
  const noConflict = renderCockpitCard({ symbol: '285A', direction: 'wait' });
  assert.doesNotMatch(noConflict, /cc-conflict/);

  const withConflict = renderCockpitCard({ symbol: '285A', direction: 'wait', conflict: 'MS2とTradingViewで価格が不一致' });
  assert.match(withConflict, /cc-conflict/);
  assert.match(withConflict, /MS2とTradingViewで価格が不一致/);
});

test('failClosed forces the FAIL-CLOSED badge and suppresses the direction badge text', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'long', failClosed: true });
  assert.match(html, /cc-card--fail-closed/);
  assert.match(html, /class="cc-badge">FAIL-CLOSED</);
  assert.doesNotMatch(html, />BUY</);
});

test('failClosed with a string renders it as the banner message', () => {
  const html = renderCockpitCard({ symbol: '285A', direction: 'long', failClosed: '鮮度切れ・過去データ参考値' });
  assert.match(html, /cc-fail-closed-banner/);
  assert.match(html, /鮮度切れ・過去データ参考値/);
});

test('all free-text fields are HTML-escaped', () => {
  const html = renderCockpitCard({
    symbol: '285A',
    company: '<script>alert(1)</script>',
    direction: 'wait',
    catalyst: '<img onerror=alert(1)>',
    foot: '"quoted" & <b>bold</b>',
  });
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<img onerror/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&amp;/);
});

test('renderCockpitWatchRow requires a symbol and renders a compact row', () => {
  assert.throws(() => renderCockpitWatchRow({}), /symbol is required/);
  const html = renderCockpitWatchRow({ symbol: '6857', company: 'アドバンテスト', direction: 'short', price: 12345 });
  assert.match(html, /class="cc-watch-row cc-card--short"/);
  assert.match(html, /アドバンテスト/);
  assert.match(html, /12,345/);
});

test('renderCockpitWatchRow: showBadge:false omits the direction badge', () => {
  const html = renderCockpitWatchRow({ symbol: '285A', company: 'キオクシアHD', direction: 'wait', showBadge: false });
  assert.doesNotMatch(html, /cc-badge/);
});

test('renderCockpitWatchRow: rank renders as a leading chip, omitted when absent', () => {
  const withRank = renderCockpitWatchRow({ symbol: '285A', direction: 'wait', rank: 3 });
  assert.match(withRank, /class="cc-rank">#3</);
  const withoutRank = renderCockpitWatchRow({ symbol: '285A', direction: 'wait' });
  assert.doesNotMatch(withoutRank, /cc-rank/);
});

test('renderCockpitWatchRow: explicit freshness override with a custom label (watch-list "LIVE"/"データ停止" pattern)', () => {
  const live = renderCockpitWatchRow({ symbol: '6920', direction: 'wait', showBadge: false, freshness: 'fresh', freshnessLabel: 'LIVE' });
  assert.match(live, /cc-freshness--fresh/);
  assert.match(live, />LIVE</);
  const stopped = renderCockpitWatchRow({ symbol: '6920', direction: 'wait', showBadge: false, freshness: 'stale', freshnessLabel: 'データ停止' });
  assert.match(stopped, /cc-freshness--stale/);
  assert.match(stopped, /データ停止/);
});

test('renderCockpitWatchRow: metrics chips render, missing values dropped, never fabricated', () => {
  const html = renderCockpitWatchRow({
    symbol: '285A', direction: 'wait',
    metrics: [{ label: 'UNDER', value: '34%' }, { label: '出来高加速', value: null }],
  });
  assert.match(html, /UNDER<b>34%/);
  assert.doesNotMatch(html, />出来高加速</);
});

test('on-air log: recordOnAir requires a symbol', () => {
  clearOnAirLog();
  assert.throws(() => recordOnAir({}), /symbol is required/);
});

test('on-air log: renderOnAirPanel shows an empty state with no fabricated rows', () => {
  clearOnAirLog();
  const html = renderOnAirPanel();
  assert.match(html, /cc-onair-empty/);
  assert.doesNotMatch(html, /cc-watch-row/);
});

test('on-air log: recordOnAir adds to the front, most recent first', () => {
  clearOnAirLog();
  recordOnAir({ symbol: '285A', company: 'キオクシアHD', direction: 'long' });
  recordOnAir({ symbol: '6920', company: 'レーザーテック', direction: 'short' });
  const log = getOnAirLog();
  assert.equal(log.length, 2);
  assert.equal(log[0].symbol, '6920');
  assert.equal(log[1].symbol, '285A');
});

test('on-air log: re-announcing the same symbol moves it to front, never duplicates', () => {
  clearOnAirLog();
  recordOnAir({ symbol: '285A', company: 'キオクシアHD', direction: 'long' });
  recordOnAir({ symbol: '6920', company: 'レーザーテック', direction: 'short' });
  recordOnAir({ symbol: '285A', company: 'キオクシアHD', direction: 'long', price: 50000 });
  const log = getOnAirLog();
  assert.equal(log.length, 2);
  assert.equal(log[0].symbol, '285A');
  assert.equal(log[0].price, 50000);
});

test('on-air log: caps at 8 entries, dropping the oldest', () => {
  clearOnAirLog();
  for (let i = 0; i < 10; i++) {
    recordOnAir({ symbol: `S${i}`, company: `Stock ${i}`, direction: 'wait' });
  }
  const log = getOnAirLog();
  assert.equal(log.length, 8);
  assert.equal(log[0].symbol, 'S9');
  assert.equal(log[log.length - 1].symbol, 'S2');
});

test('on-air log: renderOnAirPanel renders a watch row per entry, most recent first', () => {
  clearOnAirLog();
  recordOnAir({ symbol: '285A', company: 'キオクシアHD', direction: 'long' });
  recordOnAir({ symbol: '6920', company: 'レーザーテック', direction: 'short' });
  const html = renderOnAirPanel();
  assert.equal((html.match(/cc-watch-row/g) || []).length, 2);
  assert.ok(html.indexOf('レーザーテック') < html.indexOf('キオクシアHD'));
});
