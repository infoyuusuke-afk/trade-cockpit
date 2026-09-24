import test from 'node:test';
import assert from 'node:assert/strict';
import { renderCockpitCard, renderCockpitWatchRow } from '../card_system.js';

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
