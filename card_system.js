/* Card System (P0-B-0): shared card renderer for AI Trade Cockpit.
 *
 * Pure, dependency-free functions that build card HTML strings from a plain
 * data model. Never fabricates a value for a field the caller did not
 * supply: missing scalars render as the dash "—", missing optional blocks
 * (metrics / catalyst / conflict / fail-closed) are omitted entirely rather
 * than shown empty or zeroed. See docs/CARD_SYSTEM_CONTRACT.md for the full
 * model shape and field-by-field rules.
 *
 * Loaded as an ES module (`<script type="module" src="card_system.js">`) so
 * the exact same file can be `import`-ed by tests/card_system.test.mjs.
 * Also attaches to `window` so the existing non-module inline scripts
 * (scripts/weekly_tabs.py, scripts/update.py) can call it as a plain global,
 * the same way they already call window.renderScalpCard.
 */

const DIRECTIONS = new Set(["long", "short", "wait", "block"]);
const DEFAULT_LABELS = { long: "BUY", short: "SHORT", wait: "WAIT", block: "BLOCK" };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function isFiniteNumber(value) {
  return value != null && Number.isFinite(Number(value));
}

function fmtYen(value) {
  return isFiniteNumber(value)
    ? Number(value).toLocaleString("ja-JP", { maximumFractionDigits: 1 })
    : "—";
}

function fmtPct(value) {
  return isFiniteNumber(value)
    ? (Number(value) > 0 ? "+" : "") + Number(value).toFixed(2) + "%"
    : "—";
}

function fmtScalar(value) {
  if (value == null || value === "") return "—";
  return esc(value);
}

function sparklineHtml(source, label = "直近15分・1分足終値") {
  const raw = Array.isArray(source) ? source.slice(-15) : [];
  const vals = raw.map((x) => {
    if (isFiniteNumber(x)) return Number(x);
    if (x && isFiniteNumber(x.c)) return Number(x.c);
    if (x && isFiniteNumber(x.Close)) return Number(x.Close);
    return null;
  }).filter((x) => x != null);
  if (vals.length < 3) {
    return '<div class="cc-sparkline cc-sparkline--empty"><span>'+esc(label)+'</span><b>値動き履歴不足</b></div>';
  }
  const lo = Math.min(...vals), hi = Math.max(...vals), span = Math.max(hi - lo, 0.000001);
  const pts = vals.map((v, i) => {
    const x = vals.length === 1 ? 50 : (i / (vals.length - 1)) * 100;
    const y = 44 - ((v - lo) / span) * 36;
    return x.toFixed(2)+","+y.toFixed(2);
  }).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  return '<div class="cc-sparkline"><div class="cc-sparkline-head"><span>'+esc(label)+'</span><b>'+fmtYen(vals[vals.length-1])+'</b></div>'+
    '<svg viewBox="0 0 100 48" preserveAspectRatio="none" aria-label="'+esc(label)+'">'+
    '<polyline class="'+(up?'cc-sparkline-line--up':'cc-sparkline-line--down')+'" points="'+pts+'"/></svg></div>';
}

/**
 * Resolve age/staleness from either an explicit `freshness` override or
 * ageSeconds vs. staleThresholdSeconds. Returns {state, label}, state one
 * of "fresh" | "stale" | "unknown".
 */
function resolveFreshness(model) {
  if (model.freshness === "fresh" || model.freshness === "stale") {
    return { state: model.freshness, label: model.freshnessLabel ?? null };
  }
  const age = isFiniteNumber(model.ageSeconds) ? Number(model.ageSeconds) : null;
  const threshold = isFiniteNumber(model.staleThresholdSeconds)
    ? Number(model.staleThresholdSeconds)
    : null;
  if (age == null) return { state: "unknown", label: model.freshnessLabel ?? null };
  const state = threshold != null && age > threshold ? "stale" : "fresh";
  return { state, label: model.freshnessLabel ?? null };
}

function freshnessAgeText(model) {
  const raw = isFiniteNumber(model.ageSeconds) ? Number(model.ageSeconds) : null;
  if (raw == null) return "鮮度不明";
  // Clock skew between the data source and the viewer can make a
  // just-published data point look momentarily "in the future" (negative
  // age). Never show a negative number - that reads as a bug, not freshness.
  const age = Math.max(0, raw);
  if (age < 60) return `${Math.round(age)}秒前`;
  if (age < 3600) return `${Math.round(age / 60)}分前`;
  return `${Math.round(age / 3600)}時間前`;
}

function directionInfo(model) {
  const direction = DIRECTIONS.has(model.direction) ? model.direction : "wait";
  const label = model.directionLabel ?? DEFAULT_LABELS[direction];
  return { direction, label };
}

