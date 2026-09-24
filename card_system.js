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
  const age = isFiniteNumber(model.ageSeconds) ? Number(model.ageSeconds) : null;
  if (age == null) return "鮮度不明";
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

  const badgeLabel = failClosed ? "FAIL-CLOSED" : label;

  const metrics = Array.isArray(model.metrics)
    ? model.metrics.filter((m) => m && m.label != null && m.value != null && m.value !== "")
    : [];
  const metricsHtml = metrics.length
    ? `<div class="cc-metrics-grid">${metrics
        .map((m) => `<span>${esc(m.label)}<b>${esc(m.value)}</b></span>`)
        .join("")}</div>`
    : "";

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
    `<article class="${cardClasses.join(" ")}">` +
    `<div class="cc-head"><div class="cc-identity"><span class="cc-company">${fmtScalar(model.company ?? model.symbol)}</span><span class="cc-symbol">TSE:${esc(model.symbol)}</span></div><span class="cc-badge">${esc(badgeLabel)}</span></div>` +
    `<div class="cc-price-row"><div class="cc-price">${fmtYen(model.price)}</div><div class="cc-change ${chgCls}">${fmtPct(model.changePct)}</div></div>` +
    `<div class="cc-freshness cc-freshness--${fresh.state}"><i class="cc-freshness-dot"></i>${esc(fresh.label ?? freshnessAgeText(model))}</div>` +
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
 * Compact horizontal row variant for "on-air" watch lists (実況銘柄カード) -
 * symbols currently being spoken about or actively monitored, so a missed
 * voice alert can still be confirmed on screen. Same model as
 * renderCockpitCard; only symbol/company/direction/price/changePct/
 * freshness/foot are used.
 */
export function renderCockpitWatchRow(model) {
  if (!model || !model.symbol) {
    throw new Error("renderCockpitWatchRow: model.symbol is required");
  }
  const { direction, label } = directionInfo(model);
  const fresh = resolveFreshness(model);
  const chg = isFiniteNumber(model.changePct) ? Number(model.changePct) : null;
  const chgCls = chg == null ? "cc-change--flat" : chg > 0 ? "cc-change--up" : chg < 0 ? "cc-change--down" : "cc-change--flat";

  return (
    `<div class="cc-watch-row cc-card--${direction}">` +
    `<div class="cc-identity"><span class="cc-company">${fmtScalar(model.company ?? model.symbol)}</span><span class="cc-symbol">TSE:${esc(model.symbol)}</span></div>` +
    `<span class="cc-badge">${esc(label)}</span>` +
    `<div class="cc-price-row"><div class="cc-price">${fmtYen(model.price)}</div><div class="cc-change ${chgCls}">${fmtPct(model.changePct)}</div></div>` +
    `<div class="cc-freshness cc-freshness--${fresh.state}"><i class="cc-freshness-dot"></i>${esc(fresh.label ?? freshnessAgeText(model))}</div>` +
    `</div>`
  );
}

if (typeof window !== "undefined") {
  window.renderCockpitCard = renderCockpitCard;
  window.renderCockpitWatchRow = renderCockpitWatchRow;
}
