/* NEXT board renderer. Display only. No orders, no MS2/RSS calls. */
(function () {
  "use strict";

  var REASONS = {
    PRICE_ACCEL_45S: "45秒加速",
    VOLUME_SURGE: "出来高急増",
    TURNOVER_ACCEL: "売買代金加速",
    HIGH_UPDATE: "高値更新",
    VWAP_SUPPORTIVE: "VWAP位置",
    OR5_ABOVE: "OR5上抜け",
    OR15_ABOVE: "OR15上抜け",
    OR5_INSIDE: "OR5内",
    OR15_INSIDE: "OR15内",
    SHALLOW_PULLBACK: "押しが浅い",
    RELATIVE_STRENGTH: "相対強度",
    RANK_VELOCITY_UP: "順位急上昇",
    PRICE_CHANGE_15S: "15秒の初動",
    LIQUIDITY_OK: "流動性",
    EMERGENCY_PROMOTION: "場中緊急昇格",
    SCHEDULED_RESELECT: "定時再選定",
    TOP_UNIVERSE_SCORE: "探索スコア上位"
  };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[ch];
    });
  }

  function finite(value) {
    return value != null && value !== "" && Number.isFinite(Number(value));
  }

  function fail(box, message) {
    box.innerHTML = '<div class="next-fail">FAIL-CLOSED：' + esc(message) + "</div>";
  }

  function rankChange(card) {
    if (!finite(card.previous_rank) || !finite(card.rank)) return "—";
    var delta = Number(card.previous_rank) - Number(card.rank);
    var sign = delta > 0 ? "+" : "";
    return card.previous_rank + "→" + card.rank + " (" + sign + delta + ")";
  }

  function render(board) {
    var meta = document.getElementById("next-discovery-meta");
    var box = document.getElementById("next-discovery-cards");
    if (!box) return;
    if (!board || typeof board !== "object" || !board.generated_at) {
      fail(box, "判定時刻のないデータは表示しません");
      return;
    }
    if (meta) {
      var mode = board.source_mode === "sample" ? "サンプル入力。実売買の根拠にはしません。" : "探索スナップショット。";
      meta.textContent = mode + " 更新 " + board.generated_at + " ／ Active100 " + (finite(board.active100_count) ? board.active100_count : "—") + " ／ 発注なし";
    }
    if (board.fail_closed) {
      fail(box, board.fail_closed_reason || "ユニバースを確定できないため NEXT を出しません");
      return;
    }
    var cards = Array.isArray(board.next5) ? board.next5 : null;
    if (!cards || board.funnel_fail_closed) {
      fail(box, board.funnel_reason || "NEXT5を確定できないため順位は出しません");
      return;
    }
    var html = cards.map(function (card) {
      if (!card || !card.symbol || !finite(card.score) || !card.state || !finite(card.next_rank)) return "";
      var reasons = Array.isArray(card.primary_reasons) ? card.primary_reasons.slice(0, 3) : [];
      var reasonHtml = reasons.map(function (code) {
        return "<span>" + esc(REASONS[code] || code) + "</span>";
      }).join("");
      return '<article class="next-card" data-symbol="' + esc(card.symbol) + '" data-next-rank="' + esc(card.next_rank) + '" data-state="' + esc(card.state) + '">' +
        '<div class="next-card-top"><span class="next-rank">#' + esc(card.next_rank) + '</span><b class="next-symbol">' + esc(card.symbol) + '</b></div>' +
        '<div class="next-score">' + Number(card.score).toFixed(1) + '</div>' +
        '<div class="next-meta"><span class="next-state">' + esc(card.state) + '</span><span>' + esc(rankChange(card)) + '</span></div>' +
        '<div class="next-reasons">' + reasonHtml + '</div></article>';
    }).join("");
    if (!html) {
      fail(box, "表示できるNEXT5がありません");
      return;
    }
    box.innerHTML = html;
  }

  function load() {
    var box = document.getElementById("next-discovery-cards");
    if (!box) return;
    fetch("next_board.json?t=" + Date.now(), {cache: "no-store"}).then(function (response) {
      if (!response.ok) throw new Error("missing");
      return response.json();
    }).then(render).catch(function () {
      fail(box, "NEXTボードを読めないため順位は出しません");
    });
  }

  window.renderNextBoard = render;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