/**
 * Build one card's HTML. `model` fields (all optional unless noted):
 *   symbol (string, required), company, direction ("long"|"short"|"wait"|
 *   "block", required), directionLabel, price, changePct, ageSeconds,
 *   staleThresholdSeconds, freshness ("fresh"|"stale"|"unknown" override),
 *   freshnessLabel, entry, stop, target, metrics ([{label, value}]),
 *   catalyst, conflict (bool|string), failClosed (bool|string), foot.
 *
 * When failClosed is truthy the card is rendered in a muted, explicitly
 * fail-closed style and the BUY/SHORT badge is replaced with a neutral
 * "FAIL-CLOSED" marker — per the 2026-09-25 requirement that stale/conflict
 * states must never be styled to look like an actionable LIVE signal.
 */
export function renderCockpitCard(model) {
  if (!model || !model.symbol) {
    throw new Error("renderCockpitCard: model.symbol is required");
  }
  const failClosed = Boolean(model.failClosed);
  const { direction, label } = directionInfo(model);
  const fresh = resolveFreshness(model);
  const chg = isFiniteNumber(model.changePct) ? Number(model.changePct) : null;
  const chgCls = chg == null ? "cc-change--flat" : chg > 0 ? "cc-change--up" : chg < 0 ? "cc-change--down" : "cc-change--flat";

  const cardClasses = ["cc-card", `cc-card--${direction}`];
  if (failClosed) cardClasses.push("cc-card--fail-closed");
  if (!failClosed && model.opportunityState === "WATCH") cardClasses.push("cc-opportunity--watch");
  if (!failClosed && model.opportunityState === "HOT") cardClasses.push("cc-opportunity--hot");
  if (!failClosed && model.attentionPulse) cardClasses.push("cc-opportunity--pulse");

  const badgeLabel = failClosed ? "FAIL-CLOSED" : label;

  const metrics = Array.isArray(model.metrics)
    ? model.metrics.filter((m) => m && m.label != null && m.value != null && m.value !== "")
    : [];
  const metricsHtml = metrics.length
    ? `<div class="cc-metrics-grid">${metrics
        .map((m) => `<span>${esc(m.label)}<b>${esc(m.value)}</b></span>`)
        .join("")}</div>`
    : "";

  const sparklineBlock = model.sparkline ? sparklineHtml(model.sparkline, model.sparklineLabel) : "";

  const hasOrder = isFiniteNumber(model.entry) || isFiniteNumber(model.stop) || isFiniteNumber(model.target);
  const orderHtml = hasOrder
    ? `<div class="cc-order-grid"><span class="cc-entry">ENTRY<b>${fmtYen(model.entry)}</b></span><span class="cc-stop">STOP<b>${fmtYen(model.stop)}</b></span><span class="cc-target">TARGET<b>${fmtYen(model.target)}</b></span></div>`
    : "";

  const catalystHtml = model.catalyst
    ? `<div class="cc-catalyst">${esc(model.catalyst)}</div>`
    : "";

  const conflictHtml = model.conflict
    ? `<div class="cc-conflict">⚠ データ不一致：${esc(typeof model.conflict === "string" ? model.conflict : "複数ソース間で値が一致しません")}</div>`
    : "";

  const failClosedHtml = failClosed
    ? `<div class="cc-fail-closed-banner">⛔ Fail-Closed：${esc(typeof model.failClosed === "string" ? model.failClosed : "鮮度・整合性を確認できないため表示を抑制しています")}</div>`
    : "";

  const footHtml = model.foot ? `<div class="cc-foot">${esc(model.foot)}</div>` : "";

  return (
    `<article class="${cardClasses.join(" ")}" data-symbol="${esc(model.symbol)}">` +
    `<div class="cc-head"><div class="cc-identity"><span class="cc-company">${fmtScalar(model.company ?? model.symbol)}</span><span class="cc-symbol">TSE:${esc(model.symbol)}</span></div><span class="cc-badge">${esc(badgeLabel)}</span></div>` +
    `<div class="cc-price-row"><div class="cc-price">${fmtYen(model.price)}</div><div class="cc-change ${chgCls}">${fmtPct(model.changePct)}</div></div>` +
    `<div class="cc-freshness cc-freshness--${fresh.state}"><i class="cc-freshness-dot"></i>${esc(fresh.label ?? freshnessAgeText(model))}</div>` +
    sparklineBlock +
    conflictHtml +
    failClosedHtml +
    orderHtml +
    metricsHtml +
    catalystHtml +
    footHtml +
    `</article>`
  );
}

