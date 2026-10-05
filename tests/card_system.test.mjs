import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import {
  renderCockpitCard, renderCockpitWatchRow,
  recordOnAir, getOnAirLog, clearOnAirLog, renderOnAirPanel,
  resolveIdentityLivePrice, identityPriceText,
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

function localStamp(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function livePayload(price, at, patch = {}) {
  const body = {
    source: 'MarketSpeed II RSS / local PC',
    source_mode: 'MS2_RSS_WORKBOOK',
    price_source_status: 'OK',
    live_values_available: true,
    real_submit_allowed: false,
    data_conflict: false,
    stale: false,
    updated_at: at,
    live_price_diagnostics: {
      symbol: '285A.T',
      current_price: price,
      source_mode: 'MS2_RSS_WORKBOOK',
      price_source_status: 'OK',
      live_values_available: true,
      source_timestamp: '09:10:01',
    },
    kioxia: { ticker: '285A.T', price },
  };
  return { ...body, ...patch, live_price_diagnostics: { ...body.live_price_diagnostics, ...(patch.live_price_diagnostics || {}) } };
}

test('285A current price is shown only when collector and gateway agree', () => {
  const now = Date.parse('2026-10-05T09:10:02');
  const at = '2026-10-05 09:10:02';
  const collector = livePayload(19120, at);
  const gateway = livePayload(19120, at);
  const chain = resolveIdentityLivePrice(collector, gateway, now);
  assert.equal(chain.ok, true);
  assert.equal(chain.collector_value, 19120);
  assert.equal(chain.gateway_value, 19120);
  assert.equal(chain.ui_value, 19120);
  assert.equal(identityPriceText(chain), '19,120円');
  assert.equal(collector.real_submit_allowed, false);

  const next = resolveIdentityLivePrice(livePayload(19150, at), livePayload(19150, at), now);
  assert.equal(next.ui_value, 19150);
  assert.equal(identityPriceText(next), '19,150円');
  assert.notEqual(identityPriceText(chain), identityPriceText(next));
});

test('snapshot, stale cache, old symbol, and a one-sided price stay blank', () => {
  const now = Date.parse('2026-10-05T09:10:02');
  const at = '2026-10-05 09:10:02';
  const collector = livePayload(19120, at);
  const cases = [
    [null, livePayload(19120, at)],
    [collector, null],
    [collector, livePayload(8035, at)],
    [livePayload(19120, at, { connection_source: '公開スナップショット' }), livePayload(19120, at)],
    [livePayload(19120, at, { source: 'sample snapshot' }), livePayload(19120, at)],
    [livePayload(19120, '2026-10-05 08:00:00'), livePayload(19120, '2026-10-05 08:00:00')],
    [livePayload(19120, at, { live_price_diagnostics: { symbol: '8035.T' } }), livePayload(19120, at, { live_price_diagnostics: { symbol: '8035.T' } })],
    [livePayload(0, at), livePayload(0, at)],
    [livePayload(19120, at, { real_submit_allowed: true }), livePayload(19120, at)],
    [livePayload(19120, at, { kioxia: { ticker: '285A.T', price: 100 } }), livePayload(19120, at)],
    [livePayload(19120, at, { live_values_available: false }), livePayload(19120, at)],
  ];
  for (const [left, right] of cases) {
    const chain = resolveIdentityLivePrice(left, right, now);
    assert.equal(chain.ok, false);
    assert.equal(chain.ui_value, null);
    assert.equal(identityPriceText(chain), '—');
    assert.equal(identityPriceText(chain).includes('19120'), false);
  }
});

test('page wires the visible 285A price to the collector-gateway chain', () => {
  const index = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(index, /http:\/\/127\.0\.0\.1:28580\/live_ms2\.json/);
  assert.match(index, /http:\/\/127\.0\.0\.1:28581\/live_ms2\.json/);
  assert.match(index, /id="kio-live-current-price">—</);
  assert.match(index, /identityPriceText/);
  assert.doesNotMatch(index, /kio-live-current-price">19,/);
  assert.doesNotMatch(index, /fetchJson\("live_ms2\.json/);
});

function serveJson(getPayload) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const body = JSON.stringify(getPayload());
      res.writeHead(200, {
        'Content-Type': 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Private-Network': 'true',
      });
      res.end(body);
    });
    server.listen(0, '127.0.0.1', () => resolve(server));
  });
}

test('COLLECTOR_VALUE equals GATEWAY_VALUE equals UI_VALUE across a price change', async () => {
  let price = 19120;
  const serverA = await serveJson(() => livePayload(price, localStamp(Date.now())));
  const serverB = await serveJson(() => livePayload(price, localStamp(Date.now())));
  try {
    const read = async (server) => {
      const { port } = server.address();
      const response = await fetch(`http://127.0.0.1:${port}/live_ms2.json?t=${Date.now()}`, { cache: 'no-store' });
      assert.equal(response.status, 200);
      return response.json();
    };
    const firstCollector = await read(serverA);
    const firstGateway = await read(serverB);
    const first = resolveIdentityLivePrice(firstCollector, firstGateway, Date.now());
    assert.equal(first.collector_value, 19120);
    assert.equal(first.gateway_value, 19120);
    assert.equal(first.ui_value, 19120);
    price = 19240;
    const secondCollector = await read(serverA);
    const secondGateway = await read(serverB);
    const second = resolveIdentityLivePrice(secondCollector, secondGateway, Date.now());
    assert.equal(second.collector_value, 19240);
    assert.equal(second.gateway_value, 19240);
    assert.equal(second.ui_value, 19240);
    assert.equal(identityPriceText(second), '19,240円');
    const evidence = {
      symbol: '285A.T',
      real_submit_allowed: false,
      COLLECTOR_VALUE: second.collector_value,
      GATEWAY_VALUE: second.gateway_value,
      UI_VALUE: second.ui_value,
      previous_ui_value: first.ui_value,
      snapshot_ui_value: null,
    };
    const artifactDir = '/opt/cursor/artifacts';
    if (fs.existsSync(artifactDir)) {
      fs.writeFileSync(`${artifactDir}/identity_price_chain.json`, JSON.stringify(evidence, null, 2));
    }
  } finally {
    serverA.closeAllConnections();
    serverB.closeAllConnections();
    serverA.close();
    serverB.close();
  }
});