/**
 * Compact horizontal row variant for watch-list style listings: the
 * "on-air" symbol log (実況銘柄カード, direction/badge meaningful) as well
 * as plain scan lists like 監視銘柄/寄り前気配 (rank + metrics, no
 * long/short judgement - pass showBadge:false there). Same base model as
 * renderCockpitCard, plus:
 *   rank (number, optional) - shown as a leading "#N" chip.
 *   showBadge (bool, default true) - set false to omit the direction badge
 *     entirely for lists that carry no directional judgement.
 *   metrics ([{label, value}], optional) - short inline chips after the
 *     price, same drop-missing-values rule as renderCockpitCard.
 */
export function renderCockpitWatchRow(model) {
  if (!model || !model.symbol) {
    throw new Error("renderCockpitWatchRow: model.symbol is required");
  }
  const { direction, label } = directionInfo(model);
  const fresh = resolveFreshness(model);
  const chg = isFiniteNumber(model.changePct) ? Number(model.changePct) : null;
  const chgCls = chg == null ? "cc-change--flat" : chg > 0 ? "cc-change--up" : chg < 0 ? "cc-change--down" : "cc-change--flat";
  const showBadge = model.showBadge !== false;
  const rankHtml = isFiniteNumber(model.rank) ? `<span class="cc-rank">#${Math.trunc(model.rank)}</span>` : "";

  const metrics = Array.isArray(model.metrics)
    ? model.metrics.filter((m) => m && m.label != null && m.value != null && m.value !== "")
    : [];
  const metricsHtml = metrics.length
    ? `<div class="cc-watch-metrics">${metrics
        .map((m) => `<span>${esc(m.label)}<b>${esc(m.value)}</b></span>`)
        .join("")}</div>`
    : "";

  return (
    `<div class="cc-watch-row cc-card--${direction}">` +
    rankHtml +
    `<div class="cc-identity"><span class="cc-company">${fmtScalar(model.company ?? model.symbol)}</span><span class="cc-symbol">TSE:${esc(model.symbol)}</span></div>` +
    (showBadge ? `<span class="cc-badge">${esc(label)}</span>` : "") +
    `<div class="cc-price-row"><div class="cc-price">${fmtYen(model.price)}</div><div class="cc-change ${chgCls}">${fmtPct(model.changePct)}</div></div>` +
    metricsHtml +
    `<div class="cc-freshness cc-freshness--${fresh.state}"><i class="cc-freshness-dot"></i>${esc(fresh.label ?? freshnessAgeText(model))}</div>` +
    `</div>`
  );
}

/*
 * On-air log (実況銘柄カード): a small rolling record of symbols that were
 * (or would have been) voice-announced, so a missed/disabled voice alert is
 * still visible on screen. This module only stores/renders what callers
 * explicitly record via recordOnAir() - it never listens for speech events
 * itself and never decides what counts as alert-worthy; that stays entirely
 * with the caller's existing alert logic. Deliberately decoupled from
 * window.cockpitSpeak's market-hours/voice-toggle gating, since the whole
 * point is that the card must still update even when voice did not fire.
 */
const ON_AIR_LOG_LIMIT = 8;
let onAirLog = [];

/** Record (or re-surface) one symbol in the on-air log. Moves an existing
 * entry for the same symbol to the front instead of duplicating it. */
export function recordOnAir(model) {
  if (!model || !model.symbol) {
    throw new Error("recordOnAir: model.symbol is required");
  }
  const entry = { ...model, announcedAt: Date.now() };
  onAirLog = [entry, ...onAirLog.filter((e) => e.symbol !== model.symbol)].slice(0, ON_AIR_LOG_LIMIT);
  return onAirLog;
}

export function getOnAirLog() {
  return onAirLog;
}

/** Test-only: reset the module-level log between test cases. */
export function clearOnAirLog() {
  onAirLog = [];
}

export function renderOnAirPanel() {
  if (!onAirLog.length) {
    return '<div class="cc-onair-empty">実況銘柄はまだありません（音声通知・注目銘柄はここに表示されます）</div>';
  }
  return onAirLog
    .map((entry) => renderCockpitWatchRow({ ...entry, ageSeconds: (Date.now() - entry.announcedAt) / 1000 }))
    .join("");
}

if (typeof window !== "undefined") {
  window.renderCockpitCard = renderCockpitCard;
  window.renderCockpitWatchRow = renderCockpitWatchRow;
  window.recordOnAir = recordOnAir;
  window.getOnAirLog = getOnAirLog;
  window.renderOnAirPanel = renderOnAirPanel;
}
